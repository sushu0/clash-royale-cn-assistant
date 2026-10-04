// This inert helper never calls ADB, MEmu, or another executable. Its only
// outputs are a readiness string, an explicitly scoped marker, and a wait.
if (args.SequenceEqual(new[] { "isvmrunning", "-i", "0" }))
{
    Console.WriteLine("running");
    return 0;
}
if (args.Length == 3 && args[0] == "-s" && !string.IsNullOrWhiteSpace(args[1]) && args[2] == "get-state")
{
    string? markerValue = Environment.GetEnvironmentVariable("CLASH_FAKE_TOOL_MARKER");
    if (string.IsNullOrWhiteSpace(markerValue))
    {
        Console.Error.WriteLine("CLASH_FAKE_TOOL_MARKER is required for get-state simulation");
        return 64;
    }
    string marker = Path.GetFullPath(markerValue);
    string boundary = Path.GetFullPath(@"D:\codex").TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
    if (!marker.StartsWith(boundary, StringComparison.OrdinalIgnoreCase))
    {
        Console.Error.WriteLine("marker must stay under D:\\codex");
        return 64;
    }
    Directory.CreateDirectory(Path.GetDirectoryName(marker)!);
    await File.WriteAllTextAsync(marker, System.Text.Json.JsonSerializer.Serialize(new
    {
        phase = "waiting-for-get-state",
        pid = Environment.ProcessId,
        created_at = DateTimeOffset.UtcNow.ToString("O"),
        command = "get-state",
        stalled_seconds = 30,
        real_device_access = false
    }));
    await Task.Delay(TimeSpan.FromSeconds(30));
    Console.WriteLine("device");
    return 0;
}
Console.Error.WriteLine("unsupported simulated command");
return 64;
