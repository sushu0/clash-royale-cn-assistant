using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;
using System.Windows.Threading;

namespace ClashAssistant.Desktop.Interop;

/// <summary>Hosts the existing MEmu Qt tree, with a clipped and letterboxed game surface.</summary>
public sealed class NativeEmulatorHost : HwndHost
{
    private NativeWindowOwner? _owner;
    private IntPtr _viewport, _clip;
    private IntPtr _backgroundBrush;
    private readonly DispatcherTimer _timer;
    public bool IsEmbedded => _owner?.IsEmbedded ?? false;
    public string? LastError { get; private set; }
    public event Action<string>? Error;

    public NativeEmulatorHost()
    {
        _timer = new DispatcherTimer(DispatcherPriority.Background, Dispatcher) { Interval = TimeSpan.FromSeconds(1) };
        _timer.Tick += (_, _) =>
        {
            if (IsEmbedded) TryResize(refresh: true);
        };
        SizeChanged += (_, _) => TryResize();
    }

    public void Configure(string emulatorExe, string dataRoot)
    {
        VerifyAccess();
        if (_owner is not null) _owner.Detach();
        _owner = new NativeWindowOwner(emulatorExe, dataRoot);
        LastError = null;
    }

    protected override HandleRef BuildWindowCore(HandleRef hwndParent)
    {
        uint style = NativeMethods.WsChild | NativeMethods.WsVisible | NativeMethods.WsClipChildren | NativeMethods.WsClipSiblings | 4;
        _viewport = NativeMethods.CreateWindowExW(0, "STATIC", "", style, 0, 0, 1, 1, hwndParent.Handle, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
        if (_viewport == IntPtr.Zero) throw new System.ComponentModel.Win32Exception(Marshal.GetLastPInvokeError());
        // COLORREF stores RGB as 0x00BBGGRR. This brush belongs only to this
        // viewport; the shared Windows STATIC class is never changed.
        _backgroundBrush = CreateSolidBrush(0x00392214);
        if (_backgroundBrush == IntPtr.Zero)
        {
            int error = Marshal.GetLastPInvokeError();
            NativeMethods.DestroyWindow(_viewport); _viewport = IntPtr.Zero;
            throw new System.ComponentModel.Win32Exception(error, "创建原生游戏背景失败");
        }
        _clip = NativeMethods.CreateWindowExW(0, "STATIC", "", style, 0, 0, 1, 1, _viewport, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
        if (_clip == IntPtr.Zero)
        {
            int error = Marshal.GetLastPInvokeError();
            NativeMethods.DestroyWindow(_viewport); _viewport = IntPtr.Zero;
            DeleteObject(_backgroundBrush); _backgroundBrush = IntPtr.Zero;
            throw new System.ComponentModel.Win32Exception(error);
        }
        return new HandleRef(this, _viewport);
    }

    protected override IntPtr WndProc(IntPtr hwnd, int message, IntPtr wparam, IntPtr lparam, ref bool handled)
    {
        const int WmEraseBackground = 0x0014;
        if (hwnd == _viewport && message == WmEraseBackground && wparam != IntPtr.Zero && _backgroundBrush != IntPtr.Zero
            && NativeMethods.GetClientRect(hwnd, out var client) && FillRect(wparam, ref client, _backgroundBrush) != 0)
        {
            // The existing WS_CLIPCHILDREN HDC clipping keeps paint outside
            // the game surface. Other messages keep the original WPF routing.
            handled = true;
            return new IntPtr(1);
        }
        return base.WndProc(hwnd, message, wparam, lparam, ref handled);
    }

    [DllImport("gdi32.dll", SetLastError = true)] private static extern IntPtr CreateSolidBrush(uint color);
    [DllImport("gdi32.dll")] private static extern bool DeleteObject(IntPtr handle);
    [DllImport("user32.dll")] private static extern int FillRect(IntPtr deviceContext, ref NativeMethods.Rect rect, IntPtr brush);

    public void Attach()
    {
        VerifyAccess();
        if (_owner is null) throw new InvalidOperationException("请先配置模拟器和本地数据目录。");
        if (_clip == IntPtr.Zero) throw new InvalidOperationException("主界面尚未创建原生宿主窗口。");
        try
        {
            NativeMethods.Check(NativeMethods.GetClientRect(_viewport, out var rect), "读取宿主尺寸失败");
            int width = Math.Max(1, rect.Right), height = Math.Max(1, rect.Bottom);
            _owner.Attach(_clip.ToInt64(), width, height);
            ResizeCore();
            LastError = null;
            _timer.Start();
        }
        catch (Exception error) { LastError = error.Message; throw; }
    }

    public void Detach()
    {
        VerifyAccess();
        // Leave both HWNDs and the ownership lock intact on a failed restore.
        // The Window.Closing handler must cancel close on this exception.
        try { _owner?.Detach(); }
        catch (Exception error) { LastError = error.Message; throw; }
        _timer.Stop();
        LastError = null;
    }

    private void ResizeCore()
    {
        if (_owner?.Snapshot is not NativeWindowSnapshot saved || !IsEmbedded || _viewport == IntPtr.Zero) return;
        NativeMethods.Check(NativeMethods.GetClientRect(_viewport, out var client), "读取宿主尺寸失败");
        int viewportWidth = Math.Max(1, client.Right), viewportHeight = Math.Max(1, client.Bottom);
        int[] content = saved.ContentRect ?? new[] { 0, 0, saved.Rect[2] - saved.Rect[0], saved.Rect[3] - saved.Rect[1] };
        double scale = Math.Min(viewportWidth / (double)content[2], viewportHeight / (double)content[3]);
        int width = Math.Max(1, (int)Math.Round(content[2] * scale)), height = Math.Max(1, (int)Math.Round(content[3] * scale));
        NativeMethods.Check(NativeMethods.SetWindowPos(_clip, IntPtr.Zero, (viewportWidth - width) / 2, (viewportHeight - height) / 2,
            width, height, NativeMethods.SwpNoZOrder | NativeMethods.SwpNoActivate), "调整游戏显示区域失败");
        _owner.Resize(width, height);
    }

    private void TryResize(bool refresh = false)
    {
        if (!IsEmbedded) return;
        try { ResizeCore(); if (refresh) _owner?.RefreshRenderSurfaces(); LastError = null; }
        catch (Exception error) { LastError = error.Message; Error?.Invoke(error.Message); }
    }

    public Dictionary<string, object?> Diagnostics()
    {
        var result = _owner?.Diagnostics() ?? new Dictionary<string, object?> { ["embedded"] = false, ["game_input_sent"] = false };
        result["viewport_handle"] = _viewport.ToInt64(); result["clip_handle"] = _clip.ToInt64(); result["error"] = LastError;
        return result;
    }

    protected override void DestroyWindowCore(HandleRef hwnd)
    {
        Detach(); // A failed restore deliberately prevents destroying this HWND.
        _timer.Stop();
        if (_clip != IntPtr.Zero) { NativeMethods.Check(NativeMethods.DestroyWindow(_clip), "销毁游戏显示宿主失败"); _clip = IntPtr.Zero; }
        if (_viewport != IntPtr.Zero) { NativeMethods.Check(NativeMethods.DestroyWindow(_viewport), "销毁原生宿主失败"); _viewport = IntPtr.Zero; }
        if (_backgroundBrush != IntPtr.Zero) { DeleteObject(_backgroundBrush); _backgroundBrush = IntPtr.Zero; }
    }
}
