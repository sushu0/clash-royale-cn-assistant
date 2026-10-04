using System.Text.Json;

Console.InputEncoding = System.Text.Encoding.UTF8;
Console.OutputEncoding = new System.Text.UTF8Encoding(false);
string root = args.Length >= 2 ? args[1] : "";
string mode = Path.GetFileName(root);
Directory.CreateDirectory(root);
if (mode == "stderr") Console.Error.WriteLine("bridge diagnostic password=DO_NOT_EXPOSE\n" + new string('x', 20000));
while (await Console.In.ReadLineAsync() is { } line)
{
    using var input = JsonDocument.Parse(line);
    string id = input.RootElement.GetProperty("id").GetString()!;
    string command = input.RootElement.GetProperty("command").GetString()!;
    await File.AppendAllTextAsync(Path.Combine(root, "requests.log"), command + "\n");
    if (command == "snapshot" && mode == "retry" && !File.Exists(Path.Combine(root, "once")))
    {
        await File.WriteAllTextAsync(Path.Combine(root, "once"), "first disconnected");
        return;
    }
    if (command == "snapshot" && mode == "oversized")
    {
        Console.WriteLine(new string('x', 17 * 1024 * 1024));
        continue;
    }
    if (command is "start" or "stop") await Task.Delay(300);
    object data = command switch
    {
        "snapshot" => new {
            STATE = "running", selected_strategy = "random", updated_at = "2026-10-04T12:00:00+08:00",
            live = new { state = "battle", completed = 12 },
            scopes = new { random = new { strategy = "random", total = new { total = 12, wins = 7, losses = 4, draws = 0, unknown = 1, win_rate = 7.0 / 12 }, records = new[] {new { battle = 12, result = "胜利", confirmed = 18 }} } },
            reward_totals = new { rewards = 5, coins = 3000000000L, unknown_coin_items = 1 },
            reports = new[] {new { event_id = "e1", created_at = "later", occurred_at = "earlier", reason = "暂停", report_json = "report.json", pending = false, incomplete = false }},
            recent_events = new[] { "对战开始" }, runtime = new { serial = "127.0.0.1:21503", data_root = root, vm_index = 0 }
        },
        "reports" => new { reports = new[] {new {event_id = "e1", reason = "暂停", occurred_at = "earlier"}}, updated_at = "now" },
        _ => new { state = command == "stop" ? "stopped" : "running", message = "ok", shutdown = command == "shutdown" }
    };
    if (command == "snapshot" && mode == "missing-state") data = new {runtime=new {data_root=root}};
    if (command == "snapshot" && mode == "wrong-root") data = new {state="running",runtime=new {data_root=@"D:\codex\unrelated"}};
    // An unrelated response must never complete the waiting request.
    if (mode == "matching") Console.WriteLine(JsonSerializer.Serialize(new {id=Guid.NewGuid().ToString(), ok=true,data=new {state="wrong"}}));
    Console.WriteLine(JsonSerializer.Serialize(new { id, ok = true, data }));
    await Console.Out.FlushAsync();
    if (command == "shutdown") return;
}
