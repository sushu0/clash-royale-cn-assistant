using ClashAssistant.Desktop.Services;

if(args.Length == 1 && args[0] == "--real-read-only")
{
    string dataRoot=@"D:\codex\CodexWork\clash";
    await using var real = new BackendClient(Path.Combine(dataRoot,"outputs/wpf-desktop-20261004/backend/ClashBackend.exe"),dataRoot,true);
    await real.StartAsync();
    var snapshot=await real.GetSnapshotAsync();
    var reports=await real.GetReportsAsync();
    var validation=new{SnapshotState=snapshot.State,DataRoot=snapshot.Runtime.DataRoot,RandomBattles=snapshot.Scopes["random"].Total.Total,
        Rewards=snapshot.RewardTotals.Rewards,Coins=snapshot.RewardTotals.Coins,SnapshotReportCount=snapshot.Reports.Count,
        ReportCommandCount=reports.Count,OccurrenceTime=reports.FirstOrDefault()?.DisplayTime,ReadOnly=true,NoStartOrStopSent=true};
    string json=System.Text.Json.JsonSerializer.Serialize(validation,new System.Text.Json.JsonSerializerOptions{WriteIndented=true});
    File.WriteAllText(Path.Combine(dataRoot,"work/wpf-rewrite-20261004/client-real-readonly.json"),json);
    Console.WriteLine(json);
    return;
}
string folder = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../.."));
string fake = Path.Combine(folder, "FakeBackend/bin/Debug/net10.0/FakeBackend.exe");
string cases = Path.Combine(folder, "cases-" + DateTime.UtcNow.ToString("yyyyMMddHHmmssffff"));
int checks = 0;
void Check(bool value, string label) { if (!value) throw new Exception(label); checks++; Console.WriteLine("PASS " + label); }

await using (var client = new BackendClient(fake, Path.Combine(cases,"matching")))
{
    await client.StartAsync();
    var snapshots = await Task.WhenAll(client.GetSnapshotAsync(),client.GetSnapshotAsync());
    Check(snapshots.All(s => s.State == "running"), "matched response IDs and serialized reads");
    var s = snapshots[0];
    Check(s.Scopes["random"].Total.Wins == 7 && s.Scopes["random"].Total.WinRate > 0.58, "snake case and nested summary");
    Check(s.Scopes["random"].Records[0].Confirmed == 18 && s.RewardTotals.Coins == 3000000000L, "nullable records and large cumulative coins");
    Check(s.Reports[0].DisplayTime == "earlier" && s.Live.GetProperty("completed").GetInt32() == 12, "report occurrence time and JSON live payload");
    Check((await client.GetReportsAsync()).Count == 1, "reports object response");
}
await using (var client = new BackendClient(fake,Path.Combine(cases,"retry")))
{
    Check((await client.GetSnapshotAsync()).State == "running", "read-only transport reconnect");
    Check(File.ReadAllLines(Path.Combine(cases,"retry/requests.log")).Count(x=>x=="snapshot") == 2, "read-only retries exactly once");
}
await using (var client = new BackendClient(fake,Path.Combine(cases,"start-cancel")))
{
    await client.StartAsync();
    using var cancel = new CancellationTokenSource(80);
    try { await client.StartBotAsync(cancel.Token); throw new Exception("start should be cancelled"); }
    catch(BackendRequestException error) { Check(error.ResultUnknown && error.Command == "start", "cancelled mutation reports unknown result"); }
    Check((await client.GetSnapshotAsync()).State == "running", "late mutation reply does not replace fresh snapshot");
    Check(File.ReadAllLines(Path.Combine(cases,"start-cancel/requests.log")).Count(x=>x=="start") == 1, "start is never automatically retried");
}
await using (var client = new BackendClient(fake,Path.Combine(cases,"oversized")))
{
    try { await client.GetSnapshotAsync(); throw new Exception("oversized frame should fail"); }
    catch(BackendRequestException error) { Check(error.IsTransportFailure && !error.ResultUnknown,"16 MiB frame guard"); }
}
await using (var client = new BackendClient(fake,Path.Combine(cases,"stderr")))
{
    await client.GetSnapshotAsync();
    await Task.Delay(100);
    Check(client.DiagnosticText.Length <= 16384 && !client.DiagnosticText.Contains("DO_NOT_EXPOSE"),"bounded and redacted owned stderr");
}
await using (var client = new BackendClient(fake,Path.Combine(cases,"read-only"),true))
{
    await client.GetSnapshotAsync();
    try {await client.StartBotAsync();throw new Exception("readonly mutation should fail");}
    catch(BackendRequestException error){Check(!error.ResultUnknown,"read-only preview rejects mutation before sending");}
    Check(!File.ReadAllLines(Path.Combine(cases,"read-only/requests.log")).Contains("start"),"read-only preview sends no mutation");
}
foreach(string mode in new[]{"missing-state","wrong-root"})
{
    await using var client=new BackendClient(fake,Path.Combine(cases,mode));
    try {await client.GetSnapshotAsync();throw new Exception("invalid snapshot should fail");}
    catch(BackendRequestException){Check(true,"fail-closed snapshot " + mode);}
}
try { _ = new BackendClient(@"C:\unrelated.exe", cases); throw new Exception("outside root should fail"); }
catch(ArgumentException) { Check(true,"D-drive storage boundary"); }
Console.WriteLine($"{checks} checks passed");
