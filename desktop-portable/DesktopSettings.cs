using System;
using System.IO;
using System.Text.Json;

namespace ClashAssistant.Desktop;

/// <summary>Sharing builds own only the directories under their installation.</summary>
public sealed record DesktopSettings(string DataRoot, string BackendPath, bool Distribution, string InstallRoot, string AppRoot)
{
    public string RuntimeConfigPath => Path.Combine(DataRoot, "work", "runtime-config.json");

    public bool IsOwned(string value)
    {
        string root = Path.GetFullPath(Distribution ? InstallRoot : @"D:\codex").TrimEnd(Path.DirectorySeparatorChar);
        string full = Path.GetFullPath(value);
        return full.Equals(root, StringComparison.OrdinalIgnoreCase) ||
            full.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase);
    }

    public static DesktopSettings Load(string? simulatedBaseDirectory = null)
    {
        using var document = JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "wpf-runtime.json")));
        JsonElement config = document.RootElement;
        bool distribution = config.TryGetProperty("distribution", out var flag) && flag.ValueKind == JsonValueKind.True;
        string appRoot = Path.GetFullPath(simulatedBaseDirectory ?? AppContext.BaseDirectory);
        string installRoot = Directory.GetParent(appRoot.TrimEnd(Path.DirectorySeparatorChar))!.FullName;
        string rootValue = config.GetProperty("data_root").GetString() ?? throw new InvalidDataException("缺少数据目录。");
        string backendValue = config.GetProperty("backend_path").GetString() ?? throw new InvalidDataException("缺少后端路径。");
        if (distribution && (Path.IsPathRooted(rootValue) || Path.IsPathRooted(backendValue)))
            throw new InvalidDataException("分享版程序和数据路径必须相对于安装目录。");
        string dataRoot = Path.GetFullPath(Path.Combine(appRoot, rootValue));
        string backend = Path.GetFullPath(Path.Combine(appRoot, backendValue));
        if (distribution && !dataRoot.Equals(Path.Combine(installRoot, "data"), StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("分享版数据目录必须是安装目录内的 data 文件夹。");
        var settings = new DesktopSettings(dataRoot, backend, distribution, installRoot, appRoot);
        if (!settings.IsOwned(dataRoot) || !settings.IsOwned(backend))
            throw new InvalidDataException(distribution ? "程序和数据路径必须位于本软件的安装目录。" : "软件数据目录必须位于 D:\\codex。");
        return settings;
    }

    public static string ValidateOwnedPath(string value, string name)
    {
        string full = Path.GetFullPath(value);
        if (!Load().IsOwned(full)) throw new ArgumentException("程序和数据路径必须位于本软件的安装目录。", name);
        return full;
    }
}
