using System.Diagnostics;
using System.IO.Compression;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace ClashAssistant.Installer;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        if (args.Length != 0)
        {
            ConsoleBridge.Initialize();
            try
            {
                if (args.Length == 1 && args[0] == "--self-check")
                {
                    var manifest = Payload.Check();
                    Console.WriteLine(JsonSerializer.Serialize(new
                    {
                        ok = true,
                        payload_sha256 = manifest.Sha256,
                        compressed_bytes = manifest.CompressedBytes,
                        files = manifest.Files,
                        directories = manifest.Directories,
                        expanded_bytes = manifest.ExpandedBytes,
                        architecture = "win-x64",
                        self_contained = true,
                    }));
                    return 0;
                }
                if (args.Length == 2 && args[0] == "--extract-only")
                {
                    var destination = InstallEngine.NormalizeDestination(args[1]);
                    if (!destination.StartsWith("D:\\codex\\", StringComparison.OrdinalIgnoreCase))
                        throw new InvalidOperationException("自动验证模式只允许写入 D:\\codex 内的全新或空目录。");
                    var result = InstallEngine.InstallAsync(destination, CancellationToken.None, null).GetAwaiter().GetResult();
                    Console.WriteLine(JsonSerializer.Serialize(new
                    {
                        ok = true,
                        destination = result.Destination,
                        payload_sha256 = result.Manifest.Sha256,
                        files = result.Manifest.Files,
                        expanded_bytes = result.Manifest.ExpandedBytes,
                        shortcuts_created = false,
                        application_started = false,
                    }));
                    return 0;
                }
                throw new ArgumentException("支持 --self-check 或 --extract-only <D:\\codex 内绝对路径>。");
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine(JsonSerializer.Serialize(new { ok = false, error = ex.Message }));
                return 1;
            }
        }

        ApplicationConfiguration.Initialize();
        Application.Run(new InstallerForm());
        return 0;
    }
}

internal record PayloadManifest(string Sha256, long CompressedBytes, int Files, int Directories, long ExpandedBytes);
internal record InstallProgress(int Percent, string Message);
internal record InstallResult(string Destination, PayloadManifest Manifest);

internal static class Payload
{
    private const string ZipResource = "ClashAssistant.Installer.payload.zip";
    private const string HashResource = "ClashAssistant.Installer.payload.sha256";
    private const long MaximumExpandedBytes = 32L * 1024 * 1024 * 1024;
    private const int MaximumEntries = 100_000;
    private static readonly HashSet<string> ReservedNames = new(StringComparer.OrdinalIgnoreCase)
    {
        "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9", "CONIN$", "CONOUT$",
    };

    internal static Stream Open()
        => Assembly.GetExecutingAssembly().GetManifestResourceStream(ZipResource)
            ?? throw new InvalidDataException("安装器缺少内嵌文件包。");

