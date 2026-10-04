using System.Diagnostics;
using System.IO;
using System.Text.Json;
using ClashAssistant.Desktop.Models;
using ClashAssistant.Desktop.Services;
using ClashAssistant.Desktop.ViewModels;

const string harness = @"D:\codex\CodexWork\clash\work\task-stop-repair-20261004\client-harness";
string fixture = Path.Combine(harness, "baseline-cases", Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(fixture);
File.WriteAllText(Path.Combine(fixture, "mode.txt"), "concurrency");
string fake = Path.Combine(harness, "FakeBackend", "bin", "Debug", "net10.0", "FakeBackend.exe");
var evidence = new List<object>();
int reproduced = 0;
await using (var backend = new BackendClient(fake, fixture))
{
    Task<CommandResult> start = backend.StartBotAsync();
    var requestWait = Stopwatch.StartNew();
    while (!File.Exists(Path.Combine(fixture, "requests.jsonl")))
    {
        if (requestWait.ElapsedMilliseconds > 5000) throw new Exception("baseline backend never received start");
        await Task.Delay(15);
    }
    var elapsed = Stopwatch.StartNew();
    CommandResult stop = await backend.StopBotAsync();
    bool defect = elapsed.ElapsedMilliseconds >= 1000 && start.IsCompleted;
    evidence.Add(new { name = "stop_serialized_behind_pending_start", defect_reproduced = defect, stop_elapsed_ms = elapsed.ElapsedMilliseconds, start_completed_when_stop_returns = start.IsCompleted, expected_after_fix = "stop completes within 700 ms while start remains pending" });
    if (defect) reproduced++;
    await start;
}
ConsoleSnapshot stopped = new()
{
    State = "stopped", Runtime = new RuntimeSnapshot { DataRoot = fixture },
    Live = JsonSerializer.SerializeToElement(new { state = "fixture-only" })
};
var vm = new DesktopViewModel(fixture, false);
vm.Apply(stopped);
vm.SetBusy("start");
bool unavailableDuringStart = !vm.CanStop;
evidence.Add(new { name = "stop_control_disabled_during_pending_start", defect_reproduced = unavailableDuringStart, expected_after_fix = "CanStop true during pending start" });
if (unavailableDuringStart) reproduced++;
vm.SetBusy("stop");
vm.SetBusy("");
bool unknownRestart = vm.CanStart;
evidence.Add(new { name = "unknown_stop_completion_restores_start_from_old_snapshot", defect_reproduced = unknownRestart, expected_after_fix = "CanStart false until a fresh confirmed snapshot" });
if (unknownRestart) reproduced++;
vm.SetBusy("stop");
vm.Apply(stopped);
vm.SetBusy("");
bool busySnapshotRestart = vm.CanStart;
evidence.Add(new { name = "snapshot_received_while_busy_unlocks_start_after_busy_clears", defect_reproduced = busySnapshotRestart, expected_after_fix = "CanStart false until a read made after command completion" });
if (busySnapshotRestart) reproduced++;
string report = JsonSerializer.Serialize(new { generated_at = DateTimeOffset.UtcNow, fixture, reproduced, expected_defects = 4, evidence }, new JsonSerializerOptions { WriteIndented = true });
File.WriteAllText(Path.Combine(harness, "baseline-reproduction.json"), report);
Console.WriteLine(report);
return reproduced == 4 ? 0 : 1;
