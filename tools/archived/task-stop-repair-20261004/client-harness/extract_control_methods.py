"""Compile actual command/refresh method bodies with inert UI collaborators."""
from pathlib import Path
import hashlib
import json

PROJECT = Path(__file__).resolve().parents[3]
ROOT = Path(__file__).resolve().parent
SOURCE = PROJECT / "desktop-wpf" / "MainWindow.xaml.cs"
text = SOURCE.read_text(encoding="utf-8-sig")

def extract(name: str) -> str:
    marker = "    private " + ("void " if name == "SyncCommandBusy" else "async Task ") + name + "("
    start = text.index(marker)
    body_start = text.index("\n    {", start)
    # These methods use regular indented C# braces. A top-level closing brace
    # is at exactly four spaces; nested blocks cannot end the extraction.
    end = text.index("\n    }", body_start + 6) + len("\n    }")
    return text[start:end]

names = ["RefreshAsync", "RunCommandAsync", "SyncCommandBusy"]
methods = [extract(name) for name in names]
generated = '''using System;
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
''' + "\n\n".join(methods) + '''
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
'''
(ROOT / "GeneratedControl.cs").write_text(generated, encoding="utf-8")
(ROOT / "control-source-evidence.json").write_text(json.dumps({
    "source": str(SOURCE), "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    "methods": {name: hashlib.sha256(method.encode()).hexdigest() for name, method in zip(names, methods)},
    "ui_collaborators": "inert; no game window, tray, production storage, or emulator commands",
}, indent=2), encoding="utf-8")
print("Extracted live MainWindow methods: " + ", ".join(names))