    internal static PayloadManifest Check(CancellationToken cancellationToken = default)
    {
        using var stream = Open();
        using var expectedStream = Assembly.GetExecutingAssembly().GetManifestResourceStream(HashResource)
            ?? throw new InvalidDataException("安装器缺少内嵌校验值。");
        using var reader = new StreamReader(expectedStream, Encoding.UTF8, detectEncodingFromByteOrderMarks: true);
        var expectedHash = reader.ReadToEnd().Trim();
        if (expectedHash.Length != 64 || !expectedHash.All(Uri.IsHexDigit))
            throw new InvalidDataException("内嵌校验值格式错误。");
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        var buffer = new byte[256 * 1024];
        int bytes;
        while ((bytes = stream.Read(buffer, 0, buffer.Length)) > 0)
        {
            cancellationToken.ThrowIfCancellationRequested();
            hash.AppendData(buffer, 0, bytes);
        }
        var actualHash = Convert.ToHexString(hash.GetHashAndReset());
        if (!CryptographicOperations.FixedTimeEquals(Convert.FromHexString(expectedHash), Convert.FromHexString(actualHash)))
            throw new InvalidDataException("安装器文件校验失败，请重新获取完整安装包。");
        var compressedBytes = stream.Length;
        stream.Position = 0;
        using var archive = new ZipArchive(stream, ZipArchiveMode.Read, leaveOpen: true);
        if (archive.Entries.Count == 0 || archive.Entries.Count > MaximumEntries)
            throw new InvalidDataException("文件包为空或文件数超出限制。");
        var paths = new Dictionary<string, bool>(StringComparer.OrdinalIgnoreCase);
        long expandedBytes = 0;
        int files = 0, directories = 0;
        foreach (var entry in archive.Entries)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var name = ValidateEntry(entry);
            bool directory = IsDirectory(entry);
            if (!paths.TryAdd(name, directory))
                throw new InvalidDataException($"文件包包含重复路径：{name}");
            if (directory) directories++;
            else
            {
                files++;
                expandedBytes = checked(expandedBytes + entry.Length);
                if (expandedBytes > MaximumExpandedBytes)
                    throw new InvalidDataException("文件包解压大小超出限制。");
            }
        }
        foreach (var path in paths.Keys)
        {
            var parent = Path.GetDirectoryName(path);
            while (!string.IsNullOrEmpty(parent))
            {
                if (paths.TryGetValue(parent, out bool directory) && !directory)
                    throw new InvalidDataException($"文件包路径冲突：{parent}");
                parent = Path.GetDirectoryName(parent);
            }
        }
        foreach (var required in new[] { "app\\ClashAssistant.Desktop.exe", "backend\\ClashBackend.exe" })
            if (!paths.TryGetValue(required, out bool directory) || directory)
                throw new InvalidDataException($"文件包缺少必要文件：{required}");
        return new(actualHash, compressedBytes, files, directories, expandedBytes);
    }

    internal static bool IsDirectory(ZipArchiveEntry entry)
        => entry.FullName.EndsWith('/') || entry.FullName.EndsWith('\\');

    internal static string ValidateEntry(ZipArchiveEntry entry)
    {
        var unixType = (entry.ExternalAttributes >> 16) & 0xF000;
        if (unixType is 0xA000 or 0x6000 or 0x2000 or 0x1000 or 0xC000
            || (entry.ExternalAttributes & (int)FileAttributes.ReparsePoint) != 0)
            throw new InvalidDataException("文件包包含不允许的链接或特殊文件。");
        var name = entry.FullName.Replace('/', '\\');
        if (IsDirectory(entry)) name = name.TrimEnd('\\');
        if (string.IsNullOrWhiteSpace(name) || Path.IsPathRooted(name) || name.Contains(':') || name.Length > 24_000)
            throw new InvalidDataException("文件包包含无效路径。");
        foreach (var segment in name.Split('\\'))
        {
            if (segment.Length == 0 || segment is "." or ".." || segment.EndsWith('.') || segment.EndsWith(' ')
                || segment.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0
                || ReservedNames.Contains(segment.Split('.')[0]))
                throw new InvalidDataException("文件包包含无效或越界路径。");
        }
        return name;
    }
}

internal static class InstallEngine
{
    internal static string NormalizeDestination(string path)
    {
        if (!Path.IsPathFullyQualified(path) || path.StartsWith("\\\\", StringComparison.Ordinal))
            throw new ArgumentException("请选择本机磁盘上的绝对路径。");
        var full = Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        if (full.Length <= 3 || full.Equals(Path.GetPathRoot(full)?.TrimEnd('\\'), StringComparison.OrdinalIgnoreCase))
            throw new ArgumentException("不能直接安装到磁盘根目录。");
        foreach (var segment in full[3..].Split('\\'))
            if (segment.Length == 0 || segment.EndsWith('.') || segment.EndsWith(' ') || segment.Contains(':'))
                throw new ArgumentException("安装路径含无效目录名称。");
        return full;
    }

    internal static void ValidateEmptyDestination(string destination)
    {
        RejectReparseAncestors(destination);
        if (File.Exists(destination)) throw new IOException("目标路径已存在同名文件，请选择新目录。");
        if (Directory.Exists(destination) && Directory.EnumerateFileSystemEntries(destination).Any())
            throw new IOException("目标目录不是空目录。为保护已有数据，请选择一个新目录或空目录。");
    }

