using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json.Serialization;
using System.Threading;

namespace ClashAssistant.Desktop.Interop;

public sealed class NativePlacementData
{
    [JsonRequired, JsonPropertyName("flags")] public uint Flags { get; set; }
    [JsonRequired, JsonPropertyName("showCmd")] public uint ShowCmd { get; set; }
    [JsonRequired, JsonPropertyName("ptMinPosition")] public int[] MinPosition { get; set; } = Array.Empty<int>();
    [JsonRequired, JsonPropertyName("ptMaxPosition")] public int[] MaxPosition { get; set; } = Array.Empty<int>();
    [JsonRequired, JsonPropertyName("rcNormalPosition")] public int[] NormalPosition { get; set; } = Array.Empty<int>();
}

public sealed class NativeWindowSnapshot
{
    [JsonRequired, JsonPropertyName("hwnd")] public long Hwnd { get; set; }
    [JsonRequired, JsonPropertyName("pid")] public int Pid { get; set; }
    [JsonRequired, JsonPropertyName("parent")] public long Parent { get; set; }
    [JsonRequired, JsonPropertyName("style")] public uint Style { get; set; }
    [JsonRequired, JsonPropertyName("ex_style")] public uint ExStyle { get; set; }
    [JsonRequired, JsonPropertyName("placement")] public NativePlacementData Placement { get; set; } = new();
    [JsonRequired, JsonPropertyName("rect")] public int[] Rect { get; set; } = Array.Empty<int>();
    [JsonPropertyName("content_rect")] public int[]? ContentRect { get; set; }

    public void Validate()
    {
        if (Hwnd <= 0 || Pid <= 0 || Parent < 0 || Rect is not { Length: 4 } || Rect[2] <= Rect[0] || Rect[3] <= Rect[1]
            || Placement is null || Placement.MinPosition is not { Length: 2 } || Placement.MaxPosition is not { Length: 2 }
            || Placement.NormalPosition is not { Length: 4 }
            || (ContentRect is not null && (ContentRect.Length != 4 || ContentRect[2] <= 0 || ContentRect[3] <= 0)))
            throw new InvalidOperationException("窗口恢复记录无效；已保留原文件。");
    }
}

public interface INativeWindowApi
{
    long? FindWindow(string executable);
    bool IsWindow(long hwnd, int pid);
    string? WindowExecutable(long hwnd);
    double? ProcessCreatedAt(int pid);
    NativeWindowSnapshot Snapshot(long hwnd);
    void SetStyle(long hwnd, uint style);
    void SetExStyle(long hwnd, uint style);
    void SetParent(long hwnd, long parent);
    void MoveWindow(long hwnd, int x, int y, int width, int height);
    void ResizeRenderSurfaces(long hwnd);
    void Restore(long hwnd, NativeWindowSnapshot snapshot);
}

public sealed class NativeWindowApi : INativeWindowApi
{
    private static int Pid(long hwnd) { NativeMethods.GetWindowThreadProcessId(new IntPtr(hwnd), out uint pid); return (int)pid; }
    private static string Text(long hwnd, bool windowClass = false)
    {
        StringBuilder text = new(512);
        if (windowClass) NativeMethods.GetClassNameW(new IntPtr(hwnd), text, text.Capacity);
        else NativeMethods.GetWindowTextW(new IntPtr(hwnd), text, text.Capacity);
        return text.ToString();
    }

    private static List<long> Windows(long parent = 0)
    {
        List<long> result = new();
        NativeMethods.EnumWindowProc collect = (hwnd, _) => { result.Add(hwnd.ToInt64()); return true; };
        if (parent == 0) NativeMethods.EnumWindows(collect, IntPtr.Zero);
        else NativeMethods.EnumChildWindows(new IntPtr(parent), collect, IntPtr.Zero);
        GC.KeepAlive(collect);
        return result;
    }

