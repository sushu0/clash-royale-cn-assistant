using System;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Windows;
using System.Windows.Threading;
using ClashAssistant.Desktop.Interop;

namespace ClashAssistant.Desktop.Services;

/// <summary>Shares the existing Python mutex and Show event; no ports or commands.</summary>
public sealed class SingleInstance : IDisposable
{
    private Mutex? _mutex;
    private EventWaitHandle? _showEvent;
    private DispatcherTimer? _timer;
    private bool _disposed;
    public bool IsPrimary { get; private set; }
    public string MutexName { get; }
    public string ShowEventName { get; }

    public SingleInstance(string title = "皇室战争助手")
    {
        string digest = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(NativeMethods.AppId + ":" + title))).ToLowerInvariant()[..24];
        MutexName = @"Local\ClashAssistant." + digest + ".Instance";
        ShowEventName = @"Local\ClashAssistant." + digest + ".Show";
    }

    public bool Acquire()
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        if (_mutex is not null) return IsPrimary;
        // Create the event first to preserve an early duplicate launch before
        // the primary GUI's dispatcher has begun polling for Show.
        _showEvent = new EventWaitHandle(false, EventResetMode.AutoReset, ShowEventName);
        try { _mutex = new Mutex(false, MutexName, out bool created); IsPrimary = created; }
        catch { _showEvent.Dispose(); _showEvent = null; throw; }
        if (!IsPrimary) _showEvent.Set();
        return IsPrimary;
    }

    public void Bind(Action show)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        if (!IsPrimary || _showEvent is null || _timer is not null) return;
        Dispatcher dispatcher = Application.Current?.Dispatcher ?? Dispatcher.CurrentDispatcher;
        _timer = new DispatcherTimer(DispatcherPriority.Background, dispatcher) { Interval = TimeSpan.FromMilliseconds(120) };
        _timer.Tick += (_, _) => { if (!_disposed && _showEvent.WaitOne(0)) show(); };
        _timer.Start();
    }

    public bool ConsumeShowRequest() => !_disposed && IsPrimary && _showEvent is not null && _showEvent.WaitOne(0);

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _timer?.Stop(); _timer = null;
        // No thread owns this mutex; its named-object lifetime is the gate,
        // exactly like CreateMutex(initialOwner=False) in the Python shell.
        _mutex?.Dispose(); _mutex = null;
        _showEvent?.Dispose(); _showEvent = null;
    }
}
