using System.Diagnostics;
using System.IO;
using System.Text.Json;
using ClashAssistant.Desktop;
using ClashAssistant.Desktop.Models;
using ClashAssistant.Desktop.Services;
using ClashAssistant.Desktop.ViewModels;

internal static class Program
{
    private const string HarnessRoot = @"D:\codex\CodexWork\clash\work\task-stop-repair-20261004\client-harness";
    private static readonly string FakeExe = Path.Combine(HarnessRoot, "FakeBackend", "bin", "Debug", "net10.0", "FakeBackend.exe");
    private static readonly string CasesRoot = Path.Combine(HarnessRoot, "cases", DateTimeOffset.UtcNow.ToString("yyyyMMddHHmmss") + "-" + Guid.NewGuid().ToString("N"));
    private static readonly List<object> Results = new();
    private static readonly Dictionary<string, long> Measurements = new();
    private static int failed;

    [STAThread]
    private static int Main()
    {
        Directory.CreateDirectory(CasesRoot);
        RunAsync().GetAwaiter().GetResult();
        string report = JsonSerializer.Serialize(new { generated_at = DateTimeOffset.UtcNow, cases_root = CasesRoot, passed = Results.Count - failed, failed, measurements = Measurements, tests = Results }, new JsonSerializerOptions { WriteIndented = true });
        File.WriteAllText(Path.Combine(HarnessRoot, "results.json"), report);
        Console.WriteLine($"RESULT: {Results.Count - failed} passed, {failed} failed");
        return failed == 0 ? 0 : 1;
    }

