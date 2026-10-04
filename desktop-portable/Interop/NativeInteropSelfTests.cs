using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using ClashAssistant.Desktop.Services;

namespace ClashAssistant.Desktop.Interop;

/// <summary>Offline contract checks: fake HWNDs only, never touches a game window.</summary>
public static class NativeInteropSelfTests
{
    public static Dictionary<string, object?> Run(string taskDataRoot)
    {
        string root = Path.Combine(Path.GetFullPath(taskDataRoot), "work", "wpf-interop-tests", DateTime.UtcNow.ToString("yyyyMMdd-HHmmss") + "-" + Guid.NewGuid().ToString("N")[..8]);
        DesktopSettings.ValidateOwnedPath(root, nameof(taskDataRoot));
        Directory.CreateDirectory(root);
        string exe = Path.Combine(root, "MEmu.exe");
        List<string> passed = new();

        void Check(bool condition, string name)
        {
            if (!condition) throw new InvalidOperationException("离线原生自检失败：" + name);
            passed.Add(name);
        }

        var fake = new FakeApi(exe);
        using (var owner = new NativeWindowOwner(exe, Path.Combine(root, "restore"), fake))
        {
            owner.Attach(987, 320, 483);
            Check(owner.IsEmbedded && fake.Parent == 987, "attach_uses_owned_hwnd");
            Check(fake.LastMove is not null && fake.LastMove.SequenceEqual(new[] { -1, -40, 370, 524 }), "aspect_ratio_and_renderer_crop");
            using JsonDocument journal = JsonDocument.Parse(File.ReadAllText(owner.JournalPath));
            Check(journal.RootElement.GetProperty("snapshot").GetProperty("ex_style").GetUInt32() == 1024, "python_journal_field_compatibility");
            Check(journal.RootElement.GetProperty("snapshot").GetProperty("placement").GetProperty("ptMinPosition").GetArrayLength() == 2, "original_placement_persisted");
            using var competing = new NativeWindowOwner(exe, Path.Combine(root, "restore"), new FakeApi(exe));
            bool denied = false;
            try { competing.Attach(988, 320, 483); } catch (InvalidOperationException) { denied = true; }
            Check(denied, "first_byte_lock_excludes_other_owner");
            fake.FailRestore = true;
            denied = false;
            try { owner.Detach(); } catch (InvalidOperationException) { denied = true; }
            Check(denied && owner.Snapshot is not null && (bool)owner.Diagnostics()["owner_lock_held"]!, "failed_restore_retains_snapshot_and_lock");
            fake.FailRestore = false;
            fake.Created = 1001;
            denied = false;
            try { owner.Detach(); } catch (InvalidOperationException) { denied = true; }
            Check(denied, "recycled_process_identity_refuses_restore");
            fake.Created = 1000;
            owner.Detach();
            Check(!owner.IsEmbedded && owner.Snapshot is null && fake.Restores == 1, "successful_restore_releases_owner");
            using JsonDocument restored = JsonDocument.Parse(File.ReadAllText(owner.JournalPath));
            Check(restored.RootElement.GetProperty("restored").GetBoolean(), "successful_restore_marks_journal");
        }

        var recoveryApi = new FakeApi(exe);
        string recoveryRoot = Path.Combine(root, "abandoned");
        string journalPath = Path.Combine(recoveryRoot, "work", "native-window-recovery.json");
        Directory.CreateDirectory(Path.GetDirectoryName(journalPath)!);
        File.WriteAllText(journalPath, JsonSerializer.Serialize(new NativeRecoveryJournal {
            OwnerPid = 991, OwnerCreatedAt = 1500, WindowCreatedAt = 1000, Executable = exe, Snapshot = recoveryApi.Snapshot(123)
        }));
        using (var owner = new NativeWindowOwner(exe, recoveryRoot, recoveryApi))
        {
            owner.Attach(987, 320, 483);
            Check(recoveryApi.Restores == 1 && owner.IsEmbedded, "abandoned_python_journal_recovers_before_attach");
            owner.Detach();
        }

        var activeOwnerApi = new FakeApi(exe) { PreviousOwnerAlive = true };
        string activeRoot = Path.Combine(root, "active-owner");
        string activeJournal = Path.Combine(activeRoot, "work", "native-window-recovery.json");
        Directory.CreateDirectory(Path.GetDirectoryName(activeJournal)!);
        File.WriteAllText(activeJournal, JsonSerializer.Serialize(new NativeRecoveryJournal {
            OwnerPid = 991, OwnerCreatedAt = 1500, WindowCreatedAt = 1000, Executable = exe, Snapshot = activeOwnerApi.Snapshot(123)
        }));
        using (var owner = new NativeWindowOwner(exe, activeRoot, activeOwnerApi))
        {
            bool denied = false;
            try { owner.Attach(987, 320, 483); } catch (InvalidOperationException) { denied = true; }
            Check(denied && activeOwnerApi.Restores == 0 && activeOwnerApi.StyleChanges == 0, "live_python_owner_is_never_stolen");
        }

        string title = "ClashAssistant.OfflineTest." + Guid.NewGuid().ToString("N");
        using (var primary = new SingleInstance(title))
        using (var duplicate = new SingleInstance(title))
        {
            Check(primary.Acquire() && !duplicate.Acquire() && primary.ConsumeShowRequest() && !primary.ConsumeShowRequest(), "single_instance_show_event_only");
        }

        var result = new Dictionary<string, object?> { ["status"] = "ok", ["passed"] = passed, ["count"] = passed.Count,
            ["fake_windows_only"] = true, ["game_input_sent"] = false, ["evidence_root"] = root };
        File.WriteAllText(Path.Combine(root, "result.json"), JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = true }));
        return result;
    }

    private sealed class FakeApi : INativeWindowApi
    {
        private readonly string _exe;
        public double Created = 1000;
        public bool FailRestore, PreviousOwnerAlive;
        public long Parent;
        public int Restores, StyleChanges;
        public int[]? LastMove;
        public FakeApi(string exe) { _exe = exe; }
        public long? FindWindow(string executable) => 123;
        public bool IsWindow(long hwnd, int pid) => hwnd == 123 && pid == 17;
        public string? WindowExecutable(long hwnd) => _exe;
        public double? ProcessCreatedAt(int pid) => pid == 17 ? Created : pid == Environment.ProcessId ? 2000 : pid == 991 && PreviousOwnerAlive ? 1500 : null;
        public NativeWindowSnapshot Snapshot(long hwnd) => new() {
            Hwnd = 123, Pid = 17, Parent = 0, Style = 2517303296, ExStyle = 1024,
            Rect = new[] { 300, 100, 874, 933 }, ContentRect = new[] { 1, 40, 524, 792 },
            Placement = new() { Flags = 0, ShowCmd = 1, MinPosition = new[] { -1, -1 }, MaxPosition = new[] { -1, -1 }, NormalPosition = new[] { 300, 100, 874, 933 } }
        };
        public void SetStyle(long hwnd, uint style) { StyleChanges++; }
        public void SetExStyle(long hwnd, uint style) { }
        public void SetParent(long hwnd, long parent) { Parent = parent; }
        public void MoveWindow(long hwnd, int x, int y, int width, int height) { LastMove = new[] { x, y, width, height }; }
        public void ResizeRenderSurfaces(long hwnd) { }
        public void Restore(long hwnd, NativeWindowSnapshot snapshot)
        {
            if (FailRestore) throw new InvalidOperationException("fake restore failure");
            Parent = snapshot.Parent; Restores++;
        }
    }
}