    private static string? Executable(int pid)
    {
        IntPtr process = NativeMethods.OpenProcess(0x1000, false, pid);
        if (process == IntPtr.Zero) return null;
        try
        {
            StringBuilder text = new(32768);
            uint length = (uint)text.Capacity;
            return NativeMethods.QueryFullProcessImageNameW(process, 0, text, ref length) ? Path.GetFullPath(text.ToString()) : null;
        }
        finally { NativeMethods.CloseHandle(process); }
    }

    private static long? Renderer(long hwnd)
    {
        foreach (long child in Windows(hwnd))
            if (Text(child) == "RenderWindowWindow" && NativeMethods.GetClientRect(new IntPtr(child), out var rect) && rect.Right > 0 && rect.Bottom > 0)
                return child;
        return null;
    }

    internal static bool SamePath(string? left, string? right) => left is not null && right is not null
        && string.Equals(Path.GetFullPath(left), Path.GetFullPath(right), StringComparison.OrdinalIgnoreCase);

    public long? FindWindow(string executable)
    {
        List<long> matches = new();
        Dictionary<int, string?> paths = new();
        foreach (long hwnd in Windows())
        {
            if (NativeMethods.GetWindow(new IntPtr(hwnd), 4) != IntPtr.Zero || !Text(hwnd, true).StartsWith("Qt", StringComparison.Ordinal)) continue;
            int pid = Pid(hwnd);
            if (!paths.TryGetValue(pid, out string? path)) paths[pid] = path = Executable(pid);
            if (SamePath(path, executable) && Renderer(hwnd) is not null) matches.Add(hwnd);
        }
        return matches.Count == 1 ? matches[0] : null;
    }

    public bool IsWindow(long hwnd, int pid) => NativeMethods.IsWindow(new IntPtr(hwnd)) && Pid(hwnd) == pid;
    public string? WindowExecutable(long hwnd) => Executable(Pid(hwnd));
    public double? ProcessCreatedAt(int pid)
    {
        try
        {
            using Process process = Process.GetProcessById(pid);
            return (process.StartTime.ToUniversalTime() - DateTime.UnixEpoch).TotalSeconds;
        }
        catch (ArgumentException) { return null; }
        catch (InvalidOperationException) { return null; }
    }

    public NativeWindowSnapshot Snapshot(long hwnd)
    {
        int pid = Pid(hwnd);
        if (pid == 0 || !IsWindow(hwnd, pid)) throw new InvalidOperationException("模拟器窗口已经关闭。");
        NativeMethods.Check(NativeMethods.GetWindowRect(new IntPtr(hwnd), out var rect), "读取模拟器位置失败");
        var placement = new NativeMethods.WindowPlacement { Length = (uint)Marshal.SizeOf<NativeMethods.WindowPlacement>() };
        NativeMethods.Check(NativeMethods.GetWindowPlacement(new IntPtr(hwnd), ref placement), "读取模拟器布局失败");
        int[]? content = null;
        if (Renderer(hwnd) is long renderer && NativeMethods.GetWindowRect(new IntPtr(renderer), out var renderRect))
        {
            var point = new NativeMethods.Point(renderRect.Left, renderRect.Top);
            if (NativeMethods.ScreenToClient(new IntPtr(hwnd), ref point))
                content = new[] { point.X, point.Y, renderRect.Right - renderRect.Left, renderRect.Bottom - renderRect.Top };
        }
        return new NativeWindowSnapshot
        {
            Hwnd = hwnd, Pid = pid, Parent = NativeMethods.GetParent(new IntPtr(hwnd)).ToInt64(),
            Style = NativeMethods.ReadStyle(new IntPtr(hwnd), NativeMethods.GwlStyle), ExStyle = NativeMethods.ReadStyle(new IntPtr(hwnd), NativeMethods.GwlExStyle),
            Rect = new[] { rect.Left, rect.Top, rect.Right, rect.Bottom }, ContentRect = content,
            Placement = new NativePlacementData { Flags = placement.Flags, ShowCmd = placement.ShowCmd,
                MinPosition = new[] { placement.MinPosition.X, placement.MinPosition.Y }, MaxPosition = new[] { placement.MaxPosition.X, placement.MaxPosition.Y },
                NormalPosition = new[] { placement.NormalPosition.Left, placement.NormalPosition.Top, placement.NormalPosition.Right, placement.NormalPosition.Bottom } }
        };
    }

