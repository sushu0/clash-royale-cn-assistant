using System;
using System.IO;
using System.Text.Json;
using ClashAssistant.Desktop.Interop;
using ClashAssistant.Desktop.Services;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        if (args.Length == 2 && args[0] == "--guard-probe")
        {
            using var guard = new SingleInstance(args[1]);
            Console.WriteLine(JsonSerializer.Serialize(new { primary = guard.Acquire(), mutex = guard.MutexName, show_event = guard.ShowEventName }));
            return;
        }
        if (args.Length == 2 && args[0] == "--lock-probe")
        {
            using var stream = new FileStream(args[1], FileMode.Open, FileAccess.ReadWrite, FileShare.ReadWrite | FileShare.Delete);
            bool blocked = false;
            try { stream.Lock(0, 1); stream.Unlock(0, 1); } catch (IOException) { blocked = true; }
            Console.WriteLine(JsonSerializer.Serialize(new { blocked }));
            return;
        }
        Console.WriteLine(JsonSerializer.Serialize(NativeInteropSelfTests.Run(@"D:\codex\CodexWork\clash")));
    }
}
