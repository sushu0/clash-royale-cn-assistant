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
            int check = Array.IndexOf(e.Args, "--settings-check");
            if (check >= 0)
            {
                string? output = check + 1 < e.Args.Length && !e.Args[check + 1].StartsWith("--", StringComparison.Ordinal)
                    ? e.Args[check + 1] : null;
                int outputOption = Array.IndexOf(e.Args, "--settings-check-output");
                if (outputOption >= 0 && outputOption + 1 < e.Args.Length) output = e.Args[outputOption + 1];
                int testRoot = Array.IndexOf(e.Args, "--settings-test-root");
                string? simulatedBase = testRoot >= 0 && testRoot + 1 < e.Args.Length ? e.Args[testRoot + 1] : null;
                var settings = DesktopSettings.Load(simulatedBase);
                string result = JsonSerializer.Serialize(new { distribution = settings.Distribution,
                    install_root = settings.InstallRoot, app_root = settings.AppRoot,
                    data_root = settings.DataRoot, backend_path = settings.BackendPath,
                    config_path = settings.RuntimeConfigPath,
                    backend_exists = File.Exists(settings.BackendPath),
                    configuration_exists = File.Exists(settings.RuntimeConfigPath),
                    own_paths_valid = settings.IsOwned(settings.DataRoot) && settings.IsOwned(settings.BackendPath),
                    outside_install_rejected = !settings.IsOwned(Path.Combine(settings.InstallRoot, "..", "other-data")) },
                    new JsonSerializerOptions { WriteIndented = true });
                if (output is not null)
                {
                    string full = Path.GetFullPath(output);
                    if (!settings.IsOwned(full))
                        throw new InvalidDataException("验证结果必须保存在本软件的安装目录内。");
                    Directory.CreateDirectory(Path.GetDirectoryName(full)!);
                    File.WriteAllText(full, result);
                }
                else Console.WriteLine(result);
                Shutdown(0);
                return;
            }
            bool preview = Array.IndexOf(e.Args, "--preview") >= 0;
            var startupSettings = DesktopSettings.Load();
            if (Array.IndexOf(e.Args, "--setup") >= 0 ||
                startupSettings.Distribution && !preview && !File.Exists(startupSettings.RuntimeConfigPath))
            {
                var setup = new SetupWindow(startupSettings);
                MainWindow = setup;
                setup.Closed += (_, _) => Shutdown();
                setup.Show();
                return;
            }
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
