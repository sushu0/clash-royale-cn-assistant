using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text.Json;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Threading;
using ClashAssistant.Desktop.Models;
using ClashAssistant.Desktop.Interop;
using ClashAssistant.Desktop.Services;
using ClashAssistant.Desktop.ViewModels;

namespace ClashAssistant.Desktop;

public partial class MainWindow : Window
{
    private readonly DesktopSettings _settings;
    private readonly DesktopViewModel _view;
    private readonly BackendClient _backend;
    private readonly bool _preview;
    private readonly DispatcherTimer _refreshTimer;
    private TrayService? _tray;
    private ConsoleSnapshot? _snapshot;
    private bool _refreshing, _closingForExit, _exiting, _hidden, _configured, _detachedByUser, _restoreOnShow;
    private bool _previewCollapsed, _previewWasEmbedded;
    private bool _startCommandPending, _stopCommandPending, _stopRequestedForStart;
    private long _controlRevision;
    private double _gameWidth = 320;
    private int _page;
    private DateTime _nextAttach = DateTime.MinValue;
    private DispatcherOperation? _pendingAttach;

    public MainWindow(bool preview)
    {
        _settings = DesktopSettings.Load();
        _preview = preview;
        _view = new DesktopViewModel(_settings.DataRoot, preview);
        _backend = new BackendClient(_settings.BackendPath, _settings.DataRoot, preview);
        InitializeComponent();
        DataContext = _view;
        Width = Math.Min(1480, SystemParameters.WorkArea.Width - 40);
        Height = Math.Min(920, SystemParameters.WorkArea.Height - 40);
        MinWidth = Math.Min(1240, Width); MinHeight = Math.Min(720, Height);
        if (preview) { Title = "皇室战争助手 · WPF预览"; EmulatorHost.Visibility = Visibility.Hidden; }
        SelectPage(0);
        _refreshTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1) };
        _refreshTimer.Tick += async (_, _) => await RefreshAsync();
        KeyDown += (_, e) =>
        {
            if (Keyboard.Modifiers == ModifierKeys.Control && e.Key >= Key.D1 && e.Key <= Key.D5)
                SelectPage(e.Key - Key.D1);
        };
    }

    private async void WindowLoaded(object sender, RoutedEventArgs e)
    {
        // A temporary startup failure must still be retried by the regular
        // refresh loop; otherwise the window remains unusable until restarted.
        _refreshTimer.Start();
        try
        {
            _tray = new TrayService(Path.Combine(AppContext.BaseDirectory, "clash-desktop.ico"), ShowFromTray,
                () => _ = RunCommandAsync("start"), () => _ = RunCommandAsync("stop"), () => _ = ExitAsync());
            await _backend.StartAsync();
            await RefreshAsync();
            _refreshTimer.Start();
            if (!_preview)
            {
                TryAttach();
                if (_snapshot is not null) _view.Notice = _view.State == "running" ? "已连接正在运行的任务。" : _view.StartHint;
            }
            else
            {
                _view.Notice = "界面预览已连接本机真实历史数据。";
                var previewTimer = new DispatcherTimer { Interval = TimeSpan.FromMinutes(5) };
                previewTimer.Tick += async (_, _) => { previewTimer.Stop(); await ExitAsync(); };
                previewTimer.Start();
            }
        }
        catch (Exception error) { App.LogFailure(error); ShowNotice("连接任务失败：" + error.Message); }
    }

    private async Task RefreshAsync()
    {
        if (_refreshing || _exiting || _startCommandPending || _stopCommandPending) return;
        _refreshing = true;
        long revision = _controlRevision;
        try
        {
            var snapshot = await _backend.GetSnapshotAsync();
            // A read already in flight when a command starts describes the old
            // task. It must not restore controls after that command completes.
            if (revision != _controlRevision || _startCommandPending || _stopCommandPending || _exiting) return;
            _snapshot = snapshot;
            _view.Apply(_snapshot);
            _tray?.SetStatus(_view.StateLabel.Replace("●", "").Trim(), _view.State is "running" or "starting", _view.CanStart, _view.CanStop);
            if (AutoScroll.IsChecked == true) LogBox.ScrollToEnd();
            if (!_preview && !_configured && !string.IsNullOrWhiteSpace(_snapshot.Runtime.Memuc))
            {
                EmulatorHost.Configure(Path.Combine(Path.GetDirectoryName(_snapshot.Runtime.Memuc)!, "MEmu.exe"), _settings.DataRoot);
                _configured = true;
            }
            if (!_preview && !_hidden && !_previewCollapsed && !_detachedByUser && !EmulatorHost.IsEmbedded && DateTime.UtcNow >= _nextAttach) TryAttach();
            PublishState();
        }
        catch (Exception error)
        {
            if (revision != _controlRevision || _startCommandPending || _stopCommandPending || _exiting) return;
            _view.MarkStateUnconfirmed();
            SyncTray();
            ShowNotice("状态同步暂未完成：" + error.Message);
            App.LogFailure(error);
        }
        finally { _refreshing = false; }
    }

    private async Task RunCommandAsync(string command)
    {
        if (_preview || _exiting) return;
        if (command == "start")
        {
            if (_startCommandPending || _stopCommandPending) return;
            _view.RefreshStopRequest();
            if (!_view.CanStart) { ShowNotice(_view.StartHint); return; }
        }
        if (command == "stop" && _stopCommandPending) return;
        if (command == "stop" && !_view.CanStop) { ShowNotice("当前没有正在运行的任务。"); return; }
        if (command == "start") { _startCommandPending = true; _stopRequestedForStart = false; }
        else { _stopCommandPending = true; _stopRequestedForStart |= _startCommandPending; }
        _controlRevision++;
        SyncCommandBusy();
        SyncTray();
        _view.Notice = command == "start" ? "正在连接游戏并开始对战…" : "正在停止后台任务…";
        if (_snapshot is not null) PublishState();
        try
        {
            var result = command == "start" ? await _backend.StartBotAsync() : await _backend.StopBotAsync();
            if (command == "stop" || !_stopRequestedForStart) _view.Notice = result.Message;
        }
        catch (Exception error)
        {
            if (command == "stop" || !_stopRequestedForStart) ShowNotice("操作未完成：" + error.Message);
            App.LogFailure(error);
        }
        finally
        {
            if (command == "start") _startCommandPending = false;
            else _stopCommandPending = false;
            _controlRevision++;
            SyncCommandBusy();
            if (_snapshot is not null) PublishState();
        }
        await RefreshAsync();
        if (command == "start" && !_stopRequestedForStart) { _detachedByUser = false; TryAttach(); }
    }

    private void SyncCommandBusy()
    {
        _view.SetBusy(_stopCommandPending || (_stopRequestedForStart && _startCommandPending) ? "stop" : _startCommandPending ? "start" : "");
        SyncTray();
    }

    private void StartClick(object sender, RoutedEventArgs e) => _ = RunCommandAsync("start");
    private void StopClick(object sender, RoutedEventArgs e) => _ = RunCommandAsync("stop");
    private void ExitClick(object sender, RoutedEventArgs e) => _ = ExitAsync();
    public void ShowNotice(string value) => _view.Notice = value;
    private void NavigateClick(object sender, RoutedEventArgs e)
    { if (sender is Button button && int.TryParse(button.Tag?.ToString(), out int page)) SelectPage(page); }
    private void SelectPage(int page)
    {
        _page = Math.Clamp(page, 0, 4); Pages.SelectedIndex = _page; _view.SelectPage(_page);
        foreach (var button in Navigation.Children.OfType<Button>())
        {
            bool active = button.Tag?.ToString() == _page.ToString();
            button.Background = new SolidColorBrush(active ? Color.FromRgb(42, 66, 107) : Colors.Transparent);
            button.Foreground = new SolidColorBrush(active ? Color.FromRgb(237, 243, 255) : Color.FromRgb(182, 193, 213));
            button.BorderBrush = new SolidColorBrush(active ? Color.FromRgb(55, 80, 114) : Colors.Transparent);
        }
        if (_page == 4 && AutoScroll.IsChecked == true)
            Dispatcher.BeginInvoke(DispatcherPriority.Loaded, new Action(() => { if (!_exiting && _page == 4) LogBox.ScrollToEnd(); }));
        if (_snapshot is not null) PublishState();
    }
    private void ScopeChanged(object sender, SelectionChangedEventArgs e)
    { if (sender is ComboBox combo && combo.SelectedItem is ComboBoxItem item) _view.SelectScope(item.Tag?.ToString() ?? "random"); }

    private void TryAttach()
    {
        if (_preview || !_configured || _hidden || _previewCollapsed || _exiting) return;
        _nextAttach = DateTime.UtcNow.AddSeconds(4);
        try
        {
            EmulatorHost.Visibility = Visibility.Visible;
            UpdateLayout();
            EmulatorHost.Attach();
            EmulatorPlaceholder.Visibility = Visibility.Collapsed;
            _view.EmulatorStatus = "模拟器 · 已连接";
        }
        catch (Exception error)
        {
            EmulatorHost.Visibility = Visibility.Hidden;
            EmulatorPlaceholder.Visibility = Visibility.Visible;
            _view.EmulatorStatus = "模拟器 · 等待连接";
            _view.Notice = "游戏窗口尚未连接：" + error.Message;
        }
    }
    private void AttachClick(object sender, RoutedEventArgs e) { _detachedByUser = false; TryAttach(); }
    private void DetachClick(object sender, RoutedEventArgs e)
    {
        try
        {
            EmulatorHost.Detach(); _detachedByUser = true; EmulatorHost.Visibility = Visibility.Hidden;
            EmulatorPlaceholder.Visibility = Visibility.Visible; _view.EmulatorStatus = "模拟器 · 独立窗口";
            _view.Notice = "游戏已恢复为独立窗口，任务状态保持不变。";
        }
        catch (Exception error) { ShowNotice("还原游戏窗口失败：" + error.Message); }
    }
    private void HideToTrayClick(object sender, RoutedEventArgs e) => HideToTray();
    private void CalibrationInfoClick(object sender, RoutedEventArgs e)
    {
        MessageBox.Show(this, "导航校准请求仍然保留，机器人保持停止。\n\n校准期间不会自动恢复对战，也不会因打开软件而清除请求。校准完成并解除停止请求后，再手动点击开始运行。", "导航校准", MessageBoxButton.OK, MessageBoxImage.Information);
    }
    private void LatestReportClick(object sender, RoutedEventArgs e)
    {
        _view.SelectedReport = _view.CurrentPauseReport; SelectPage(3);
    }
    private void SyncTray() => _tray?.SetStatus(_view.StateLabel.Replace("●", "").Trim(), _view.State is "running" or "starting", _view.CanStart, _view.CanStop);
    private void PreviewToggleClick(object sender, RoutedEventArgs e)
    {
        if (!_previewCollapsed)
        {
            bool embedded = EmulatorHost.IsEmbedded;
            var native = EmulatorHost.Diagnostics();
            long releasedWindow = native.TryGetValue("window_handle", out var handleValue) ? Convert.ToInt64(handleValue) : 0;
            uint releasedPid = native.TryGetValue("window_pid", out var pidValue) ? Convert.ToUInt32(pidValue) : 0;
            try { EmulatorHost.Detach(); }
            catch (Exception error) { ShowNotice("收起预览未完成，已保留游戏区：" + error.Message); return; }
            _pendingAttach?.Abort(); _pendingAttach = null;
            _previewWasEmbedded = embedded;
            _gameWidth = Math.Clamp(GameColumn.ActualWidth, 270, 480);
            _previewCollapsed = true;
            GamePane.Visibility = GameSplitter.Visibility = Visibility.Collapsed;
            GameColumn.MinWidth = 0; GameColumn.Width = new GridLength(0); SplitterColumn.Width = new GridLength(0);
            PreviewToggle.Content = "显示游戏";
            PreviewToggle.ToolTip = "恢复游戏预览";
            _view.EmulatorStatus = "模拟器 · 独立窗口";
            ShowNotice("游戏预览已收起，任务状态保持不变。");
            // Qt can raise its restored top-level window after SetWindowPlacement
            // returns. Set only its z-order after that queued work, keeping the
            // restored position, size, styles and renderer intact.
            var focusTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(250) };
            focusTimer.Tick += (_, _) =>
            {
                focusTimer.Stop();
                if (!_previewCollapsed || _hidden || _exiting || releasedWindow == 0) return;
                var hwnd = new IntPtr(releasedWindow);
                if (NativeMethods.IsWindow(hwnd) && NativeMethods.GetWindowThreadProcessId(hwnd, out uint pid) != 0 && pid == releasedPid)
                    NativeMethods.SetWindowPos(hwnd, new WindowInteropHelper(this).Handle, 0, 0, 0, 0, 0x0001 | 0x0002 | NativeMethods.SwpNoActivate);
                Activate();
            };
            focusTimer.Start();
        }
        else
        {
            _previewCollapsed = false;
            GameColumn.MinWidth = 270; GameColumn.Width = new GridLength(_gameWidth); SplitterColumn.Width = new GridLength(12);
            GamePane.Visibility = GameSplitter.Visibility = Visibility.Visible;
            PreviewToggle.Content = "收起游戏";
            PreviewToggle.ToolTip = "收起预览后，游戏恢复为独立窗口";
            UpdateLayout();
            if (_previewWasEmbedded && !_detachedByUser) TryAttach();
            ShowNotice("游戏预览已恢复。");
        }
        // Restoring the emulator's top-level window must not cover the data view.
        Activate();
        if (_snapshot is not null) PublishState();
    }
    private void LayoutSplitChanged(object sender, DragCompletedEventArgs e)
    {
        if (!_previewCollapsed) _gameWidth = Math.Clamp(GameColumn.ActualWidth, 270, 480);
        if (_snapshot is not null) PublishState();
    }
    private void WorkspaceSizeChanged(object sender, SizeChangedEventArgs e)
    {
        if (_previewCollapsed || e.NewSize.Width <= 0) return;
        double leftMinimum = Math.Min(580, Math.Max(360, e.NewSize.Width - 282));
        WorkspaceGrid.ColumnDefinitions[0].MinWidth = leftMinimum;
        GameColumn.MaxWidth = Math.Max(270, Math.Min(480, e.NewSize.Width - leftMinimum - 12));
    }
    private void HideToTray()
    {
        if (_tray is null || _exiting) return;
        _pendingAttach?.Abort(); _pendingAttach = null;
        _restoreOnShow |= EmulatorHost.IsEmbedded;
        try { EmulatorHost.Detach(); }
        catch (Exception error) { ShowNotice("游戏窗口还原失败，已保留主界面：" + error.Message); return; }
        _hidden = true; Hide(); PublishState();
    }
    public void ShowFromTray()
    {
        _hidden = false; Show(); if (WindowState == WindowState.Minimized) WindowState = WindowState.Normal; Activate();
        _view.Notice = "主界面已恢复。";
        if (_restoreOnShow)
        {
            _pendingAttach?.Abort();
            _pendingAttach = Dispatcher.BeginInvoke(DispatcherPriority.Loaded, new Action(() =>
            { _pendingAttach = null; if (!_hidden && !_exiting) { _restoreOnShow = false; TryAttach(); } }));
        }
    }
    private void WindowClosing(object? sender, CancelEventArgs e)
    { if (!_closingForExit) { e.Cancel = true; HideToTray(); } }
    private async Task ExitAsync()
    {
        if (_exiting || _view.IsBusy) { ShowNotice("请等待当前操作结束后再退出。"); return; }
        _exiting = true; _refreshTimer.Stop(); _pendingAttach?.Abort(); _pendingAttach = null;
        try
        {
            if (!_preview)
            {
                var current = await _backend.GetSnapshotAsync();
                if (current.State is "running" or "starting" or "stopping")
                {
                    _view.SetBusy("stop");
                    SyncTray();
                    if (_snapshot is not null) PublishState();
                    var stopped = await _backend.StopBotAsync();
                    if (stopped.State is not ("stopped" or "paused")) throw new InvalidOperationException("后台任务尚未停止，请稍后重试退出。");
                    var verified = await _backend.GetSnapshotAsync();
                    if (verified.State is not ("stopped" or "paused")) throw new InvalidOperationException("仍有运行中的任务，已保留软件窗口。");
                    _view.SetBusy("");
                }
            }
            EmulatorHost.Detach();
            await _backend.DisposeAsync();
            _tray?.Dispose(); _tray = null;
            _closingForExit = true; Close(); Application.Current.Shutdown();
        }
        catch (Exception error)
        {
            _exiting = false; _view.SetBusy(""); SyncTray(); _refreshTimer.Start(); ShowFromTray();
            ShowNotice("退出未完成，已保留软件窗口：" + error.Message); App.LogFailure(error);
        }
    }

    private void OpenReportsFolderClick(object sender, RoutedEventArgs e)
    {
        string folder = Path.Combine(_settings.DataRoot, "outputs", "error-reports"); Directory.CreateDirectory(folder); OpenFile(folder);
    }
    private void OpenReportClick(object sender, RoutedEventArgs e)
    {
        try
        {
            string? path = DesktopViewModel.LocalEvidence(_view.SelectedReport?.Record.ReportMd, Path.Combine(_settings.DataRoot, "outputs", "error-reports"), ".md");
            if (path is not null) OpenFile(path);
        }
        catch (Exception error) { ShowNotice("报告打开失败：" + error.Message); }
    }
    private void OpenScreenshotClick(object sender, RoutedEventArgs e)
    {
        try
        {
            string? path = DesktopViewModel.LocalEvidence(_view.SelectedReport?.Record.GamePng, Path.Combine(_settings.DataRoot, "outputs", "error-reports"), ".png");
            if (path is not null) OpenFile(path);
        }
        catch (Exception error) { ShowNotice("截图打开失败：" + error.Message); }
    }
    private void BattleDoubleClick(object sender, MouseButtonEventArgs e)
    {
        if (sender is not DataGrid grid || grid.SelectedItem is not BattleRow row) return;
        try
        {
            string? path = DesktopViewModel.LocalEvidence(row.Record.Evidence, Path.Combine(_settings.DataRoot, "work"), ".png");
            if (path is null) { ShowNotice("该场没有可用的结算图，历史记录保留。"); return; }
            string actual = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path)));
            if ((row.Record.Strategy == "random" || row.Record.EvidenceHash is not null) && !actual.Equals(row.Record.EvidenceHash, StringComparison.OrdinalIgnoreCase))
            { ShowNotice("结算图与保存的证据不匹配，请查看其他对局。"); return; }
            OpenFile(path);
        }
        catch (Exception error) { ShowNotice("结算图打开失败：" + error.Message); }
    }
    private void OpenFile(string path)
    {
        try { Process.Start(new ProcessStartInfo(path) { UseShellExecute = true }); }
        catch (Exception error) { ShowNotice("文件打开失败：" + error.Message); }
    }

    private void PublishState()
    {
        try
        {
            string folder = Path.Combine(_settings.DataRoot, "work", "wpf-desktop"); Directory.CreateDirectory(folder);
            string path = Path.Combine(folder, _preview ? "preview-state.json" : "frontend-state.json");
            var record = new
            {
                updated_at = DateTimeOffset.Now.ToString("O"), pid = Environment.ProcessId, frontend_language = "C#", framework = "WPF",
                preview = _preview, state = _view.State, visible = !_hidden, page = _page, backend_running = _backend.IsRunning,
                backend_path = _settings.BackendPath, report_count = _view.ReportCount,
                selected_report_md = _view.SelectedReport?.Record.ReportMd, selected_report_png = _view.SelectedReport?.Record.GamePng,
                metrics = new { total = _view.Total, wins = _view.Wins, losses = _view.Losses, rate = _view.WinRate, coins = _view.Coins, rewards = _view.Rewards },
                emulator = EmulatorHost.Diagnostics(), tray = _tray?.Diagnostics(), notice = _view.Notice,
                live = _snapshot?.Live,
                ui = new { phase = _view.Phase, description = _view.PhaseDescription, can_start = _view.CanStart, can_stop = _view.CanStop,
                    state_confirmed = _view.StateConfirmed, start_pending = _startCommandPending, stop_pending = _stopCommandPending,
                    calibration_requested = _view.HasCalibrationRequest, stop_requested = _view.HasStopRequest, report_badge = _view.ReportBadgeText,
                    preview_collapsed = _previewCollapsed, game_width = GameColumn.ActualWidth, recent_grid_height = RecentGrid.ActualHeight,
                    recent_row_count = _view.RecentBattles.Count, recent_visible_capacity = Math.Max(0, (int)Math.Floor((RecentGrid.ActualHeight - 36) / 36)),
                    layout_version = "2026.10.4.4" }
            };
            File.WriteAllText(path + ".tmp", JsonSerializer.Serialize(record, new JsonSerializerOptions { WriteIndented = true }));
            File.Move(path + ".tmp", path, true);
        }
        catch (Exception error) { App.LogFailure(error); }
    }
}
