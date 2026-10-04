using System.Text.Json;

Console.InputEncoding = System.Text.Encoding.UTF8;
Console.OutputEncoding = new System.Text.UTF8Encoding(false);
string root = args.Length >= 2 ? args[1] : throw new Exception("data-root required");
Directory.CreateDirectory(root);
string mode = File.ReadAllText(Path.Combine(root, "mode.txt")).Trim();
var outputLock = new SemaphoreSlim(1, 1);
var logLock = new SemaphoreSlim(1, 1);
int sequence = 0, snapshots = 0;
bool stopped = false;
var started = System.Diagnostics.Stopwatch.StartNew();

async Task Emit(string id, object data)
{
    await outputLock.WaitAsync();
    try
    {
        // A well-formed foreign ID is deliberately interleaved before every
        // real reply, including out-of-order start/stop responses.
        Console.WriteLine(JsonSerializer.Serialize(new { id = Guid.NewGuid().ToString(), ok = true, data = new { state = "foreign-response" } }));
        Console.WriteLine(JsonSerializer.Serialize(new { id, ok = true, data }));
        await Console.Out.FlushAsync();
    }
    finally { outputLock.Release(); }
}

async Task Handle(string id, string command, int index)
{
    if (command == "start")
    {
        await Task.Delay(1200);
        await Emit(id, new { state = stopped ? "stopped" : "running", message = "start-reply-" + index });
    }
    else if (command == "stop")
    {
        stopped = true;
        if (mode == "exit-stop") { Environment.Exit(3); return; }
        await Task.Delay(100);
        if (mode == "hang-stop") return;
        await Emit(id, new { state = "stopped", message = "stop-reply-" + index });
    }
    else if (command == "snapshot")
    {
        bool capturedStop = stopped;
        int snapshotIndex = Interlocked.Increment(ref snapshots);
        if (mode == "delayed-snapshot" && snapshotIndex == 1) await Task.Delay(1800);
        else await Task.Delay(100 - index % 5 * 15);
        await Emit(id, new
        {
            state = mode == "state-stopping" ? "stopping" : mode is "busy-clears" or "busy-then-invalid" || capturedStop ? "stopped" : "running",
            selected_strategy = "snapshot-reply-" + index,
            updated_at = DateTimeOffset.UtcNow.ToString("O"),
            live = new { state = "fixture-only", session = "fake-session" },
            runtime = new { data_root = mode == "busy-then-invalid" && snapshotIndex == 2 ? @"D:\codex\unrelated-fixture" : root, vm_index = 0, memuc = "" },
            busy = mode == "busy-stop" || (mode is "busy-clears" or "busy-then-invalid" && snapshotIndex == 1) ? "stop" : (string?)null
        });
    }
    else if (command == "reports")
    {
        await Task.Delay(30);
        await Emit(id, new { reports = new[] { new { event_id = "reports-reply-" + index, report_json = "fixture-only" } } });
    }
    else if (command == "shutdown")
    {
        await Emit(id, new { state = "stopped", shutdown = true });
    }
}

while (await Console.In.ReadLineAsync() is { } line)
{
    using var request = JsonDocument.Parse(line);
    string id = request.RootElement.GetProperty("id").GetString()!;
    string command = request.RootElement.GetProperty("command").GetString()!;
    int index = Interlocked.Increment(ref sequence);
    await logLock.WaitAsync();
    try
    {
        await File.AppendAllTextAsync(Path.Combine(root, "requests.jsonl"), JsonSerializer.Serialize(new { id, command, index, elapsed_ms = started.ElapsedMilliseconds }) + "\n");
    }
    finally { logLock.Release(); }
    if (command == "shutdown") { await Handle(id, command, index); break; }
    _ = Handle(id, command, index);
}