    private static void RejectReparseAncestors(string path)
    {
        for (string? current = path; current is not null; current = Path.GetDirectoryName(current))
        {
            if ((File.Exists(current) || Directory.Exists(current))
                && (File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                throw new IOException("安装路径不能包含符号链接、联接点或其他重解析目录。");
            if (File.Exists(current) && !Directory.Exists(current))
                throw new IOException("安装路径的上级目录实际是文件。");
        }
    }

    internal static async Task<InstallResult> InstallAsync(string path, CancellationToken cancellationToken,
        IProgress<InstallProgress>? progress)
    {
        var destination = NormalizeDestination(path);
        ValidateEmptyDestination(destination);
        progress?.Report(new(0, "正在校验内嵌安装文件…"));
        var manifest = Payload.Check(cancellationToken);
        cancellationToken.ThrowIfCancellationRequested();
        var parent = Path.GetDirectoryName(destination)!;
        var createdParents = new List<string>();
        var stage = Path.Combine(parent, $".ClashAssistant-install-{Guid.NewGuid():N}");
        bool stageCreated = false, destinationCreated = false, committed = false;
        var createdDestinationFiles = new List<string>();
        var createdDestinationDirectories = new List<string>();
        try
        {
            var missingParents = new Stack<string>();
            for (string? current = parent; current is not null && !Directory.Exists(current); current = Path.GetDirectoryName(current))
                missingParents.Push(current);
            while (missingParents.TryPop(out var missing))
            {
                cancellationToken.ThrowIfCancellationRequested();
                RejectReparseAncestors(missing);
                Directory.CreateDirectory(missing);
                createdParents.Add(missing);
            }
            ValidateEmptyDestination(destination);
            if (File.Exists(stage) || Directory.Exists(stage)) throw new IOException("安装临时目录发生冲突。");
            Directory.CreateDirectory(stage);
            stageCreated = true;
            using (var stream = Payload.Open())
            using (var archive = new ZipArchive(stream, ZipArchiveMode.Read))
            {
                long written = 0;
                foreach (var entry in archive.Entries)
                {
                    cancellationToken.ThrowIfCancellationRequested();
                    var entryPath = Path.GetFullPath(Path.Combine(stage, Payload.ValidateEntry(entry)));
                    if (!entryPath.StartsWith(stage + "\\", StringComparison.OrdinalIgnoreCase))
                        throw new InvalidDataException("文件包包含越界路径。");
                    if (Payload.IsDirectory(entry)) { Directory.CreateDirectory(entryPath); continue; }
                    Directory.CreateDirectory(Path.GetDirectoryName(entryPath)!);
                    RejectReparseAncestors(entryPath);
                    using var source = entry.Open();
                    await using var output = new FileStream(entryPath, FileMode.CreateNew, FileAccess.Write, FileShare.None,
                        256 * 1024, FileOptions.Asynchronous | FileOptions.SequentialScan);
                    var buffer = new byte[256 * 1024];
                    long entryWritten = 0;
                    int read;
                    while ((read = await source.ReadAsync(buffer, cancellationToken)) != 0)
                    {
                        await output.WriteAsync(buffer.AsMemory(0, read), cancellationToken);
                        written += read;
                        entryWritten += read;
                        if (entryWritten > entry.Length) throw new InvalidDataException("文件包长度校验失败。");
                        var percent = manifest.ExpandedBytes == 0 ? 95 : (int)(written * 95 / manifest.ExpandedBytes);
                        progress?.Report(new(Math.Clamp(percent, 0, 95), $"正在安装：{entry.FullName}"));
                    }
                    if (entryWritten != entry.Length) throw new InvalidDataException("文件包长度校验失败。");
                }
            }
            cancellationToken.ThrowIfCancellationRequested();
            Directory.CreateDirectory(Path.Combine(stage, "data"));
            var runtimePath = Path.Combine(stage, "app", "wpf-runtime.json");
            await File.WriteAllTextAsync(runtimePath, JsonSerializer.Serialize(new
            {
                distribution = true,
                data_root = "../data",
                backend_path = "../backend/ClashBackend.exe",
            }, new JsonSerializerOptions { WriteIndented = true }), new UTF8Encoding(false), cancellationToken);
            cancellationToken.ThrowIfCancellationRequested();
            progress?.Report(new(97, "正在完成安装…"));
            ValidateEmptyDestination(destination);
            // The commit phase is deliberately bounded and cannot be cancelled mid-move.
            if (!Directory.Exists(destination))
            {
                Directory.Move(stage, destination);
                stageCreated = false;
                destinationCreated = true;
                committed = true;
            }
            else
            {
                foreach (var directory in Directory.EnumerateDirectories(stage, "*", SearchOption.AllDirectories)
                    .OrderBy(value => value.Length))
                {
                    var target = Path.Combine(destination, Path.GetRelativePath(stage, directory));
                    RejectReparseAncestors(target);
                    if (Directory.Exists(target) || File.Exists(target)) throw new IOException("目标目录在安装期间发生变化。");
                    Directory.CreateDirectory(target);
                    createdDestinationDirectories.Add(target);
                }
                foreach (var file in Directory.EnumerateFiles(stage, "*", SearchOption.AllDirectories))
                {
                    var target = Path.Combine(destination, Path.GetRelativePath(stage, file));
                    RejectReparseAncestors(target);
                    File.Move(file, target, overwrite: false);
                    createdDestinationFiles.Add(target);
                }
                committed = true;
            }
            progress?.Report(new(100, "安装完成。请先双击“首次使用.cmd”配置你自己的模拟器和游戏账号。"));
            return new(destination, manifest);
        }
        finally
        {
            if (!committed)
            {
                foreach (var file in createdDestinationFiles.AsEnumerable().Reverse()) TryDeleteOwnedFile(file);
                foreach (var directory in createdDestinationDirectories.AsEnumerable().Reverse()) TryDeleteEmptyDirectory(directory);
                if (destinationCreated) TryDeleteEmptyDirectory(destination);
            }
            if (stageCreated) TryDeleteOwnedStage(stage);
            if (!committed)
                foreach (var directory in createdParents.AsEnumerable().Reverse()) TryDeleteEmptyDirectory(directory);
        }
    }

    private static void TryDeleteOwnedFile(string file)
    {
        try { if (File.Exists(file) && (File.GetAttributes(file) & FileAttributes.ReparsePoint) == 0) File.Delete(file); }
        catch { /* Retain an inaccessible new file rather than touching other content. */ }
    }

    private static void TryDeleteEmptyDirectory(string directory)
    {
        try
        {
            if (Directory.Exists(directory) && (File.GetAttributes(directory) & FileAttributes.ReparsePoint) == 0
                && !Directory.EnumerateFileSystemEntries(directory).Any()) Directory.Delete(directory, recursive: false);
        }
        catch { }
    }

    private static void TryDeleteOwnedStage(string stage)
    {
        // Only this invocation's newly-created random staging directory is eligible for cleanup.
        try
        {
            if (!Directory.Exists(stage) || (File.GetAttributes(stage) & FileAttributes.ReparsePoint) != 0) return;
            foreach (var path in Directory.EnumerateFileSystemEntries(stage))
            {
                if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) continue;
                if (Directory.Exists(path)) TryDeleteOwnedStage(path);
                else TryDeleteOwnedFile(path);
            }
            TryDeleteEmptyDirectory(stage);
        }
        catch { }
    }
}

internal static class ShortcutWriter
{
    internal static List<string> Create(string destination, bool desktop, bool startMenu)
    {
        var warnings = new List<string>();
        var app = Path.Combine(destination, "app", "ClashAssistant.Desktop.exe");
        if (desktop) CreateOne(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),
            "Clash Assistant 分享版.lnk"), app, "", warnings);
        if (startMenu)
        {
            var folder = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "Clash Assistant 分享版");
            try
            {
                if (File.Exists(folder) || (Directory.Exists(folder) && (File.GetAttributes(folder) & FileAttributes.ReparsePoint) != 0))
                    throw new IOException("开始菜单目录不可用。");
                Directory.CreateDirectory(folder);
                CreateOne(Path.Combine(folder, "Clash Assistant.lnk"), app, "", warnings);
                CreateOne(Path.Combine(folder, "首次配置.lnk"), app, "--setup", warnings);
            }
            catch (Exception ex) { warnings.Add("未创建开始菜单快捷方式：" + ex.Message); }
        }
        return warnings;
    }

    private static void CreateOne(string path, string target, string arguments, List<string> warnings)
    {
        object? shell = null, shortcut = null;
        try
        {
            if (File.Exists(path) || Directory.Exists(path))
            {
                warnings.Add("已存在同名快捷方式，已保留：" + Path.GetFileName(path));
                return;
            }
            var type = Type.GetTypeFromProgID("WScript.Shell") ?? throw new InvalidOperationException("Windows 快捷方式组件不可用。");
            shell = Activator.CreateInstance(type) ?? throw new InvalidOperationException("无法创建 Windows 快捷方式组件。");
            dynamic dynamicShell = shell;
            shortcut = dynamicShell.CreateShortcut(path);
            dynamic dynamicShortcut = shortcut;
            dynamicShortcut.TargetPath = target;
            dynamicShortcut.Arguments = arguments;
            dynamicShortcut.WorkingDirectory = Path.GetDirectoryName(target);
            dynamicShortcut.IconLocation = target + ",0";
            dynamicShortcut.Description = string.IsNullOrEmpty(arguments) ? "Clash Assistant 分享版" : "配置自己的模拟器与游戏账号";
            dynamicShortcut.Save();
        }
        catch (Exception ex) { warnings.Add("未创建快捷方式：" + ex.Message); }
        finally
        {
            if (shortcut is not null && Marshal.IsComObject(shortcut)) Marshal.FinalReleaseComObject(shortcut);
            if (shell is not null && Marshal.IsComObject(shell)) Marshal.FinalReleaseComObject(shell);
        }
    }
}

