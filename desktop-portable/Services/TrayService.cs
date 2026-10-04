using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Windows;
using System.Windows.Threading;
using ClashAssistant.Desktop.Interop;
using Forms = System.Windows.Forms;

namespace ClashAssistant.Desktop.Services;

/// <summary>NotifyIcon owns Explorer-restart recovery; all actions use the WPF dispatcher.</summary>
public sealed class TrayService : IDisposable
{
    private readonly Dispatcher _dispatcher;
    private readonly Forms.NotifyIcon _notification;
    private readonly Forms.ContextMenuStrip _menu;
    private readonly Forms.ToolStripMenuItem _start, _stop;
    private readonly Icon _icon;
    private bool _disposed, _running;
    private string _status = "就绪";

    public TrayService(string iconPath, Action show, Action start, Action stop, Action exit)
    {
        _dispatcher = Application.Current?.Dispatcher ?? Dispatcher.CurrentDispatcher;
        _icon = File.Exists(iconPath) ? new Icon(iconPath) : (Icon)SystemIcons.Application.Clone();
        _menu = new Forms.ContextMenuStrip();
        Forms.ToolStripMenuItem showItem = new("显示主界面");
        showItem.Click += (_, _) => Dispatch(show);
        _start = new("开始运行"); _start.Click += (_, _) => Dispatch(start);
        _stop = new("停止任务") { Enabled = false }; _stop.Click += (_, _) => Dispatch(stop);
        Forms.ToolStripMenuItem exitItem = new("退出软件（停止任务）"); exitItem.Click += (_, _) => Dispatch(exit);
        _menu.Items.AddRange(new Forms.ToolStripItem[] { showItem, _start, _stop, new Forms.ToolStripSeparator(), exitItem });
        _notification = new Forms.NotifyIcon { Icon = _icon, Text = "皇室战争助手 · 就绪", ContextMenuStrip = _menu, Visible = true };
        _notification.MouseClick += (_, args) => { if (args.Button == Forms.MouseButtons.Left) Dispatch(show); };
        _notification.DoubleClick += (_, _) => Dispatch(show);
    }

    private void Dispatch(Action callback)
    {
        if (_disposed || _dispatcher.HasShutdownStarted) return;
        _dispatcher.BeginInvoke(DispatcherPriority.Normal, new Action(() => { if (!_disposed) callback(); }));
    }

    public void SetStatus(string status, bool running = false, bool? canStart = null, bool? canStop = null)
    {
        if (_disposed) return;
        if (!_dispatcher.CheckAccess()) { Dispatch(() => SetStatus(status, running, canStart, canStop)); return; }
        _status = status;
        _running = running;
        string text = ("皇室战争助手 · " + status).Replace('\0', ' ');
        if (text.Length > 63) text = text[..63];
        if (text.Length > 0 && char.IsHighSurrogate(text[^1])) text = text[..^1];
        _notification.Text = text;
        _start.Enabled = canStart ?? !running; _stop.Enabled = canStop ?? running;
    }

    public Dictionary<string, object?> Diagnostics() => new()
    {
        ["app_id"] = NativeMethods.AppId, ["tray_ready"] = !_disposed, ["tray_icon_added"] = !_disposed && _notification.Visible,
        ["tooltip"] = _notification.Text, ["status"] = _status, ["running"] = _running, ["closed"] = _disposed,
        ["start_enabled"] = _start.Enabled, ["stop_enabled"] = _stop.Enabled
    };

    public void Dispose()
    {
        if (_disposed) return;
        if (!_dispatcher.CheckAccess() && !_dispatcher.HasShutdownStarted) { _dispatcher.Invoke(Dispose); return; }
        _disposed = true;
        _notification.Visible = false;
        _notification.Dispose(); _menu.Dispose(); _icon.Dispose();
    }
}
