using System;
using System.IO;
using System.Threading.Tasks;
using System.Windows;
using ClashAssistant.Desktop.Models;
using ClashAssistant.Desktop.Services;
using ClashAssistant.Desktop.ViewModels;

namespace ClashAssistant.Desktop;

internal sealed class MainWindow
{
    private readonly BackendClient _backend;
    private readonly DesktopViewModel _view;
    private readonly SettingsStub _settings;
    private bool _refreshing, _exiting, _configured, _preview, _hidden, _previewCollapsed, _detachedByUser;
    private bool _startCommandPending, _stopCommandPending, _stopRequestedForStart;
    private long _controlRevision;
    private DateTime _nextAttach = DateTime.MinValue;
    private ConsoleSnapshot? _snapshot;
    private readonly TrayStub? _tray = null;
    private readonly ScrollStub AutoScroll = new();
    private readonly LogStub LogBox = new();
    private readonly EmulatorStub EmulatorHost = new();
    public int AppliedSnapshotCount { get; private set; }
    public MainWindow(BackendClient backend, DesktopViewModel view, string root)
    { _backend = backend; _view = view; _settings = new(root); }
    public Task RefreshForTest() => RefreshAsync();
    public Task CommandForTest(string command) => RunCommandAsync(command);
    public void SeedForTest(ConsoleSnapshot snapshot) { _snapshot = snapshot; _view.Apply(snapshot); }
    public void ShowNotice(string value) => _view.Notice = value;
    private void SyncTray() { }
    private void TryAttach() { }
    private void PublishState() { AppliedSnapshotCount++; }
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
}
internal sealed record SettingsStub(string DataRoot);
internal sealed class TrayStub { public void SetStatus(string state, bool running, bool start, bool stop) { } }
internal sealed class ScrollStub { public bool? IsChecked => false; }
internal sealed class LogStub { public void ScrollToEnd() { } }
internal sealed class EmulatorStub
{
    public bool IsEmbedded => true;
    public void Configure(string executable, string root) { throw new Exception("fixture may never configure a real emulator"); }
}
internal static class App { public static void LogFailure(Exception error) { } }