    public void SetStyle(long hwnd, uint style) => NativeMethods.WriteStyle(new IntPtr(hwnd), NativeMethods.GwlStyle, style);
    public void SetExStyle(long hwnd, uint style) => NativeMethods.WriteStyle(new IntPtr(hwnd), NativeMethods.GwlExStyle, style);
    public void SetParent(long hwnd, long parent) => NativeMethods.Reparent(new IntPtr(hwnd), new IntPtr(parent));
    public void MoveWindow(long hwnd, int x, int y, int width, int height)
    {
        if (width <= 0 || height <= 0) throw new ArgumentOutOfRangeException(nameof(width));
        NativeMethods.Check(NativeMethods.SetWindowPos(new IntPtr(hwnd), IntPtr.Zero, x, y, width, height,
            NativeMethods.SwpNoZOrder | NativeMethods.SwpNoActivate | NativeMethods.SwpFrameChanged), "调整模拟器布局失败");
    }

    private (long Renderer, (long Hwnd, int Pid)[] Surfaces, int Width, int Height) ResizeTree(long hwnd)
    {
        int rootPid = Pid(hwnd);
        string? rootPath = Executable(rootPid);
        if (!IsWindow(hwnd, rootPid) || rootPath is null || !string.Equals(Path.GetFileName(rootPath), "MEmu.exe", StringComparison.OrdinalIgnoreCase)
            || !Text(hwnd, true).StartsWith("Qt", StringComparison.Ordinal)) throw new InvalidOperationException("无法确认原模拟器窗口；已停止调整。");
        NativeMethods.Check(NativeMethods.GetClientRect(new IntPtr(hwnd), out var rootRect), "读取模拟器客户区失败");
        if (rootRect.Right <= rootRect.Left || rootRect.Bottom <= rootRect.Top) throw new InvalidOperationException("模拟器主窗口尺寸不可用。");
        long renderer = Renderer(hwnd) ?? throw new InvalidOperationException("未找到原模拟器渲染窗口。");
        if (!IsWindow(renderer, rootPid) || !Text(renderer, true).StartsWith("Qt", StringComparison.Ordinal)) throw new InvalidOperationException("渲染窗口身份不匹配。");
        long parent = NativeMethods.GetParent(new IntPtr(renderer)).ToInt64();
        if (!IsWindow(parent, rootPid) || Text(parent) != "CenterWidgetWindow") throw new InvalidOperationException("渲染窗口父级不匹配。");
        NativeMethods.Check(NativeMethods.GetClientRect(new IntPtr(renderer), out var client), "读取渲染区失败");
        int width = client.Right - client.Left, height = client.Bottom - client.Top;
        if (width <= 0 || height <= 0) throw new InvalidOperationException("渲染窗口尺寸不可用。");
        var children = Windows(renderer).Where(child => Text(child, true) == "subWin" && Text(child) == "sub").ToArray();
        if (children.Length != 2) throw new InvalidOperationException("模拟器渲染子窗口结构不明确。");
        long outer = children.FirstOrDefault(child => NativeMethods.GetParent(new IntPtr(child)).ToInt64() == renderer);
        long inner = children.FirstOrDefault(child => NativeMethods.GetParent(new IntPtr(child)).ToInt64() == outer);
        if (outer == 0 || inner == 0) throw new InvalidOperationException("模拟器渲染子窗口层级不匹配。");
        int surfacePid = Pid(outer);
        string? surfacePath = Executable(surfacePid);
        if (surfacePath is null || !string.Equals(Path.GetFileName(surfacePath), "MEmuHeadless.exe", StringComparison.OrdinalIgnoreCase)
            || !IsWindow(outer, surfacePid) || !IsWindow(inner, surfacePid)) throw new InvalidOperationException("渲染子窗口所属进程不匹配。");
        foreach (long surface in new[] { outer, inner })
        {
            NativeMethods.Check(NativeMethods.GetClientRect(new IntPtr(surface), out var surfaceRect), "读取渲染子窗口失败");
            if (surfaceRect.Right <= surfaceRect.Left || surfaceRect.Bottom <= surfaceRect.Top) throw new InvalidOperationException("渲染子窗口尺寸不可用。");
        }
        return (renderer, new[] { (outer, surfacePid), (inner, surfacePid) }, width, height);
    }

