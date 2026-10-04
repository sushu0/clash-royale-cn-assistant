using System;
using System.IO;
using System.Text.Json;
using System.Windows;
using ClashAssistant.Desktop.Interop;
using ClashAssistant.Desktop.Services;

namespace ClashAssistant.Desktop;

public partial class App : Application
{
    private SingleInstance? _instance;
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        DispatcherUnhandledException += (_, args) =>
        {
            LogFailure(args.Exception);
            if (MainWindow is MainWindow main) main.ShowNotice("操作未完成：" + args.Exception.Message);
            args.Handled = true;
        };
        try
        {
            NativeMethods.SetAppIdentity();
            bool preview = Array.IndexOf(e.Args, "--preview") >= 0;
            if (!preview)
            {
                _instance = new SingleInstance();
                if (!_instance.Acquire()) { _instance.Dispose(); Shutdown(); return; }
            }
            var window = new MainWindow(preview);
            MainWindow = window;
            _instance?.Bind(window.ShowFromTray);
            window.Show();
        }
        catch (Exception error)
        {
            LogFailure(error);
            MessageBox.Show(error.Message, "皇室战争助手启动失败", MessageBoxButton.OK, MessageBoxImage.Error);
            Shutdown(1);
        }
    }

    internal static void LogFailure(Exception error)
    {
        try
        {
            var folder = Path.Combine(DesktopSettings.Load().DataRoot, "work", "wpf-desktop");
            Directory.CreateDirectory(folder);
            File.AppendAllText(Path.Combine(folder, "frontend-errors.log"), DateTimeOffset.Now.ToString("O") + " " + error + Environment.NewLine);
        }
        catch (Exception) { } // Logging must never interrupt startup or recovery.
    }

    protected override void OnExit(ExitEventArgs e) { _instance?.Dispose(); base.OnExit(e); }
}

public sealed record DesktopSettings(string DataRoot, string BackendPath)
{
    public static DesktopSettings Load()
    {
        string config = Path.Combine(AppContext.BaseDirectory, "wpf-runtime.json");
        using var data = JsonDocument.Parse(File.ReadAllText(config));
        string root = Path.GetFullPath(data.RootElement.GetProperty("data_root").GetString()!);
        if (!root.StartsWith(@"D:\codex\", StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("软件数据目录必须位于 D:\\codex。");
        string backend = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, data.RootElement.GetProperty("backend_path").GetString()!));
        return new DesktopSettings(root, backend);
    }
}
