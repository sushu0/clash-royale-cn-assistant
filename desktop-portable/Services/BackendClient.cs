using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using ClashAssistant.Desktop.Models;

namespace ClashAssistant.Desktop.Services;

public sealed class BackendRequestException : Exception
{
    public string Command { get; }
    public bool ResultUnknown { get; }
    public bool IsTransportFailure { get; }
    public bool IsTimeout { get; }

    internal BackendRequestException(string message, string command, bool resultUnknown = false,
        bool transportFailure = false, bool timeout = false, Exception? inner = null) : base(message, inner)
    {
        Command = command;
        ResultUnknown = resultUnknown;
        IsTransportFailure = transportFailure;
        IsTimeout = timeout;
    }
}

/// <summary>A local JSONL bridge. It never retries commands which can change bot state.</summary>
public sealed class BackendClient : IAsyncDisposable
{
    private const int MaxResponseBytes = 16 * 1024 * 1024;
    private const int MaxDiagnosticCharacters = 16 * 1024;
    private static readonly TimeSpan SnapshotTimeout = TimeSpan.FromSeconds(15);
    private static readonly TimeSpan StartTimeout = TimeSpan.FromSeconds(150);
    private static readonly TimeSpan ShopTimeout = TimeSpan.FromSeconds(300);
    private static readonly TimeSpan StopTimeout = TimeSpan.FromSeconds(45);
    private static readonly UTF8Encoding StrictUtf8 = new(false, true);
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        MaxDepth = 64
    };
    private static readonly HashSet<string> AllowedCommands = new(StringComparer.Ordinal)
        { "snapshot", "start", "shop_daily", "stop", "reports", "shutdown" };
    private static readonly Regex SensitiveField = new(
        @"(?i)\b(?:authorization|cookie|password|passwd|access[_ -]?token|refresh[_ -]?token|api[_ -]?key)\b[^\r\n]*",
        RegexOptions.CultureInvariant);
    private readonly string _executable;
    private readonly string _dataRoot;
    private readonly bool _readOnly;
    private readonly SemaphoreSlim _requestGate = new(1, 1);
    private readonly SemaphoreSlim _lifecycleGate = new(1, 1);
    private readonly ConcurrentDictionary<string, PendingRequest> _pending = new(StringComparer.Ordinal);
    private readonly StringBuilder _diagnostics = new();
    private readonly object _diagnosticGuard = new();
    private ProcessRun? _run;
    private int _disposed;

    public BackendClient(string executable, string dataRoot, bool readOnly = false)
    {
        _executable = ResolveOwnedPath(executable, nameof(executable));
        _dataRoot = ResolveOwnedPath(dataRoot, nameof(dataRoot));
        _readOnly = readOnly;
    }

    public bool IsRunning => Volatile.Read(ref _disposed) == 0 && _run is { Fault: null } run && !run.Process.HasExited;

    /// <summary>Only stderr from the owned bridge; capped and redacted.</summary>
    public string DiagnosticText
    {
        get { lock (_diagnosticGuard) return _diagnostics.ToString(); }
    }

    public async Task StartAsync(CancellationToken cancellationToken = default)
    {
        ThrowIfDisposed();
        await _lifecycleGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            ThrowIfDisposed();
            if (_run is { Fault: null } current && !current.Process.HasExited) return;
            if (_run is { } previous) await CloseRunAsync(previous).ConfigureAwait(false);
            if (!File.Exists(_executable)) throw new FileNotFoundException("机器人后端程序不存在。", _executable);
            var startInfo = new ProcessStartInfo(_executable)
            {
                WorkingDirectory = Path.GetDirectoryName(_executable)!,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardInput = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardInputEncoding = new UTF8Encoding(false),
                StandardOutputEncoding = new UTF8Encoding(false),
                StandardErrorEncoding = new UTF8Encoding(false)
            };
            startInfo.ArgumentList.Add("--data-root");
            startInfo.ArgumentList.Add(_dataRoot);
            if (_readOnly) startInfo.ArgumentList.Add("--read-only");
            string temp = Path.Combine(_dataRoot, "work", "wpf-backend-runtime", "temp");
            Directory.CreateDirectory(temp);
            startInfo.Environment["TEMP"] = temp;
            startInfo.Environment["TMP"] = temp;
            startInfo.Environment["PYCLASHBOT_DATA_ROOT"] = _dataRoot;
            var process = new Process { StartInfo = startInfo };
            try
            {
                if (!process.Start()) throw new IOException("机器人后端未能启动。");
            }
            catch { process.Dispose(); throw; }
            var run = new ProcessRun(process);
            _run = run;
            run.StdoutTask = ReadResponsesAsync(run);
            run.StderrTask = ReadDiagnosticsAsync(run);
        }
        finally { _lifecycleGate.Release(); }
    }

    public async Task<ConsoleSnapshot> GetSnapshotAsync(CancellationToken cancellationToken = default)
    {
        var result = await ReadCommandAsync<ConsoleSnapshot>("snapshot", cancellationToken).ConfigureAwait(false);
        if (result.State is not ("running" or "starting" or "stopping" or "stopped" or "paused") || result.Runtime is null ||
            string.IsNullOrWhiteSpace(result.Runtime.DataRoot) ||
            !Path.GetFullPath(result.Runtime.DataRoot).Equals(_dataRoot, StringComparison.OrdinalIgnoreCase))
            throw new BackendRequestException("机器人状态或数据目录身份不匹配，已保留原显示状态。", "snapshot");
        return result;
    }

    public async Task<IReadOnlyList<ErrorReportRecord>> GetReportsAsync(CancellationToken cancellationToken = default)
    {
        var result = await ReadCommandAsync<ReportsResponse>("reports", cancellationToken).ConfigureAwait(false);
        return result.Reports;
    }

    public Task<CommandResult> StartBotAsync(CancellationToken cancellationToken = default) =>
        RequestAsync<CommandResult>("start", StartTimeout, cancellationToken);

    public Task<CommandResult> StopBotAsync(CancellationToken cancellationToken = default) =>
        RequestAsync<CommandResult>("stop", StopTimeout, cancellationToken);

    public Task<CommandResult> PurchaseDailyShopAsync(CancellationToken cancellationToken = default) =>
        RequestAsync<CommandResult>("shop_daily", ShopTimeout, cancellationToken);

    private async Task<T> ReadCommandAsync<T>(string command, CancellationToken cancellationToken)
    {
        using var budget = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        budget.CancelAfter(SnapshotTimeout);
        try
        {
            try { return await RequestAsync<T>(command, SnapshotTimeout, budget.Token).ConfigureAwait(false); }
            catch (BackendRequestException error) when (error.IsTransportFailure && !error.IsTimeout && !budget.IsCancellationRequested)
            {
                // The same 15-second budget covers both attempts. Mutations never use this path.
                return await RequestAsync<T>(command, SnapshotTimeout, budget.Token).ConfigureAwait(false);
            }
        }
        catch (OperationCanceledException error) when (!cancellationToken.IsCancellationRequested)
        {
            throw new BackendRequestException("读取机器人状态超时，请稍后刷新。", command, timeout: true, inner: error);
        }
    }

    private async Task<T> RequestAsync<T>(string command, TimeSpan timeout, CancellationToken cancellationToken,
        bool allowDuringDispose = false)
    {
        if (!AllowedCommands.Contains(command)) throw new ArgumentOutOfRangeException(nameof(command));
        if (_readOnly && (command is "start" or "stop" or "shop_daily"))
            throw new BackendRequestException("只读预览无法启动、停止或购买商品。", command);
        if (!allowDuringDispose) ThrowIfDisposed();
        string id = Guid.NewGuid().ToString("D");
        bool sent = false;
        bool mutation = command is "start" or "stop" or "shop_daily";
        using var limit = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        limit.CancelAfter(timeout);
        try
        {
            if (!allowDuringDispose) await StartAsync(limit.Token).ConfigureAwait(false);
            var run = _run ?? throw new IOException("机器人后端尚未启动。");
            var completion = new TaskCompletionSource<BackendResponse>(TaskCreationOptions.RunContinuationsAsynchronously);
            if (!_pending.TryAdd(id, new PendingRequest(run, completion))) throw new IOException("重复的机器人请求编号。");
            string request = JsonSerializer.Serialize(new BackendRequest(id, command), JsonOptions);
            // Serialize complete JSONL writes only. A stop must reach the bridge
            // while start is waiting for readiness, rather than wait behind its reply.
            await _requestGate.WaitAsync(limit.Token).ConfigureAwait(false);
            try
            {
                // A partial pipe write has an unknown outcome for a mutation too.
                sent = true;
                await run.Process.StandardInput.WriteLineAsync(request.AsMemory(), limit.Token).ConfigureAwait(false);
                await run.Process.StandardInput.FlushAsync(limit.Token).ConfigureAwait(false);
            }
            finally { _requestGate.Release(); }
            var response = await completion.Task.WaitAsync(limit.Token).ConfigureAwait(false);
            if (response.Ok != true)
                throw new BackendRequestException(SafeText(response.Error ?? "机器人后端未完成该操作。"), command,
                    resultUnknown: mutation);
            try
            {
                return response.Data.Deserialize<T>(JsonOptions)
                    ?? throw new JsonException("机器人后端返回了空数据。");
            }
            catch (JsonException error)
            {
                throw new BackendRequestException("机器人后端响应格式不兼容。", command, resultUnknown: mutation, inner: error);
            }
        }
        catch (OperationCanceledException error)
        {
            if (mutation && sent)
                throw new BackendRequestException("操作等待已结束，实际结果尚未确认；请先刷新机器人状态。", command,
                    resultUnknown: true, timeout: !cancellationToken.IsCancellationRequested, inner: error);
            if (cancellationToken.IsCancellationRequested) throw;
            throw new BackendRequestException("机器人后端响应超时。", command, timeout: true, inner: error);
        }
        catch (BackendRequestException) { throw; }
        catch (Exception error) when (error is IOException or InvalidOperationException or ObjectDisposedException)
        {
            throw new BackendRequestException(mutation && sent
                ? "机器人连接中断，操作结果尚未确认；请先刷新状态。"
                : "机器人后端连接中断，请稍后刷新。", command, mutation && sent, transportFailure: true, inner: error);
        }
        finally
        {
            _pending.TryRemove(id, out _);
        }
    }

    private async Task ReadResponsesAsync(ProcessRun run)
    {
        var buffer = new byte[8192];
        using var line = new MemoryStream();
        try
        {
            while (true)
            {
                int count = await run.Process.StandardOutput.BaseStream.ReadAsync(buffer.AsMemory(), run.Cancel.Token).ConfigureAwait(false);
                if (count == 0) throw new IOException(line.Length == 0 ? "机器人后端已关闭输出。" : "机器人后端返回了未完成的 JSONL 响应。");
                int segment = 0;
                for (int index = 0; index < count; index++)
                {
                    if (buffer[index] != (byte)'\n') continue;
                    AppendFrame(line, buffer.AsSpan(segment, index - segment));
                    if (line.Length > 0) DispatchResponse(run, StrictUtf8.GetString(line.GetBuffer(), 0, checked((int)line.Length)).TrimEnd('\r'));
                    line.SetLength(0);
                    segment = index + 1;
                }
                AppendFrame(line, buffer.AsSpan(segment, count - segment));
            }
        }
        catch (Exception error) when (error is IOException or JsonException or DecoderFallbackException or OperationCanceledException or ObjectDisposedException or InvalidOperationException)
        {
            run.Fault = error;
            foreach (var entry in _pending)
                if (ReferenceEquals(entry.Value.Run, run)) entry.Value.Completion.TrySetException(new IOException("机器人后端 JSONL 连接已结束。", error));
        }
    }

    private static void AppendFrame(MemoryStream line, ReadOnlySpan<byte> part)
    {
        if (line.Length + part.Length > MaxResponseBytes) throw new IOException("机器人后端响应超过 16 MiB 上限。");
        line.Write(part);
    }

    private void DispatchResponse(ProcessRun run, string line)
    {
        var response = JsonSerializer.Deserialize<BackendResponse>(line, JsonOptions)
            ?? throw new JsonException("后端响应为空。");
        if (!Guid.TryParse(response.Id, out _) || response.Ok is null) throw new JsonException("后端响应编号或状态无效。");
        if (_pending.TryGetValue(response.Id, out var pending) && ReferenceEquals(pending.Run, run))
            pending.Completion.TrySetResult(response);
        // Late responses after a timeout, and unknown IDs, cannot complete another request.
    }

    private async Task ReadDiagnosticsAsync(ProcessRun run)
    {
        var buffer = new char[2048];
        var line = new StringBuilder();
        bool discardLine = false;
        try
        {
            while (true)
            {
                int count = await run.Process.StandardError.ReadAsync(buffer.AsMemory(), run.Cancel.Token).ConfigureAwait(false);
                if (count == 0)
                {
                    if (!discardLine && line.Length > 0) AppendDiagnostic(line.ToString());
                    return;
                }
                for (int index = 0; index < count; index++)
                {
                    char value = buffer[index];
                    if (value == '\n')
                    {
                        if (!discardLine) AppendDiagnostic(line.ToString());
                        line.Clear();
                        discardLine = false;
                    }
                    else if (!discardLine)
                    {
                        line.Append(value);
                        if (line.Length > MaxDiagnosticCharacters)
                        {
                            line.Clear();
                            discardLine = true;
                            AppendDiagnostic("[后端诊断行过长，已省略]");
                        }
                    }
                }
            }
        }
        catch (Exception error) when (error is IOException or OperationCanceledException or ObjectDisposedException or InvalidOperationException)
        { /* The stdout loop owns connection failure. Stderr is diagnostic only. */ }
    }

    private void AppendDiagnostic(string value)
    {
        lock (_diagnosticGuard)
        {
            // Redact complete lines so a key split across stream chunks stays masked.
            _diagnostics.Append(SafeText(value)).Append('\n');
            if (_diagnostics.Length > MaxDiagnosticCharacters)
                _diagnostics.Remove(0, _diagnostics.Length - MaxDiagnosticCharacters);
        }
    }

    public async ValueTask DisposeAsync()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0) return;
        // Shutdown only closes the bridge. It is deliberately separate from StopBotAsync.
        try
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
            if (_run is { Fault: null } run && !run.Process.HasExited)
                await RequestAsync<CommandResult>("shutdown", TimeSpan.FromSeconds(5), timeout.Token, allowDuringDispose: true).ConfigureAwait(false);
        }
        catch (Exception error) when (error is BackendRequestException or IOException or OperationCanceledException or ObjectDisposedException)
        { /* The bridge can still be reaped below without terminating its bot descendants. */ }
        await _lifecycleGate.WaitAsync().ConfigureAwait(false);
        try
        {
            if (_run is { } run) await CloseRunAsync(run).ConfigureAwait(false);
            _run = null;
        }
        finally { _lifecycleGate.Release(); }
    }

    private static async Task CloseRunAsync(ProcessRun run)
    {
        run.Cancel.Cancel();
        if (!run.Process.HasExited)
        {
            // This is the bridge instance created by this client; never kill its process tree.
            try { run.Process.Kill(entireProcessTree: false); }
            catch (InvalidOperationException) { }
        }
        try { await Task.WhenAll(run.StdoutTask, run.StderrTask).WaitAsync(TimeSpan.FromSeconds(2)).ConfigureAwait(false); }
        catch (TimeoutException) { }
        run.Process.Dispose();
        run.Cancel.Dispose();
    }

    private static string ResolveOwnedPath(string value, string name)
    {
        return DesktopSettings.ValidateOwnedPath(value, name);
    }

    private static string SafeText(string value)
    {
        string safe = SensitiveField.Replace(value, "[敏感字段已隐藏]");
        return safe.Length <= MaxDiagnosticCharacters ? safe : safe[^MaxDiagnosticCharacters..];
    }

    private void ThrowIfDisposed() => ObjectDisposedException.ThrowIf(Volatile.Read(ref _disposed) != 0, this);

    private sealed class ProcessRun
    {
        public Process Process { get; }
        public CancellationTokenSource Cancel { get; } = new();
        public Task StdoutTask { get; set; } = Task.CompletedTask;
        public Task StderrTask { get; set; } = Task.CompletedTask;
        public volatile Exception? Fault;
        public ProcessRun(Process process) { Process = process; }
    }

    private sealed record PendingRequest(ProcessRun Run, TaskCompletionSource<BackendResponse> Completion);
    private sealed record BackendRequest([property: JsonPropertyName("id")] string Id,
        [property: JsonPropertyName("command")] string Command);
    private sealed class BackendResponse
    {
        [JsonPropertyName("id")] public string Id { get; set; } = "";
        [JsonPropertyName("ok")] public bool? Ok { get; set; }
        [JsonPropertyName("data")] public JsonElement Data { get; set; }
        [JsonPropertyName("error")] public string? Error { get; set; }
    }
}