    private static async Task RunAsync()
    {
        await Case("stop_reaches_bridge_before_start_readiness_reply", async () =>
        {
            string root = Fixture("concurrency");
            await using var client = new BackendClient(FakeExe, root);
            Task<CommandResult> start = client.StartBotAsync();
            await WaitForRequests(root, "start", 1);
            var timer = Stopwatch.StartNew();
            CommandResult stop = await client.StopBotAsync();
            Measurements["stop_latency_while_start_pending_ms"] = timer.ElapsedMilliseconds;
            Assert(timer.ElapsedMilliseconds < 700, "stop blocked behind pending start: " + timer.ElapsedMilliseconds + " ms");
            Assert(!start.IsCompleted, "start readiness must still be pending when stop completes");
            Assert(stop.State == "stopped" && stop.Message.StartsWith("stop-reply-"), "stop must receive its own response");
            CommandResult startResult = await start;
            Assert(startResult.State == "stopped" && startResult.Message.StartsWith("start-reply-"), "late start receives only its own cancelled-start response");
        });

        await Case("concurrent_typed_responses_and_foreign_ids_are_not_crossed", async () =>
        {
            string root = Fixture("concurrency");
            await using var client = new BackendClient(FakeExe, root);
            Task<ConsoleSnapshot>[] snapshots = Enumerable.Range(0, 8).Select(_ => client.GetSnapshotAsync()).ToArray();
            Task<IReadOnlyList<ErrorReportRecord>> reports = client.GetReportsAsync();
            ConsoleSnapshot[] values = await Task.WhenAll(snapshots);
            IReadOnlyList<ErrorReportRecord> reportValues = await reports;
            string[] expected = Requests(root).Where(r => r.Command == "snapshot").Select(r => "snapshot-reply-" + r.Index).Order().ToArray();
            Assert(values.Select(v => v.SelectedStrategy).Order().SequenceEqual(expected), "every concurrent snapshot must match a snapshot request exactly once");
            Assert(values.All(v => v.State == "running" && v.Runtime.DataRoot == root), "foreign IDs may never update real pending requests");
            Assert(reportValues.Count == 1 && reportValues[0].EventId.StartsWith("reports-reply-"), "reports data cannot be confused with snapshot responses");
        });

        await Case("cancelled_start_is_unknown_not_retried_and_stop_still_preempts", async () =>
        {
            string root = Fixture("cancelled-start");
            await using var client = new BackendClient(FakeExe, root);
            using var cancellation = new CancellationTokenSource();
            Task<CommandResult> start = client.StartBotAsync(cancellation.Token);
            await WaitForRequests(root, "start", 1);
            cancellation.Cancel();
            try { await start; throw new Exception("start cancellation expected"); }
            catch (BackendRequestException error) { Assert(error.Command == "start" && error.ResultUnknown && !error.IsTimeout, "sent mutation cancellation requires unknown result"); }
            CommandResult stop = await client.StopBotAsync();
            Assert(stop.State == "stopped", "cancelled pending start must not block stop");
            await Task.Delay(1250);
            ConsoleSnapshot snapshot = await client.GetSnapshotAsync();
            Assert(snapshot.State == "stopped" && snapshot.SelectedStrategy.StartsWith("snapshot-reply-"), "late cancelled response cannot become fresh snapshot");
            Assert(Requests(root).Count(r => r.Command == "start") == 1, "mutation may not be automatically retried");
        });

        await Case("transport_loss_during_stop_is_unknown_and_never_retried", async () =>
        {
            string root = Fixture("exit-stop");
            await using var client = new BackendClient(FakeExe, root);
            try { await client.StopBotAsync(); throw new Exception("stop disconnect expected"); }
            catch (BackendRequestException error) { Assert(error.Command == "stop" && error.ResultUnknown && error.IsTransportFailure, "disconnect after stop write must be unknown"); }
            Assert(Requests(root).Count(r => r.Command == "stop") == 1, "stop may not be automatically retried");
        });

        await Case("backend_stopping_snapshot_is_accepted", async () =>
        {
            string root = Fixture("state-stopping");
            await using var client = new BackendClient(FakeExe, root);
            Assert((await client.GetSnapshotAsync()).State == "stopping", "new stopping state is part of valid protocol");
        });

        await Case("read_only_bridge_rejects_start_and_stop_before_transport", async () =>
        {
            string root = Fixture("read-only");
            await using var client = new BackendClient(FakeExe, root, true);
            await client.GetSnapshotAsync();
            foreach (string command in new[] { "start", "stop" })
            {
                try { await (command == "start" ? client.StartBotAsync() : client.StopBotAsync()); throw new Exception("readonly mutation expected to fail"); }
                catch (BackendRequestException error) { Assert(!error.ResultUnknown, "read-only rejection occurs before sending"); }
            }
            Assert(Requests(root).All(r => r.Command is not ("start" or "stop")), "read-only must send no mutation request");
        });

        await Case("vm_startup_has_no_permission_to_start_without_snapshot", () =>
        {
            var vm = new DesktopViewModel(Fixture("vm-initial"), false);
            Assert(!vm.StateConfirmed && !vm.CanStart && !vm.CanStop, "connecting view has no confirmed task identity");
        });
        await Case("vm_start_wait_keeps_stop_available", () =>
        {
            var vm = StoppedVm("vm-start-wait");
            vm.SetBusy("start");
            Assert(!vm.StateConfirmed && !vm.CanStart && vm.CanStop && vm.IsBusy, "pending start must be interruptible");
        });
        await Case("vm_stop_wait_blocks_double_stop_and_restart", () =>
        {
            var vm = StoppedVm("vm-stop-wait");
            vm.SetBusy("stop");
            Assert(!vm.StateConfirmed && !vm.CanStart && !vm.CanStop, "stop in progress disables duplicate mutations");
        });
        await Case("vm_snapshot_received_while_busy_does_not_confirm_stopped", () =>
        {
            string root = Fixture("vm-busy-snapshot");
            var vm = new DesktopViewModel(root, false);
            vm.Apply(Snapshot(root, "running"));
            vm.SetBusy("stop");
            vm.Apply(Snapshot(root, "stopped"));
            vm.SetBusy("");
            Assert(!vm.StateConfirmed && !vm.CanStart && vm.CanStop, "old or busy snapshot cannot unlock start on command completion");
        });
        await Case("vm_failed_operation_remains_unknown_until_new_snapshot", () =>
        {
            string root = Fixture("vm-unknown");
            var vm = new DesktopViewModel(root, false);
            vm.Apply(Snapshot(root, "stopped"));
            vm.SetBusy("stop");
            vm.SetBusy("");
            Assert(!vm.CanStart && vm.CanStop && !vm.StateConfirmed, "unknown stop completion cannot restore start from old stopped display");
            vm.Apply(Snapshot(root, "stopped"));
            Assert(vm.CanStart && vm.StateConfirmed && !vm.CanStop, "a new confirmed stopped snapshot permits manual start");
        });
        await Case("vm_refresh_failure_revokes_previous_start_permission", () =>
        {
            var vm = StoppedVm("vm-refresh-failed");
            Assert(vm.CanStart, "baseline stopped snapshot allows manual start");
            vm.MarkStateUnconfirmed();
            Assert(!vm.CanStart && vm.CanStop && !vm.StateConfirmed, "failed current read revokes permission derived from previous read");
        });
        await Case("vm_stopping_state_blocks_restart_and_supports_stop", () =>
        {
            string root = Fixture("vm-stopping");
            var vm = new DesktopViewModel(root, false);
            vm.Apply(Snapshot(root, "stopping"));
            Assert(!vm.CanStart && vm.CanStop && vm.Phase == "正在停止任务", "stopping state cannot become stopped");
        });
        await Case("vm_backend_busy_stop_blocks_restart_even_if_snapshot_state_stopped", () =>
        {
            string root = Fixture("vm-backend-busy");
            var vm = new DesktopViewModel(root, false);
            ConsoleSnapshot snapshot = Snapshot(root, "stopped");
            snapshot.Busy = "stop";
            vm.Apply(snapshot);
            Assert(!vm.CanStart && vm.IsBusy && vm.StateLabel.Contains("正在停止") && vm.Phase == "正在停止任务", "server command must disable restart and display pending stop consistently");
        });
        await Case("vm_backend_busy_start_keeps_stop_available_even_if_snapshot_state_stopped", () =>
        {
            string root = Fixture("vm-backend-start");
            var vm = new DesktopViewModel(root, false);
            ConsoleSnapshot snapshot = Snapshot(root, "stopped");
            snapshot.Busy = "start";
            vm.Apply(snapshot);
            Assert(!vm.CanStart && vm.CanStop && vm.IsBusy && vm.StateLabel.Contains("正在启动") && vm.Phase == "正在启动任务", "backend pending readiness can be interrupted and displays startup consistently");
        });
        await Case("vm_preview_disallows_stop_even_during_start", () =>
        {
            string root = Fixture("vm-preview");
            var vm = new DesktopViewModel(root, true);
            vm.Apply(Snapshot(root, "running"));
            vm.SetBusy("start");
            Assert(!vm.CanStart && !vm.CanStop, "preview stays immutable for all operation states");
        });

        await Case("actual_window_command_flow_preempts_start_rejects_duplicates_and_old_snapshot", async () =>
        {
            string root = Fixture("delayed-snapshot");
            await using var backend = new BackendClient(FakeExe, root);
            var vm = new DesktopViewModel(root, false);
            var window = new MainWindow(backend, vm, root);
            window.SeedForTest(Snapshot(root, "stopped"));
            Task refresh = window.RefreshForTest();
            await WaitForRequests(root, "snapshot", 1);
            Task start = window.CommandForTest("start");
            await WaitForRequests(root, "start", 1);
            Assert(vm.CanStop && !vm.CanStart, "UI start operation must expose stop");
            Task stop = window.CommandForTest("stop");
            await WaitForRequests(root, "stop", 1);
            await window.CommandForTest("stop");
            await window.CommandForTest("start");
            Assert(!vm.CanStart && !vm.CanStop, "UI stop operation rejects both duplicate stop and restart");
            await stop.WaitAsync(TimeSpan.FromMilliseconds(700));
            Assert(!start.IsCompleted && vm.IsBusy && !vm.CanStart && !vm.CanStop, "stop reply does not release UI while earlier start remains pending");
            await start;
            Assert(!vm.IsBusy && !vm.StateConfirmed && !vm.CanStart, "both command replies still need a fresh current-state read");
            await refresh;
            Assert(!vm.StateConfirmed && !vm.CanStart && vm.State == "stopped", "read sent before commands must be discarded even when it returns after commands finish");
            Assert(Requests(root).Count(r => r.Command == "start") == 1 && Requests(root).Count(r => r.Command == "stop") == 1, "click and tray entry must not send duplicate mutations");
            await window.RefreshForTest();
            Assert(vm.StateConfirmed && vm.CanStart && !vm.CanStop && vm.State == "stopped", "fresh read after commands confirms stopped state");
            Assert(vm.Notice.StartsWith("stop-reply-"), "late start notice must not overwrite user stop notice");
        });

        await Case("actual_window_continues_refresh_after_backend_busy_until_fresh_clear", async () =>
        {
            string root = Fixture("busy-clears");
            await using var backend = new BackendClient(FakeExe, root);
            var vm = new DesktopViewModel(root, false);
            var window = new MainWindow(backend, vm, root);
            window.SeedForTest(Snapshot(root, "stopped"));
            await window.RefreshForTest();
            Assert(vm.IsBusy && !vm.CanStart && !vm.CanStop && vm.Phase == "正在停止任务", "backend busy must be visible and block mutations");
            await window.RefreshForTest();
            Assert(Requests(root).Count(r => r.Command == "snapshot") == 2, "backend busy snapshot must not prevent subsequent refresh request");
            Assert(!vm.IsBusy && vm.StateConfirmed && vm.CanStart && !vm.CanStop && vm.Phase == "任务已停止", "cleared backend busy and fresh stopped snapshot must restore correct manual controls");
        });

        await Case("vm_busy_and_state_confirmed_changes_notify_bindings", () =>
        {
            string root = Fixture("vm-notifications");
            var vm = new DesktopViewModel(root, false);
            vm.Apply(Snapshot(root, "stopped"));
            var changed = new HashSet<string>();
            vm.PropertyChanged += (_, args) => { if (args.PropertyName is not null) changed.Add(args.PropertyName); };
            vm.SetBusy("start");
            Assert(changed.Contains(nameof(vm.StateConfirmed)) && changed.Contains(nameof(vm.IsBusy)) && changed.Contains(nameof(vm.CanStop)), "local command changes must notify state confirmation and busy controls");
            changed.Clear();
            vm.SetBusy("");
            ConsoleSnapshot snapshot = Snapshot(root, "stopped");
            snapshot.Busy = "stop";
            vm.Apply(snapshot);
            Assert(changed.Contains(nameof(vm.IsBusy)) && changed.Contains(nameof(vm.StateConfirmed)) && changed.Contains(nameof(vm.StateLabel)), "backend busy snapshot must notify the same visual bindings");
        });

        await Case("vm_unconfirmed_old_backend_stop_busy_allows_stop_retry_without_restart", () =>
        {
            string root = Fixture("vm-busy-unconfirmed-retry");
            var vm = new DesktopViewModel(root, false);
            ConsoleSnapshot busy = Snapshot(root, "stopping");
            busy.Busy = "stop";
            vm.Apply(busy);
            Assert(vm.IsBusy && !vm.CanStart && !vm.CanStop, "fresh stop-busy snapshot blocks duplicate mutations");
            vm.MarkStateUnconfirmed();
            Assert(!vm.StateConfirmed && !vm.IsBusy && !vm.CanStart && vm.CanStop, "unconfirmed old backend busy cannot permanently prevent a stop retry");
            Assert(vm.PhaseDescription.Contains("再次发送停止请求"), "unknown status must explain the available stop retry");
            vm.SetBusy("stop");
            Assert(vm.IsBusy && !vm.CanStart && !vm.CanStop, "locally pending stop still blocks duplicate retries");
        });

        await Case("actual_window_failed_refresh_after_stopped_backend_busy_allows_stop_retry", async () =>
        {
            string root = Fixture("busy-then-invalid");
            await using var backend = new BackendClient(FakeExe, root);
            var vm = new DesktopViewModel(root, false);
            var window = new MainWindow(backend, vm, root);
            window.SeedForTest(Snapshot(root, "stopped"));
            await window.RefreshForTest();
            Assert(vm.IsBusy && !vm.CanStart && !vm.CanStop, "fresh stopped+busy stop forbids all mutation controls");
            await window.RefreshForTest();
            Assert(Requests(root).Count(r => r.Command == "snapshot") == 2, "busy state must not prevent the next current-state read");
            Assert(!vm.StateConfirmed && !vm.IsBusy && !vm.CanStart && vm.CanStop, "failed read revokes stale backend busy and permits a stop retry without permitting start");
            Assert(vm.Notice.StartsWith("状态同步暂未完成"), "failed actual refresh must explain uncertainty");
            await window.CommandForTest("stop");
            Assert(Requests(root).Count(r => r.Command == "stop") == 1, "user retry must reach the real client transport");
            Assert(vm.StateConfirmed && vm.State == "stopped" && vm.CanStart && !vm.CanStop, "successful retry plus fresh stopped verification restores manual controls");
        });
    }

