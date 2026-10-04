using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace ClashAssistant.Desktop.Models;

public sealed class ConsoleSnapshot
{
    [JsonRequired, JsonPropertyName("state")] public string State { get; set; } = "stopped";
    [JsonPropertyName("selected_strategy")] public string SelectedStrategy { get; set; } = "random";
    [JsonPropertyName("updated_at")] public string UpdatedAt { get; set; } = "";
    [JsonPropertyName("live")] public JsonElement Live { get; set; }
    [JsonPropertyName("scopes")] public Dictionary<string, HistorySnapshot> Scopes { get; set; } = new(StringComparer.Ordinal);
    [JsonPropertyName("reward_totals")] public RewardTotals RewardTotals { get; set; } = new();
    [JsonPropertyName("reports")] public List<ErrorReportRecord> Reports { get; set; } = new();
    [JsonPropertyName("recent_events")] public List<string> RecentEvents { get; set; } = new();
    [JsonRequired, JsonPropertyName("runtime")] public RuntimeSnapshot Runtime { get; set; } = new();
    [JsonPropertyName("busy")] public string? Busy { get; set; }
    [JsonPropertyName("history_error")] public string? HistoryError { get; set; }
    [JsonPropertyName("error_report_pending")] public bool ErrorReportPending { get; set; }
}

public sealed class HistorySnapshot
{
    [JsonPropertyName("strategy")] public string Strategy { get; set; } = "random";
    [JsonPropertyName("total")] public BattleSummary Total { get; set; } = new();
    [JsonPropertyName("recent")] public BattleSummary Recent { get; set; } = new();
    [JsonPropertyName("session")] public BattleSummary Session { get; set; } = new();
    [JsonPropertyName("latest_session")] public SessionRecord? LatestSession { get; set; }
    [JsonPropertyName("records")] public List<BattleRecord> Records { get; set; } = new();
    [JsonPropertyName("recent_results")] public List<string> RecentResults { get; set; } = new();
    [JsonPropertyName("versions")] public List<StrategyVersion> Versions { get; set; } = new();
    [JsonPropertyName("malformed_lines")] public int MalformedLines { get; set; }
    [JsonPropertyName("conflicts")] public int Conflicts { get; set; }
    [JsonPropertyName("first_at")] public string? FirstAt { get; set; }
    [JsonPropertyName("last_at")] public string? LastAt { get; set; }
}

public class BattleSummary
{
    [JsonPropertyName("total")] public int Total { get; set; }
    [JsonPropertyName("wins")] public int Wins { get; set; }
    [JsonPropertyName("losses")] public int Losses { get; set; }
    [JsonPropertyName("draws")] public int Draws { get; set; }
    [JsonPropertyName("unknown")] public int Unknown { get; set; }
    [JsonPropertyName("win_rate")] public double? WinRate { get; set; }
    [JsonPropertyName("streak")] public int Streak { get; set; }
    [JsonPropertyName("streak_result")] public string? StreakResult { get; set; }
    [JsonPropertyName("best_win_streak")] public int BestWinStreak { get; set; }
}

public sealed class StrategyVersion : BattleSummary
{
    [JsonPropertyName("policy")] public string? Policy { get; set; }
    [JsonPropertyName("rule_version")] public string? RuleVersion { get; set; }
    [JsonPropertyName("strategy_hash")] public string? StrategyHash { get; set; }
    [JsonPropertyName("asset_hash")] public string? AssetHash { get; set; }
    [JsonPropertyName("environment_hash")] public string? EnvironmentHash { get; set; }
}