internal sealed class InstallerForm : Form
{
    private readonly TextBox _destination = new();
    private readonly Button _browse = new();
    private readonly Button _install = new();
    private readonly Button _cancel = new();
    private readonly ProgressBar _progress = new();
    private readonly Label _status = new();
    private readonly CheckBox _desktop = new() { Text = "创建桌面快捷方式", Checked = true };
    private readonly CheckBox _startMenu = new() { Text = "创建开始菜单及首次配置快捷方式", Checked = true };
    private readonly CheckBox _launch = new() { Text = "完成后启动程序", Checked = false };
    private CancellationTokenSource? _cancellation;
    private bool _closeRequested;
    private bool _installed;

    internal InstallerForm()
    {
        Text = "Clash Assistant 分享版安装";
        Font = new Font("Microsoft YaHei UI", 9F);
        ClientSize = new Size(660, 480);
        MinimumSize = MaximumSize = Size;
        MaximizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        var heading = new Label { Text = "Clash Assistant", AutoSize = true, Font = new Font(Font.FontFamily, 18F, FontStyle.Bold), Location = new Point(24, 20) };
        var intro = new Label
        {
            Text = "适用于 Windows 10/11 64 位，已包含程序运行环境。\r\n请选择一个全新或空目录；安装器会保护已有文件，不要求管理员权限。",
            Location = new Point(26, 66), Size = new Size(610, 52),
        };
        var label = new Label { Text = "安装位置", Location = new Point(26, 126), AutoSize = true };
        _destination.SetBounds(26, 152, 514, 28);
        _destination.Text = Directory.Exists("D:\\") ? "D:\\Games\\ClashAssistant" : Path.Combine((Environment.GetEnvironmentVariable("SystemDrive") ?? "C:") + "\\", "Games", "ClashAssistant");
        _browse.Text = "浏览…";
        _browse.SetBounds(552, 151, 84, 30);
        _browse.Click += (_, _) =>
        {
            using var dialog = new FolderBrowserDialog { Description = "选择全新或空安装目录", UseDescriptionForTitle = true, SelectedPath = _destination.Text };
            if (dialog.ShowDialog(this) == DialogResult.OK) _destination.Text = dialog.SelectedPath;
        };
        _desktop.SetBounds(26, 196, 230, 24);
        _startMenu.SetBounds(26, 224, 380, 24);
        _launch.SetBounds(26, 252, 230, 24);
        var usage = new Label
        {
            Text = "安装完成后，请先双击安装目录中的“首次使用.cmd”，\r\n或打开开始菜单中的“首次配置”，配置自己的模拟器和游戏账号。\r\n原厂 MEmu 安装器位于 prerequisites 文件夹，需手动安装；安装系统驱动时可能需要管理员权限。",
            Location = new Point(26, 292), Size = new Size(610, 70), ForeColor = Color.FromArgb(55, 65, 80),
        };
        _progress.SetBounds(26, 368, 610, 17);
        _status.SetBounds(26, 392, 610, 32);
        _status.Text = "准备安装。个人记录将保存在安装目录中的 data 文件夹。";
        _install.Text = "开始安装";
        _install.SetBounds(430, 436, 98, 30);
        _install.Click += async (_, _) => await InstallAsync();
        _cancel.Text = "退出";
        _cancel.SetBounds(540, 436, 96, 30);
        _cancel.Click += (_, _) => { if (_cancellation is null) Close(); else { _cancellation.Cancel(); _status.Text = "正在取消并清理本次安装的临时文件…"; } };
        Controls.AddRange([heading, intro, label, _destination, _browse, _desktop, _startMenu, _launch, usage, _progress, _status, _install, _cancel]);
        FormClosing += (_, e) =>
        {
            if (_cancellation is null) return;
            e.Cancel = true;
            _closeRequested = true;
            _cancellation.Cancel();
            _status.Text = "正在取消并清理本次安装的临时文件…";
        };
    }

