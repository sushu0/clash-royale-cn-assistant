using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading;

namespace ClashAssistant.Desktop.Interop;

public sealed class NativeRecoveryJournal
{
    [JsonPropertyName("schema")] public int Schema { get; set; } = 1;
    [JsonPropertyName("restored")] public bool Restored { get; set; }
    [JsonPropertyName("owner_pid")] public int OwnerPid { get; set; }
    [JsonPropertyName("owner_created_at")] public double OwnerCreatedAt { get; set; }
    [JsonPropertyName("window_created_at")] public double WindowCreatedAt { get; set; }
    [JsonPropertyName("executable")] public string? Executable { get; set; }
    [JsonPropertyName("snapshot")] public NativeWindowSnapshot? Snapshot { get; set; }
}

/// <summary>Exact Python-compatible owner lock and journal, independently testable with a fake API.</summary>
public sealed class NativeWindowOwner : IDisposable
{
    private readonly INativeWindowApi _api;
    private readonly string _executable, _journalPath, _lockPath;
    private FileStream? _ownerLock;
    private NativeWindowSnapshot? _snapshot;
    private double? _windowCreatedAt;
    private long _parent;
    private int[]? _lastLayout;
    public bool IsEmbedded { get; private set; }
    public NativeWindowSnapshot? Snapshot => _snapshot;
    public string JournalPath => _journalPath;
    public string LockPath => _lockPath;
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true, DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull };

    public NativeWindowOwner(string emulatorExe, string dataRoot, INativeWindowApi? api = null)
    {
        _executable = Path.GetFullPath(emulatorExe);
        string root = DesktopSettings.ValidateOwnedPath(dataRoot, nameof(dataRoot));
        _journalPath = Path.Combine(root, "work", "native-window-recovery.json");
        _lockPath = Path.ChangeExtension(_journalPath, ".owner.lock");
        _api = api ?? new NativeWindowApi();
    }

    private void AcquireOwnership()
    {
        if (_ownerLock is not null) return;
        Directory.CreateDirectory(Path.GetDirectoryName(_lockPath)!);
        FileStream stream = new(_lockPath, FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.ReadWrite | FileShare.Delete);
        try
        {
            if (stream.Length == 0) { stream.WriteByte(0); stream.Flush(true); }
            stream.Lock(0, 1); // Same first-byte Win32 lock as msvcrt.LK_NBLCK.
            _ownerLock = stream;
        }
        catch (IOException error) { stream.Dispose(); throw new InvalidOperationException("模拟器已由另一控制台托管；请先关闭原控制台。", error); }
        catch { stream.Dispose(); throw; }
    }

    private void ReleaseOwnership()
    {
        if (_ownerLock is null) return;
        _ownerLock.Unlock(0, 1);
        _ownerLock.Dispose();
        _ownerLock = null;
    }

    private static void WriteAtomic(string path, object value, bool backup = false)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        if (backup && File.Exists(path))
        {
            try
            {
                using JsonDocument valid = JsonDocument.Parse(File.ReadAllText(path, Encoding.UTF8));
                WriteAtomic(path + ".bak", valid.RootElement.Clone());
            }
            catch (JsonException) { /* Preserve an existing backup if primary JSON is damaged. */ }
        }
        string temporary = Path.Combine(Path.GetDirectoryName(path)!, ".tmp-" + Guid.NewGuid().ToString("N"));
        try
        {
            byte[] bytes = Encoding.UTF8.GetBytes(JsonSerializer.Serialize(value, JsonOptions) + "\n");
            using (FileStream stream = new(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            { stream.Write(bytes); stream.Flush(true); }
            for (int attempt = 0; ; attempt++)
            {
                try { File.Move(temporary, path, true); break; }
                catch (IOException) when (attempt < 14) { Thread.Sleep(30); }
            }
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }

    private NativeRecoveryJournal? ReadJournal()
    {
        bool any = false;
        foreach (string path in new[] { _journalPath, _journalPath + ".bak" })
        {
            if (!File.Exists(path)) continue;
            any = true;
            try
            {
                using JsonDocument document = JsonDocument.Parse(File.ReadAllText(path, Encoding.UTF8));
                JsonElement root = document.RootElement;
                // Do not default a missing restored flag to false and then
                // accidentally accept a partial or unrelated recovery record.
                if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty("schema", out var schema)
                    || !schema.TryGetInt32(out int version) || version != 1 || !root.TryGetProperty("restored", out var restored)
                    || restored.ValueKind is not (JsonValueKind.True or JsonValueKind.False)) continue;
                return JsonSerializer.Deserialize<NativeRecoveryJournal>(root.GetRawText());
            }
            catch (JsonException) { }
            catch (IOException) { }
        }
        if (any) throw new InvalidOperationException("窗口恢复记录无效；已保留原文件。");
        return null;
    }

    private static bool ValidTime(double value) => double.IsFinite(value) && value > 0;
    private void RecoverAbandonedHost()
    {
        NativeRecoveryJournal? row = ReadJournal();
        if (row is null || row.Restored) return;
        if (row.OwnerPid <= 0 || !ValidTime(row.OwnerCreatedAt) || !ValidTime(row.WindowCreatedAt) || row.Snapshot is null
            || !NativeWindowApi.SamePath(row.Executable, _executable)) throw new InvalidOperationException("窗口恢复身份信息不完整；已保留恢复记录。");
        double? ownerCreated = _api.ProcessCreatedAt(row.OwnerPid);
        if (ownerCreated is not null && Math.Abs(ownerCreated.Value - row.OwnerCreatedAt) < 0.01)
            throw new InvalidOperationException("模拟器已由另一控制台托管；请先关闭原控制台。");
        row.Snapshot.Validate();
        if (_api.IsWindow(row.Snapshot.Hwnd, row.Snapshot.Pid))
        {
            double? created = _api.ProcessCreatedAt(row.Snapshot.Pid);
            if (created is null || Math.Abs(created.Value - row.WindowCreatedAt) >= 0.01
                || !NativeWindowApi.SamePath(_api.WindowExecutable(row.Snapshot.Hwnd), _executable))
                throw new InvalidOperationException("无法核实旧模拟器窗口身份；已拒绝还原并保留恢复记录。");
            // Retain the old snapshot and owner lock if restore fails. This
            // keeps a partially restored native child available for retry.
            _snapshot = row.Snapshot;
            _windowCreatedAt = row.WindowCreatedAt;
            _api.Restore(row.Snapshot.Hwnd, row.Snapshot);
        }
        MarkRestored();
        _snapshot = null;
        _windowCreatedAt = null;
    }

    private void MarkRestored() => WriteAtomic(_journalPath, new { schema = 1, restored = true }, backup: true);
    private bool IdentityMatches(NativeWindowSnapshot saved)
    {
        double? created = _api.ProcessCreatedAt(saved.Pid);
        return _windowCreatedAt is not null && created is not null && Math.Abs(created.Value - _windowCreatedAt.Value) < 0.01
            && NativeWindowApi.SamePath(_api.WindowExecutable(saved.Hwnd), _executable);
    }

    public void Attach(long parent, int width, int height)
    {
        if (parent <= 0 || width <= 0 || height <= 0) throw new ArgumentException("原生宿主尚未创建或尺寸无效。");
        AcquireOwnership();
        try { AttachOwned(parent, width, height); }
        catch { if (_snapshot is null) ReleaseOwnership(); throw; }
    }

    private void AttachOwned(long parent, int width, int height)
    {
        if (_snapshot is null) RecoverAbandonedHost();
        if (_snapshot is not null)
        {
            if (_api.IsWindow(_snapshot.Hwnd, _snapshot.Pid))
            {
                if (IsEmbedded && _parent == parent) { Resize(width, height); return; }
                Detach(keepOwnership: true);
            }
            else { MarkRestored(); _snapshot = null; IsEmbedded = false; _lastLayout = null; }
        }
        long hwnd = _api.FindWindow(_executable) ?? throw new InvalidOperationException("模拟器窗口尚未打开，或存在多个相同实例。");
        NativeWindowSnapshot saved = _api.Snapshot(hwnd);
        saved.Validate();
        double created = _api.ProcessCreatedAt(saved.Pid) ?? throw new InvalidOperationException("无法确认模拟器进程身份；已停止嵌入。");
        if (!ValidTime(created) || !NativeWindowApi.SamePath(_api.WindowExecutable(hwnd), _executable))
            throw new InvalidOperationException("模拟器窗口身份不匹配；已停止嵌入。");
        _snapshot = saved;
        _windowCreatedAt = created;
        WriteAtomic(_journalPath, new NativeRecoveryJournal { OwnerPid = Environment.ProcessId,
            OwnerCreatedAt = _api.ProcessCreatedAt(Environment.ProcessId) ?? throw new InvalidOperationException("无法确认宿主身份。"),
            WindowCreatedAt = created, Executable = _executable, Snapshot = saved });
        _parent = parent;
        try
        {
            _api.SetStyle(hwnd, (saved.Style & ~(NativeMethods.WsPopup | NativeMethods.WindowChrome)) | NativeMethods.WsChild);
            _api.SetExStyle(hwnd, saved.ExStyle & ~NativeMethods.WsExAppWindow);
            _api.SetParent(hwnd, parent);
            IsEmbedded = true;
            Resize(width, height);
        }
        catch { IsEmbedded = false; Detach(); throw; }
    }

    public void Resize(int width, int height)
    {
        NativeWindowSnapshot? saved = _snapshot;
        if (!IsEmbedded || saved is null) return;
        if (!_api.IsWindow(saved.Hwnd, saved.Pid))
        {
            MarkRestored(); _snapshot = null; IsEmbedded = false; _parent = 0; _lastLayout = null; ReleaseOwnership();
            throw new InvalidOperationException("模拟器窗口已关闭，等待重新嵌入。");
        }
        if (!IdentityMatches(saved)) throw new InvalidOperationException("模拟器窗口身份已变化；已停止尺寸调整。");
        int outerWidth = saved.Rect[2] - saved.Rect[0], outerHeight = saved.Rect[3] - saved.Rect[1];
        int[] content = saved.ContentRect ?? new[] { 0, 0, outerWidth, outerHeight };
        double scale = Math.Min(Math.Max(1, width) / (double)content[2], Math.Max(1, height) / (double)content[3]);
        int gameWidth = Math.Max(1, (int)Math.Round(content[2] * scale)), gameHeight = Math.Max(1, (int)Math.Round(content[3] * scale));
        int[] layout = { -content[0], -content[1], gameWidth + outerWidth - content[2], gameHeight + outerHeight - content[3] };
        if (_lastLayout is null || !System.Linq.Enumerable.SequenceEqual(layout, _lastLayout))
        {
            _api.MoveWindow(saved.Hwnd, layout[0], layout[1], layout[2], layout[3]);
            _api.ResizeRenderSurfaces(saved.Hwnd);
            _lastLayout = layout;
        }
    }

    public void RefreshRenderSurfaces()
    {
        if (IsEmbedded && _snapshot is not null)
        {
            if (!_api.IsWindow(_snapshot.Hwnd, _snapshot.Pid) || !IdentityMatches(_snapshot))
                throw new InvalidOperationException("模拟器窗口身份已变化；已停止刷新。");
            _api.ResizeRenderSurfaces(_snapshot.Hwnd);
        }
    }

    public void Detach(bool keepOwnership = false)
    {
        NativeWindowSnapshot? saved = _snapshot;
        if (saved is null) { if (!keepOwnership) ReleaseOwnership(); return; }
        if (_api.IsWindow(saved.Hwnd, saved.Pid))
        {
            if (!IdentityMatches(saved)) throw new InvalidOperationException("模拟器窗口身份已变化；已拒绝还原并保留恢复记录。");
            _api.Restore(saved.Hwnd, saved);
        }
        MarkRestored();
        _snapshot = null; _windowCreatedAt = null; IsEmbedded = false; _parent = 0; _lastLayout = null;
        if (!keepOwnership) ReleaseOwnership();
    }

    public Dictionary<string, object?> Diagnostics() => new()
    {
        ["source"] = "native_window", ["embedded"] = IsEmbedded, ["window_handle"] = _snapshot?.Hwnd,
        ["window_pid"] = _snapshot?.Pid, ["host_handle"] = _parent == 0 ? null : _parent, ["native_layout"] = _lastLayout,
        ["original_rect"] = _snapshot?.Rect, ["original_content_rect"] = _snapshot?.ContentRect,
        ["owner_lock_held"] = _ownerLock is not null, ["recovery_path"] = _journalPath,
        ["frame_capture"] = false, ["captures_per_second"] = 0, ["game_input_sent"] = false
    };

    public void Dispose() => Detach();
}
