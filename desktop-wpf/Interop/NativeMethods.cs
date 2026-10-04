using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;

namespace ClashAssistant.Desktop.Interop;

public static class NativeMethods
{
    public const string AppId = "Codex.ClashAssistant.Desktop.2026";
    internal const uint WsChild = 0x40000000, WsVisible = 0x10000000, WsClipChildren = 0x02000000, WsClipSiblings = 0x04000000;
    internal const uint WsPopup = 0x80000000, WindowChrome = 0x00C00000 | 0x00040000 | 0x00080000 | 0x00010000;
    internal const uint WsExAppWindow = 0x00040000;
    internal const int GwlStyle = -16, GwlExStyle = -20;
    internal const uint SwpNoZOrder = 0x0004, SwpNoActivate = 0x0010, SwpFrameChanged = 0x0020;

    public static bool SetAppIdentity()
    {
        // The established MEmu host uses per-monitor V1. Match the UI thread
        // before creating any WPF HWND, including when process DPI is fixed.
        SetProcessDpiAwarenessContext(new IntPtr(-3));
        SetThreadDpiAwarenessContext(new IntPtr(-3));
        return SetCurrentProcessExplicitAppUserModelID(AppId) == 0;
    }

    internal static void Check(bool success, string operation)
    {
        if (!success) throw new Win32Exception(Marshal.GetLastPInvokeError(), operation);
    }

    internal static uint ReadStyle(IntPtr hwnd, int index)
    {
        Marshal.SetLastPInvokeError(0);
        IntPtr value = GetWindowLongPtrW(hwnd, index);
        int error = Marshal.GetLastPInvokeError();
        if (value == IntPtr.Zero && error != 0) throw new Win32Exception(error);
        return unchecked((uint)value.ToInt64());
    }

    internal static void WriteStyle(IntPtr hwnd, int index, uint value)
    {
        Marshal.SetLastPInvokeError(0);
        IntPtr previous = SetWindowLongPtrW(hwnd, index, new IntPtr(unchecked((long)value)));
        int error = Marshal.GetLastPInvokeError();
        if (previous == IntPtr.Zero && error != 0) throw new Win32Exception(error);
    }

    internal static void Reparent(IntPtr hwnd, IntPtr parent)
    {
        Marshal.SetLastPInvokeError(0);
        IntPtr previous = SetParent(hwnd, parent);
        int error = Marshal.GetLastPInvokeError();
        if (previous == IntPtr.Zero && error != 0) throw new Win32Exception(error);
    }

    [StructLayout(LayoutKind.Sequential)] internal struct Point { public int X, Y; public Point(int x, int y) { X = x; Y = y; } }
    [StructLayout(LayoutKind.Sequential)] internal struct Rect { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] internal struct WindowPlacement
    {
        public uint Length, Flags, ShowCmd;
        public Point MinPosition, MaxPosition;
        public Rect NormalPosition;
    }

    internal delegate bool EnumWindowProc(IntPtr hwnd, IntPtr lparam);
    [DllImport("shell32.dll", CharSet = CharSet.Unicode)] private static extern int SetCurrentProcessExplicitAppUserModelID(string appId);
    [DllImport("user32.dll", SetLastError = true)] private static extern bool SetProcessDpiAwarenessContext(IntPtr context);
    [DllImport("user32.dll", SetLastError = true)] private static extern IntPtr SetThreadDpiAwarenessContext(IntPtr context);
    [DllImport("user32.dll")] internal static extern bool EnumWindows(EnumWindowProc callback, IntPtr parameter);
    [DllImport("user32.dll")] internal static extern bool EnumChildWindows(IntPtr parent, EnumWindowProc callback, IntPtr parameter);
    [DllImport("user32.dll")] internal static extern bool IsWindow(IntPtr hwnd);
    [DllImport("user32.dll")] internal static extern IntPtr GetWindow(IntPtr hwnd, uint command);
    [DllImport("user32.dll")] internal static extern IntPtr GetParent(IntPtr hwnd);
    [DllImport("user32.dll")] internal static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] internal static extern int GetWindowTextW(IntPtr hwnd, StringBuilder text, int length);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] internal static extern int GetClassNameW(IntPtr hwnd, StringBuilder text, int length);
    [DllImport("user32.dll", SetLastError = true)] internal static extern bool GetWindowRect(IntPtr hwnd, out Rect rect);
    [DllImport("user32.dll", SetLastError = true)] internal static extern bool GetClientRect(IntPtr hwnd, out Rect rect);
    [DllImport("user32.dll", SetLastError = true)] internal static extern bool ScreenToClient(IntPtr hwnd, ref Point point);
    [DllImport("user32.dll", SetLastError = true)] internal static extern bool GetWindowPlacement(IntPtr hwnd, ref WindowPlacement placement);
    [DllImport("user32.dll", SetLastError = true)] internal static extern bool SetWindowPlacement(IntPtr hwnd, ref WindowPlacement placement);
    [DllImport("user32.dll", SetLastError = true)] private static extern IntPtr GetWindowLongPtrW(IntPtr hwnd, int index);
    [DllImport("user32.dll", SetLastError = true)] private static extern IntPtr SetWindowLongPtrW(IntPtr hwnd, int index, IntPtr value);
    [DllImport("user32.dll", SetLastError = true)] private static extern IntPtr SetParent(IntPtr hwnd, IntPtr parent);
    [DllImport("user32.dll", SetLastError = true)] internal static extern bool SetWindowPos(IntPtr hwnd, IntPtr after, int x, int y, int width, int height, uint flags);
    [DllImport("user32.dll", SetLastError = true)] internal static extern bool PostMessageW(IntPtr hwnd, uint message, UIntPtr wparam, IntPtr lparam);
    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)] internal static extern IntPtr CreateWindowExW(uint exStyle, string className, string text, uint style, int x, int y, int width, int height, IntPtr parent, IntPtr menu, IntPtr instance, IntPtr parameter);
    [DllImport("user32.dll", SetLastError = true)] internal static extern bool DestroyWindow(IntPtr hwnd);
    [DllImport("kernel32.dll", SetLastError = true)] internal static extern IntPtr OpenProcess(uint access, bool inherit, int pid);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] internal static extern bool QueryFullProcessImageNameW(IntPtr process, uint flags, StringBuilder path, ref uint length);
    [DllImport("kernel32.dll")] internal static extern bool CloseHandle(IntPtr handle);
}