    private async Task InstallAsync()
    {
        if (_installed) { Close(); return; }
        string destination;
        try
        {
            destination = InstallEngine.NormalizeDestination(_destination.Text);
            InstallEngine.ValidateEmptyDestination(destination);
        }
        catch (Exception ex) { MessageBox.Show(this, ex.Message, "无法安装", MessageBoxButtons.OK, MessageBoxIcon.Information); return; }
        _destination.Text = destination;
        SetBusy(true);
        _cancellation = new CancellationTokenSource();
        var token = _cancellation.Token;
        var progress = new Progress<InstallProgress>(value => { _progress.Value = value.Percent; _status.Text = value.Message; });
        try
        {
            await Task.Run(() => InstallEngine.InstallAsync(destination, token, progress), token);
            var warnings = token.IsCancellationRequested ? [] : ShortcutWriter.Create(destination, _desktop.Checked, _startMenu.Checked);
            _installed = true;
            _status.Text = "安装完成！请先运行“首次使用.cmd”或开始菜单的“首次配置”。";
            _install.Text = "完成";
            if (warnings.Count > 0) MessageBox.Show(this, "程序已安装成功。\r\n" + string.Join("\r\n", warnings), "快捷方式提示", MessageBoxButtons.OK, MessageBoxIcon.Information);
            if (_launch.Checked && !token.IsCancellationRequested)
            {
                try
                {
                    Process.Start(new ProcessStartInfo(Path.Combine(destination, "app", "ClashAssistant.Desktop.exe"))
                    { UseShellExecute = true, WorkingDirectory = Path.Combine(destination, "app") });
                }
                catch (Exception ex) { MessageBox.Show(this, "程序已安装，但自动启动失败：" + ex.Message, "启动提示", MessageBoxButtons.OK, MessageBoxIcon.Information); }
            }
        }
        catch (OperationCanceledException) { _progress.Value = 0; _status.Text = "已取消安装。已有文件未被覆盖。"; }
        catch (Exception ex) { _status.Text = "安装失败。"; MessageBox.Show(this, ex.Message, "安装失败", MessageBoxButtons.OK, MessageBoxIcon.Error); }
        finally
        {
            _cancellation.Dispose();
            _cancellation = null;
            SetBusy(false);
            if (_closeRequested) Close();
        }
    }

    private void SetBusy(bool busy)
    {
        _destination.Enabled = _browse.Enabled = _desktop.Enabled = _startMenu.Enabled = _launch.Enabled = !busy && !_installed;
        _install.Enabled = !busy;
        _cancel.Text = busy ? "取消安装" : "退出";
    }
}

internal static class ConsoleBridge
{
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AttachConsole(uint processId);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern nint GetStdHandle(int standardHandle);

    internal static void Initialize()
    {
        var output = GetStdHandle(-11);
        if (output == 0 || output == -1) AttachConsole(uint.MaxValue);
        Console.OutputEncoding = new UTF8Encoding(false);
        Console.SetOut(new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false)) { AutoFlush = true });
        Console.SetError(new StreamWriter(Console.OpenStandardError(), new UTF8Encoding(false)) { AutoFlush = true });
    }
}
