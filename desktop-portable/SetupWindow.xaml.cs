using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using Microsoft.Win32;

namespace ClashAssistant.Desktop;

/// <summary>Configuration only: no backend, emulator launch, ADB connect, or game input.</summary>
public partial class SetupWindow : Window
{
    private readonly DesktopSettings _settings;
    private static readonly Regex SerialPattern = new(@"^127\.0\.0\.1:(\d{1,5})$", RegexOptions.CultureInvariant);

    public SetupWindow(DesktopSettings settings)
    {
        _settings = settings;
        InitializeComponent();
        Height = Math.Min(770, SystemParameters.WorkArea.Height - 45);
        Status.Text = "配置保存在：" + settings.RuntimeConfigPath;
        if (File.Exists(settings.RuntimeConfigPath)) LoadSavedPaths();
        else
        {
            string bundledAdb = Path.Combine(settings.InstallRoot, "tools", "adb.exe");
            if (File.Exists(bundledAdb)) AdbPath.Text = bundledAdb;
        }
    }

    private void LoadSavedPaths()
    {
        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(_settings.RuntimeConfigPath));
            JsonElement root = document.RootElement;
            // Read only these public environment fields, never credentials or settings from the sender's machine.
            if (root.TryGetProperty("memuc", out var memuc) && memuc.ValueKind == JsonValueKind.String) MemucPath.Text = memuc.GetString();
            if (root.TryGetProperty("adb", out var adb) && adb.ValueKind == JsonValueKind.String) AdbPath.Text = adb.GetString();
            if (root.TryGetProperty("serial", out var serial) && serial.ValueKind == JsonValueKind.String) Serial.Text = serial.GetString();
            if (root.TryGetProperty("vm_index", out var index) && index.GetInt32() != 0)
                Status.Text = "已有配置使用了其他实例。分享版只支持 0 号实例，保存时会设为 0。";
        }
        catch (Exception error) when (error is IOException or JsonException or InvalidOperationException or FormatException)
        { Status.Text = "已有环境配置无法读取，请重新选择程序路径并保存。"; }
    }

    private void BrowseMemucClick(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFileDialog { Title = "选择 MEmu 的 memuc.exe", Filter = "MEmu 控制程序|memuc.exe", CheckFileExists = true };
        if (dialog.ShowDialog(this) == true) ChooseMemuc(dialog.FileName);
    }

    private void BrowseAdbClick(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFileDialog { Title = "选择 adb.exe", Filter = "ADB 程序|adb.exe", CheckFileExists = true };
        if (dialog.ShowDialog(this) == true) AdbPath.Text = dialog.FileName;
    }

    private void ChooseMemuc(string path)
    {
        MemucPath.Text = path;
        string adb = Path.Combine(Path.GetDirectoryName(path)!, "adb.exe");
        if (File.Exists(adb))
        {
            if (string.IsNullOrWhiteSpace(AdbPath.Text)) AdbPath.Text = adb;
        }
        else if (string.IsNullOrWhiteSpace(AdbPath.Text))
            Status.Text = "找到 memuc.exe，但同目录没有 adb.exe。请另行选择 Android platform-tools 的 adb.exe。";
    }

    private static IEnumerable<string> MemucCandidates()
    {
        foreach (var folder in new[] { Environment.SpecialFolder.ProgramFiles, Environment.SpecialFolder.ProgramFilesX86 })
        {
            string root = Environment.GetFolderPath(folder);
            if (!string.IsNullOrWhiteSpace(root)) yield return Path.Combine(root, "Microvirt", "MEmu", "memuc.exe");
        }
        // Inspect only public App Paths entries. No uninstall inventory or user profile scan.
        var discovered = new List<string>();
        foreach (RegistryHive hive in new[] { RegistryHive.LocalMachine, RegistryHive.CurrentUser })
        foreach (RegistryView view in new[] { RegistryView.Registry64, RegistryView.Registry32 })
        foreach (string application in new[] { "MEmu.exe", "memuc.exe" })
        {
            try
            {
                using var baseKey = RegistryKey.OpenBaseKey(hive, view);
                using var key = baseKey.OpenSubKey(@"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\" + application);
                string? executable = (key?.GetValue(null) as string)?.Trim().Trim('"');
                if (executable is not null && Path.IsPathFullyQualified(executable))
                    discovered.Add(Path.Combine(Path.GetDirectoryName(executable)!, "memuc.exe"));
                string? folder = key?.GetValue("Path") as string;
                if (!string.IsNullOrWhiteSpace(folder) && Path.IsPathFullyQualified(folder) && !folder.Contains(';'))
                    discovered.Add(Path.Combine(folder, "memuc.exe"));
            }
            catch (Exception error) when (error is System.Security.SecurityException or UnauthorizedAccessException or IOException)
            { /* A missing/inaccessible registration is not a failed installation. */ }
        }
        foreach (string candidate in discovered.Distinct(StringComparer.OrdinalIgnoreCase)) yield return candidate;
    }

    private void DiscoverClick(object sender, RoutedEventArgs e)
    {
        string? candidate = MemucCandidates().FirstOrDefault(File.Exists);
        if (candidate is null)
        {
            Status.Text = "没有在 Program Files 或公开的 App Paths 注册信息中找到 MEmu。请先安装 MEmu，或浏览选择现有安装目录中的 memuc.exe。";
            return;
        }
        ChooseMemuc(candidate);
        if (File.Exists(AdbPath.Text)) Status.Text = "已找到 MEmu 和 ADB。请手动打开 0 号实例，再点击“检测环境”。";
    }

    private (string Memuc, string Adb, string Serial) ValidatedInput()
    {
        static string Executable(string value, string name)
        {
            string trimmed = value.Trim();
            if (string.IsNullOrEmpty(trimmed)) throw new InvalidOperationException("请先选择 " + name + "。");
            if (!Path.IsPathFullyQualified(trimmed)) throw new InvalidOperationException(name + " 必须是完整路径。");
            string full = Path.GetFullPath(trimmed);
            if (!Path.GetFileName(full).Equals(name, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("请选择正确的 " + name + " 文件。");
            if (!File.Exists(full)) throw new FileNotFoundException(name + " 不存在，请重新选择安装路径。", full);
            return full;
        }
        string serial = Serial.Text.Trim();
        Match match = SerialPattern.Match(serial);
        if (!match.Success || !int.TryParse(match.Groups[1].Value, out int port) || port < 1 || port > 65535)
            throw new InvalidOperationException("仅支持本机 MEmu 0 号实例的回环地址，例如 127.0.0.1:21503。");
        return (Executable(MemucPath.Text, "memuc.exe"), Executable(AdbPath.Text, "adb.exe"), serial);
    }

    private async Task<(int ExitCode, string Text)> ReadAdbAsync(string adb, string serial, params string[] arguments)
    {
        string temp = Path.Combine(_settings.DataRoot, "work", "setup-temp");
        Directory.CreateDirectory(temp);
        return await ReadProcessAsync(adb, new[] { "-s", serial }.Concat(arguments).ToArray(), temp);
    }

    private static async Task<(int ExitCode, string Text)> ReadProcessAsync(string executable, string[] arguments, string temp)
    {
        var start = new ProcessStartInfo(executable) { UseShellExecute = false, CreateNoWindow = true,
            WorkingDirectory = Path.GetDirectoryName(executable)!, RedirectStandardOutput = true, RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8 };
        start.Environment["TEMP"] = temp;
        start.Environment["TMP"] = temp;
        foreach (string argument in arguments) start.ArgumentList.Add(argument);
        using var process = new Process { StartInfo = start };
        if (!process.Start()) throw new IOException("无法启动所选环境程序。");
        Task<string> stdout = process.StandardOutput.ReadToEndAsync();
        Task<string> stderr = process.StandardError.ReadToEndAsync();
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(8));
        try { await process.WaitForExitAsync(timeout.Token); }
        catch (OperationCanceledException)
        {
            try { process.Kill(entireProcessTree: false); } catch (InvalidOperationException) { }
            throw new TimeoutException("环境命令超过 8 秒。请确认模拟器已启动且设备已连接。");
        }
        string output = ((await stdout) + "\n" + (await stderr)).Trim();
        return (process.ExitCode, output.Length > 4096 ? output[..4096] : output);
    }

    private async void DetectClick(object sender, RoutedEventArgs e)
    {
        SetBusy(true);
        try
        {
            var input = ValidatedInput();
            await RequireInstanceZeroAsync(input.Memuc);
            var state = await ReadAdbAsync(input.Adb, input.Serial, "get-state");
            if (state.ExitCode != 0 || !state.Text.Split('\n').Any(line => line.Trim() == "device"))
            {
                DetectionResult.Text = "设备未就绪。请手动打开 MEmu 0 号实例，并完成 ADB 连接。\n" + state.Text;
                return;
            }
            var size = await ReadAdbAsync(input.Adb, input.Serial, "shell", "wm", "size");
            var density = await ReadAdbAsync(input.Adb, input.Serial, "shell", "wm", "density");
            var game = await ReadAdbAsync(input.Adb, input.Serial, "shell", "pm", "path", "com.tencent.tmgp.supercell.clashroyale");
            MatchCollection sizes = Regex.Matches(size.Text, @"(?:Physical|Override) size:\s*(\d+)x(\d+)");
            MatchCollection densities = Regex.Matches(density.Text, @"(?:Physical|Override) density:\s*(\d+)");
            bool sizeOk = size.ExitCode == 0 && sizes.Count > 0 && sizes[^1].Groups[1].Value == "419" && sizes[^1].Groups[2].Value == "633";
            bool densityOk = density.ExitCode == 0 && densities.Count > 0 && densities[^1].Groups[1].Value == "160";
            bool gameOk = game.ExitCode == 0 && game.Text.Split('\n').Any(line => line.TrimStart().StartsWith("package:", StringComparison.Ordinal));
            DetectionResult.Text = "ADB：已连接（" + input.Serial + "）\n" +
                "分辨率：" + (sizeOk ? "通过" : "需要手动设为 419 × 633") + "\n" + size.Text + "\n" +
                "DPI：" + (densityOk ? "通过" : "需要手动设为 160") + "\n" + density.Text + "\n" +
                "腾讯国服游戏：" + (gameOk ? "已安装" : "未检测到，请在模拟器内自行安装") + "\n" +
                (sizeOk && densityOk && gameOk ? "检测通过。请自己登录游戏，保存后在主界面手动开始。" : "请完成上述设置后再次检测；此次检测没有修改设备。") +
                "\n检测针对填写的设备地址，请确认它对应 MEmu 0 号实例。";
        }
        catch (Exception error) when (error is IOException or InvalidOperationException or UnauthorizedAccessException or TimeoutException or System.ComponentModel.Win32Exception)
        { DetectionResult.Text = "检测未完成：" + error.Message; }
        finally { SetBusy(false); }
    }

    private void SetBusy(bool busy)
    {
        DetectButton.IsEnabled = ScreenSetButton.IsEnabled = ScreenRestoreButton.IsEnabled = !busy;
    }

    private async Task RequireInstanceZeroAsync(string memuc)
    {
        string temp = Path.Combine(_settings.DataRoot, "work", "setup-temp");
        Directory.CreateDirectory(temp);
        var instances = await ReadProcessAsync(memuc, new[] { "listvms" }, temp);
        string? zero = instances.Text.Split('\n').FirstOrDefault(line => line.TrimStart().StartsWith("0,", StringComparison.Ordinal));
        if (instances.ExitCode != 0 || zero is null)
            throw new InvalidOperationException("MEmu 未返回 0 号实例。请确认 memuc.exe 正确，并手动创建、打开 MEmu 0 号实例。");
        string[] fields = zero.Trim().Split(',');
        if (fields.Length >= 5 && fields[4].Trim() != "1")
            throw new InvalidOperationException("MEmu 0 号实例尚未运行，请先手动打开。此次检测没有启动模拟器。");
    }

    private sealed record ScreenBackup(int Schema, string Serial, string SizeText, string DensityText, string? SizeOverride, string? DensityOverride);

    private async Task<ScreenBackup> ReadScreenAsync(string adb, string serial)
    {
        var size = await ReadAdbAsync(adb, serial, "shell", "wm", "size");
        var density = await ReadAdbAsync(adb, serial, "shell", "wm", "density");
        if (size.ExitCode != 0 || density.ExitCode != 0 ||
            !Regex.IsMatch(size.Text, @"Physical size:\s*\d+x\d+") ||
            !Regex.IsMatch(density.Text, @"Physical density:\s*\d+"))
            throw new InvalidOperationException("无法可靠读取原屏幕设置，已停止操作，请先检测设备连接。");
        Match sizeOverride = Regex.Match(size.Text, @"Override size:\s*(\d+x\d+)");
        Match densityOverride = Regex.Match(density.Text, @"Override density:\s*(\d+)");
        return new ScreenBackup(1, serial, size.Text, density.Text,
            sizeOverride.Success ? sizeOverride.Groups[1].Value : null,
            densityOverride.Success ? densityOverride.Groups[1].Value : null);
    }

    private async void SetScreenClick(object sender, RoutedEventArgs e)
    {
        SetBusy(true);
        bool commandIssued = false;
        string? backupPath = null;
        try
        {
            var input = ValidatedInput();
            if (MessageBox.Show(this, "仅修改所填设备 " + input.Serial + " 的屏幕覆盖设置为 419 × 633、DPI 160。\n请确认这是 MEmu 0 号实例。原设置会先备份；游戏需要你自行重新打开。是否继续？",
                "确认设置模拟器屏幕", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
            await RequireInstanceZeroAsync(input.Memuc);
            ScreenBackup before = await ReadScreenAsync(input.Adb, input.Serial);
            string work = Path.Combine(_settings.DataRoot, "work");
            Directory.CreateDirectory(work);
            backupPath = Path.Combine(work, "screen-before-" + DateTime.UtcNow.ToString("yyyyMMdd-HHmmss") + "-" + Guid.NewGuid().ToString("N")[..8] + ".json");
            File.WriteAllText(backupPath, JsonSerializer.Serialize(before, new JsonSerializerOptions { WriteIndented = true }), new UTF8Encoding(false));
            commandIssued = true;
            var size = await ReadAdbAsync(input.Adb, input.Serial, "shell", "wm", "size", "419x633");
            if (size.ExitCode != 0) throw new InvalidOperationException("设置分辨率返回失败：" + size.Text);
            var density = await ReadAdbAsync(input.Adb, input.Serial, "shell", "wm", "density", "160");
            if (density.ExitCode != 0) throw new InvalidOperationException("设置 DPI 返回失败：" + density.Text);
            ScreenBackup after = await ReadScreenAsync(input.Adb, input.Serial);
            MatchCollection sizes = Regex.Matches(after.SizeText, @"(?:Physical|Override) size:\s*(\d+x\d+)");
            MatchCollection densities = Regex.Matches(after.DensityText, @"(?:Physical|Override) density:\s*(\d+)");
            if (sizes.Count == 0 || densities.Count == 0 || sizes[^1].Groups[1].Value != "419x633" || densities[^1].Groups[1].Value != "160")
                throw new InvalidOperationException("重新读取的分辨率或 DPI 未达到目标。");
            DetectionResult.Text = "已验证屏幕覆盖设置：419 × 633、DPI 160。\n原设置备份：" + backupPath +
                "\n请手动关闭并重新打开游戏，再检测环境。没有启动游戏或任务。";
        }
        catch (Exception error) when (error is IOException or InvalidOperationException or UnauthorizedAccessException or TimeoutException or System.ComponentModel.Win32Exception)
        {
            DetectionResult.Text = "屏幕设置未完成：" + error.Message + (commandIssued
                ? "\n设备可能已发生部分更改。请点击“恢复原屏幕设置”。\n原设置备份：" + backupPath
                : "\n尚未发送屏幕修改命令。");
        }
        finally { SetBusy(false); }
    }

    private ScreenBackup LatestScreenBackup(string serial)
    {
        string work = Path.Combine(_settings.DataRoot, "work");
        if (!Directory.Exists(work)) throw new InvalidOperationException("没有找到此设备的屏幕备份，无法恢复。");
        foreach (string path in Directory.EnumerateFiles(work, "screen-before-*.json").OrderByDescending(Path.GetFileName, StringComparer.Ordinal))
        {
            try
            {
                var backup = JsonSerializer.Deserialize<ScreenBackup>(File.ReadAllText(path));
                if (backup is null || backup.Schema != 1 || backup.Serial != serial ||
                    !Regex.IsMatch(backup.SizeText ?? "", @"Physical size:\s*\d+x\d+") ||
                    !Regex.IsMatch(backup.DensityText ?? "", @"Physical density:\s*\d+")) continue;
                if (backup.SizeOverride is not null && !Regex.IsMatch(backup.SizeOverride, @"^\d+x\d+$")) continue;
                if (backup.DensityOverride is not null && !Regex.IsMatch(backup.DensityOverride, @"^\d+$")) continue;
                return backup;
            }
            catch (Exception error) when (error is JsonException or IOException) { }
        }
        throw new InvalidOperationException("没有找到此设备的有效屏幕备份，无法恢复。");
    }

    private async void RestoreScreenClick(object sender, RoutedEventArgs e)
    {
        SetBusy(true);
        bool commandIssued = false;
        try
        {
            var input = ValidatedInput();
            ScreenBackup before = LatestScreenBackup(input.Serial);
            if (MessageBox.Show(this, "将恢复设备 " + input.Serial + " 最近一次操作前的屏幕覆盖设置。\n分辨率：" + (before.SizeOverride ?? "恢复物理默认值") +
                "\nDPI：" + (before.DensityOverride ?? "恢复物理默认值") + "\n游戏需要你自行重新打开。是否继续？", "确认恢复模拟器屏幕",
                MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
            await RequireInstanceZeroAsync(input.Memuc);
            await ReadScreenAsync(input.Adb, input.Serial);
            commandIssued = true;
            var size = await ReadAdbAsync(input.Adb, input.Serial, "shell", "wm", "size", before.SizeOverride ?? "reset");
            if (size.ExitCode != 0) throw new InvalidOperationException("恢复分辨率返回失败：" + size.Text);
            var density = await ReadAdbAsync(input.Adb, input.Serial, "shell", "wm", "density", before.DensityOverride ?? "reset");
            if (density.ExitCode != 0) throw new InvalidOperationException("恢复 DPI 返回失败：" + density.Text);
            ScreenBackup after = await ReadScreenAsync(input.Adb, input.Serial);
            if (after.SizeOverride != before.SizeOverride || after.DensityOverride != before.DensityOverride)
                throw new InvalidOperationException("重新读取的屏幕设置与备份不一致。");
            DetectionResult.Text = "已重新读取并验证：屏幕覆盖设置已恢复。请自己重新打开游戏。\n" + after.SizeText + "\n" + after.DensityText;
        }
        catch (Exception error) when (error is IOException or InvalidOperationException or UnauthorizedAccessException or TimeoutException or System.ComponentModel.Win32Exception)
        { DetectionResult.Text = "屏幕恢复未完成：" + error.Message + (commandIssued ? "\n设备可能只恢复了一部分，请检查连接后重试；原备份仍然保留。" : "\n尚未发送屏幕修改命令。"); }
        finally { SetBusy(false); }
    }

    private void SaveClick(object sender, RoutedEventArgs e)
    {
        try
        {
            var input = ValidatedInput();
            Directory.CreateDirectory(Path.GetDirectoryName(_settings.RuntimeConfigPath)!);
            string temporary = _settings.RuntimeConfigPath + ".tmp-" + Guid.NewGuid().ToString("N");
            try
            {
                File.WriteAllText(temporary, JsonSerializer.Serialize(new { memuc = input.Memuc, adb = input.Adb,
                    serial = input.Serial, vm_index = 0 }, new JsonSerializerOptions { WriteIndented = true }) + "\n", new UTF8Encoding(false));
                File.Move(temporary, _settings.RuntimeConfigPath, overwrite: true);
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
            Status.Text = "已保存。关闭本窗口后，从“皇室战争助手”快捷方式打开主界面。软件不会自动开始对战。";
        }
        catch (Exception error) when (error is IOException or InvalidOperationException or UnauthorizedAccessException)
        { Status.Text = "配置未保存：" + error.Message + " 请确认安装目录允许当前用户写入。"; }
    }

    private void CloseClick(object sender, RoutedEventArgs e) => Close();
}