    private static DesktopViewModel StoppedVm(string mode)
    {
        string root = Fixture(mode);
        var vm = new DesktopViewModel(root, false);
        vm.Apply(Snapshot(root, "stopped"));
        return vm;
    }
    private static string Fixture(string mode)
    {
        string root = Path.Combine(CasesRoot, mode);
        Directory.CreateDirectory(root);
        File.WriteAllText(Path.Combine(root, "mode.txt"), mode);
        return root;
    }
    private static ConsoleSnapshot Snapshot(string root, string state) => new()
    {
        State = state, Runtime = new RuntimeSnapshot { DataRoot = root },
        Live = JsonSerializer.SerializeToElement(new { state = "fixture-only", session = "fake-session" }),
        UpdatedAt = DateTimeOffset.UtcNow.ToString("O")
    };
    private static List<RequestLog> Requests(string root)
    {
        string path = Path.Combine(root, "requests.jsonl");
        if (!File.Exists(path)) return new();
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
        using var reader = new StreamReader(stream);
        var results = new List<RequestLog>();
        while (reader.ReadLine() is { } line)
        {
            try
            {
                using var parsed = JsonDocument.Parse(line);
                results.Add(new(parsed.RootElement.GetProperty("command").GetString()!, parsed.RootElement.GetProperty("index").GetInt32()));
            }
            catch (JsonException) { }
        }
        return results;
    }
    private static async Task WaitForRequests(string root, string command, int count)
    {
        var timer = Stopwatch.StartNew();
        while (Requests(root).Count(r => r.Command == command) < count)
        {
            if (timer.Elapsed > TimeSpan.FromSeconds(5)) throw new Exception("backend did not receive " + command);
            await Task.Delay(15);
        }
    }
    private static void Assert(bool condition, string message) { if (!condition) throw new Exception(message); }
    private static Task Case(string name, Action action) => Case(name, () => { action(); return Task.CompletedTask; });
    private static async Task Case(string name, Func<Task> action)
    {
        var timer = Stopwatch.StartNew();
        try
        {
            await action();
            Results.Add(new { name, result = "PASS", elapsed_ms = timer.ElapsedMilliseconds });
            Console.WriteLine("PASS " + name);
        }
        catch (Exception error)
        {
            failed++;
            Results.Add(new { name, result = "FAIL", elapsed_ms = timer.ElapsedMilliseconds, error = error.ToString() });
            Console.WriteLine("FAIL " + name + ": " + error.Message);
        }
    }
    private sealed record RequestLog(string Command, int Index);
}