    public void ResizeRenderSurfaces(long hwnd)
    {
        var tree = ResizeTree(hwnd);
        long expectedParent = tree.Renderer;
        foreach (var surface in tree.Surfaces)
        {
            if (!IsWindow(surface.Hwnd, surface.Pid) || NativeMethods.GetParent(new IntPtr(surface.Hwnd)).ToInt64() != expectedParent)
                throw new InvalidOperationException("模拟器渲染子窗口已变化；已停止调整。");
            NativeMethods.Check(NativeMethods.GetClientRect(new IntPtr(surface.Hwnd), out var client), "读取渲染子窗口失败");
            if (client.Right - client.Left != tree.Width || client.Bottom - client.Top != tree.Height)
                NativeMethods.Check(NativeMethods.SetWindowPos(new IntPtr(surface.Hwnd), IntPtr.Zero, 0, 0, tree.Width, tree.Height,
                    NativeMethods.SwpNoZOrder | NativeMethods.SwpNoActivate), "调整渲染子窗口失败");
            expectedParent = surface.Hwnd;
        }
    }

    public void Restore(long hwnd, NativeWindowSnapshot snapshot)
    {
        snapshot.Validate();
        if (hwnd != snapshot.Hwnd || !IsWindow(hwnd, snapshot.Pid)) throw new InvalidOperationException("原模拟器窗口已关闭；禁止还原其他窗口。");
        if (snapshot.Parent != 0 && !NativeMethods.IsWindow(new IntPtr(snapshot.Parent))) throw new InvalidOperationException("模拟器原父窗口已关闭。");
        SetParent(hwnd, snapshot.Parent);
        SetStyle(hwnd, snapshot.Style);
        SetExStyle(hwnd, snapshot.ExStyle);
        int x = snapshot.Rect[0], y = snapshot.Rect[1];
        if (snapshot.Parent != 0 && (snapshot.Style & NativeMethods.WsChild) != 0)
        {
            var point = new NativeMethods.Point(x, y);
            NativeMethods.Check(NativeMethods.ScreenToClient(new IntPtr(snapshot.Parent), ref point), "还原原父窗口坐标失败");
            x = point.X; y = point.Y;
        }
        MoveWindow(hwnd, x, y, snapshot.Rect[2] - snapshot.Rect[0], snapshot.Rect[3] - snapshot.Rect[1]);
        var saved = snapshot.Placement;
        var placement = new NativeMethods.WindowPlacement { Length = (uint)Marshal.SizeOf<NativeMethods.WindowPlacement>(), Flags = saved.Flags, ShowCmd = saved.ShowCmd,
            MinPosition = new(saved.MinPosition[0], saved.MinPosition[1]), MaxPosition = new(saved.MaxPosition[0], saved.MaxPosition[1]),
            NormalPosition = new() { Left = saved.NormalPosition[0], Top = saved.NormalPosition[1], Right = saved.NormalPosition[2], Bottom = saved.NormalPosition[3] } };
        NativeMethods.Check(NativeMethods.SetWindowPlacement(new IntPtr(hwnd), ref placement), "还原模拟器窗口布局失败");
        Thread.Sleep(100);
        try { ResizeRenderSurfaces(hwnd); }
        catch (InvalidOperationException) { /* The restored top level may survive a closed VM renderer. */ }
    }
}