public sealed class BattleRecord
{
    [JsonPropertyName("strategy")] public string Strategy { get; set; } = "";
    [JsonPropertyName("session")] public string Session { get; set; } = "";
    [JsonPropertyName("battle")] public int Battle { get; set; }
    [JsonPropertyName("time")] public string Time { get; set; } = "";
    [JsonPropertyName("policy")] public string? Policy { get; set; }
    [JsonPropertyName("mode")] public string? Mode { get; set; }
    [JsonPropertyName("result")] public string Result { get; set; } = "未知";
    [JsonPropertyName("confirmed")] public int? Confirmed { get; set; }
    [JsonPropertyName("attempts")] public int? Attempts { get; set; }
    [JsonPropertyName("evidence")] public string? Evidence { get; set; }
    [JsonPropertyName("conflict")] public int Conflict { get; set; }
    [JsonPropertyName("rule_version")] public string? RuleVersion { get; set; }
    [JsonPropertyName("strategy_hash")] public string? StrategyHash { get; set; }
    [JsonPropertyName("asset_hash")] public string? AssetHash { get; set; }
    [JsonPropertyName("environment_hash")] public string? EnvironmentHash { get; set; }
    [JsonPropertyName("evidence_hash")] public string? EvidenceHash { get; set; }
    [JsonPropertyName("evidence_status")] public string EvidenceStatus { get; set; } = "未记录";
}

public sealed class SessionRecord
{
    [JsonPropertyName("strategy")] public string Strategy { get; set; } = "";
    [JsonPropertyName("session")] public string Session { get; set; } = "";
    [JsonPropertyName("time")] public string Time { get; set; } = "";
    [JsonPropertyName("policy")] public string? Policy { get; set; }
    [JsonPropertyName("event")] public string? Event { get; set; }
    [JsonPropertyName("detail")] public string? Detail { get; set; }
}

public sealed class RewardTotals
{
    [JsonPropertyName("rewards")] public int Rewards { get; set; }
    [JsonPropertyName("coins")] public long Coins { get; set; }
    [JsonPropertyName("unknown_coin_items")] public int UnknownCoinItems { get; set; }
}

public sealed class RuntimeSnapshot
{
    [JsonPropertyName("memuc")] public string Memuc { get; set; } = "";
    [JsonPropertyName("adb")] public string Adb { get; set; } = "";
    [JsonPropertyName("serial")] public string Serial { get; set; } = "";
    [JsonPropertyName("data_root")] public string DataRoot { get; set; } = "";
    [JsonPropertyName("vm_index")] public int VmIndex { get; set; }
    [JsonPropertyName("python")] public string Python { get; set; } = "";
}

public sealed class ErrorReportRecord
{
    [JsonPropertyName("event_id")] public string EventId { get; set; } = "";
    [JsonPropertyName("created_at")] public string CreatedAt { get; set; } = "";
    [JsonPropertyName("occurred_at")] public string? OccurredAt { get; set; }
    [JsonPropertyName("reason")] public string Reason { get; set; } = "";
    [JsonPropertyName("report_dir")] public string ReportDir { get; set; } = "";
    [JsonPropertyName("report_md")] public string? ReportMd { get; set; }
    [JsonPropertyName("report_json")] public string ReportJson { get; set; } = "";
    [JsonPropertyName("game_png")] public string? GamePng { get; set; }
    [JsonPropertyName("screenshot_status")] public string ScreenshotStatus { get; set; } = "unknown";
    [JsonPropertyName("runtime")] public JsonElement Runtime { get; set; }
    [JsonPropertyName("session")] public string? Session { get; set; }
    [JsonPropertyName("pending")] public bool Pending { get; set; }
    [JsonPropertyName("incomplete")] public bool Incomplete { get; set; }
    [JsonIgnore] public string DisplayTime => string.IsNullOrWhiteSpace(OccurredAt) ? CreatedAt : OccurredAt;
}

public sealed class CommandResult
{
    [JsonPropertyName("state")] public string State { get; set; } = "";
    [JsonPropertyName("message")] public string Message { get; set; } = "";
    [JsonPropertyName("shutdown")] public bool Shutdown { get; set; }
}

internal sealed class ReportsResponse
{
    [JsonPropertyName("reports")] public List<ErrorReportRecord> Reports { get; set; } = new();
    [JsonPropertyName("updated_at")] public string UpdatedAt { get; set; } = "";
}
