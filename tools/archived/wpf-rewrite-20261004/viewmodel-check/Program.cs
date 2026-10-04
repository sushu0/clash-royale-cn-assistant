using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text.Json;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using ClashAssistant.Desktop.Models;
using ClashAssistant.Desktop.ViewModels;

internal static class Program
{
    private const string ProjectRoot = @"D:\codex\CodexWork\clash\work\wpf-rewrite-20261004\viewmodel-check";
    private static readonly string FixtureRoot = Path.Combine(ProjectRoot, "fixtures");
    private static readonly List<object> Results = new();
    private static int Failed;

    [STAThread]
    private static void Main()
    {
        CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo("zh-CN");
        CultureInfo.CurrentUICulture = CultureInfo.GetCultureInfo("zh-CN");
        Directory.CreateDirectory(FixtureRoot);
        ErrorReportRecord old = Report("old", "2026-10-03T09:12:00+08:00", "较早暂停：读取奖励失败", 32);
        ErrorReportRecord latest = Report("latest", "2026-10-04T09:12:00+08:00", "最新暂停：连接失败", 160);
        ErrorReportRecord newer = Report("newer", "2026-10-04T10:12:00+08:00", "新增暂停：匹配异常", 220);
        var snapshot = Snapshot(new[] { latest, old }, "{\"state\":\"battle\",\"session\":\"fixture-only\",\"cards_confirmed\":12}");
        var vm = new DesktopViewModel(FixtureRoot, false);

        Case("two_historical_reports_are_displayed", () =>
        {
            vm.Apply(snapshot);
            Assert(vm.Reports.Count == 2 && vm.Reports.Any(row => row.Record.EventId == "old") && vm.Reports.Any(row => row.Record.EventId == "latest"));
            Assert(vm.SelectedReport?.Record.EventId == "latest");
        });
        Case("old_report_selection_survives_refresh_and_new_report", () =>
        {
            vm.SelectedReport = vm.Reports.Single(row => row.Record.EventId == "old");
            vm.Apply(snapshot);
            Assert(vm.SelectedReport?.Record.EventId == "old");
            var refreshed = Snapshot(new[] { newer, latest, old }, "{\"state\":\"battle\",\"cards_confirmed\":13}");
            vm.Apply(refreshed);
            Assert(vm.Reports.Count == 3 && vm.SelectedReport?.Record.EventId == "old");
            Assert(vm.ReportText.Contains("较早暂停", StringComparison.Ordinal));
        });
        Case("win_rate_denominator_keeps_unknown_and_draw", () =>
        {
            vm.Apply(snapshot);
            Assert(vm.Total == "4" && vm.Wins == "1" && vm.Losses == "1" && vm.WinRate == "25.0%");
            Assert(vm.TotalNote.Contains("未知 1", StringComparison.Ordinal) && vm.TotalNote.Contains("平局 1", StringComparison.Ordinal));
            Assert(vm.HistoryNote.Contains("未知和平局", StringComparison.Ordinal));
            Assert(vm.Battles.Any(row => row.Result == "未知") && vm.Battles.Any(row => row.Result == "平局"));
            Assert(vm.Versions.Single().Other == "1 / 1");
        });
        Case("report_image_loaded_and_file_handle_released", () =>
        {
            vm.SelectedReport = vm.Reports.Single(row => row.Record.EventId == "old");
            Assert(vm.ReportImage is BitmapSource image && image.IsFrozen && image.PixelWidth > 0);
            using (var exclusive = new FileStream(old.GamePng!, FileMode.Open, FileAccess.ReadWrite, FileShare.None))
                Assert(exclusive.Length > 0);
            string renamed = old.GamePng! + ".loaded";
            File.Move(old.GamePng!, renamed, true);
            Assert(vm.ReportImage is not null);
            File.Move(renamed, old.GamePng!, true);
        });
        Case("present_confirmed_count_is_displayed", () =>
        {
            vm.Apply(snapshot);
            Assert(vm.DeploymentText.Contains("12", StringComparison.Ordinal));
        });
        Case("missing_confirmed_count_is_not_fabricated_as_zero", () =>
        {
            vm.Apply(Snapshot(Array.Empty<ErrorReportRecord>(), "{\"state\":\"starting\"}"));
            Assert(!vm.DeploymentText.Contains("0 次", StringComparison.Ordinal), "未提供cards_confirmed时不能声称已确认0次，实际=" + vm.DeploymentText);
        });
        Case("null_confirmed_count_does_not_crash", () =>
        {
            vm.Apply(Snapshot(Array.Empty<ErrorReportRecord>(), "{\"cards_confirmed\":null}"));
            Assert(!vm.DeploymentText.Contains("0 次", StringComparison.Ordinal));
        });
        Case("string_confirmed_count_does_not_crash", () =>
        {
            vm.Apply(Snapshot(Array.Empty<ErrorReportRecord>(), "{\"cards_confirmed\":\"unknown\"}"));
            Assert(!vm.DeploymentText.Contains("0 次", StringComparison.Ordinal));
        });
        Case("preview_disables_all_bot_mutation_controls", () =>
        {
            var preview = new DesktopViewModel(FixtureRoot, true);
            preview.Apply(snapshot);
            Assert(!preview.CanStart && !preview.CanStop);
            preview.Apply(Snapshot(Array.Empty<ErrorReportRecord>(), "{}", "stopped"));
            Assert(!preview.CanStart && !preview.CanStop);
        });
        Case("scope_change_preserves_main_totals_and_updates_records", () =>
        {
            vm.Apply(snapshot);
            vm.SelectScope("all");
            Assert(vm.Battles.Count == 5 && vm.Total == "4" && vm.WinRate == "25.0%");
            vm.SelectScope("random");
            Assert(vm.Battles.Count == 4);
        });
        Case("evidence_path_boundary_and_extension_are_enforced", () =>
        {
            string reportsRoot = Path.Combine(FixtureRoot, "outputs", "error-reports");
            string outside = Path.Combine(FixtureRoot, "outside", "report.md");
            Directory.CreateDirectory(Path.GetDirectoryName(outside)!); File.WriteAllText(outside, "outside fixture");
            string prefixCollision = Path.Combine(FixtureRoot, "outputs", "error-reports-escape", "report.md");
            Directory.CreateDirectory(Path.GetDirectoryName(prefixCollision)!); File.WriteAllText(prefixCollision, "prefix fixture");
            Assert(DesktopViewModel.LocalEvidence(old.ReportMd, reportsRoot, ".md") is not null);
            Assert(DesktopViewModel.LocalEvidence(outside, reportsRoot, ".md") is null);
            Assert(DesktopViewModel.LocalEvidence(prefixCollision, reportsRoot, ".md") is null);
            Assert(DesktopViewModel.LocalEvidence(old.ReportMd, reportsRoot, ".png") is null);
        });
        Case("reparse_point_report_path_is_rejected", () =>
        {
            string reportsRoot = Path.Combine(FixtureRoot, "outputs", "error-reports");
            string link = Path.Combine(reportsRoot, "junction-fixture", "report.md");
            Assert(File.Exists(link), "需要先创建任务专属junction fixture");
            Assert((File.GetAttributes(Path.GetDirectoryName(link)!) & FileAttributes.ReparsePoint) != 0);
            Assert(DesktopViewModel.LocalEvidence(link, reportsRoot, ".md") is null);
        });
        Case("stopped_calibration_request_blocks_start_and_is_unchanged", () =>
        {
            string root = RequestFixture("calibration", "Finish current battle and reward cycle, then pause for navigation calibration.\n");
            string path = RequestPath(root);
            byte[] before = File.ReadAllBytes(path); DateTime written = File.GetLastWriteTimeUtc(path);
            var view = new DesktopViewModel(root, false);
            view.Apply(Snapshot(Array.Empty<ErrorReportRecord>(), "{}", "stopped"));
            Assert(view.HasStopRequest && view.HasCalibrationRequest && !view.CanStart && !view.CanStop);
            Assert(view.Phase == "任务已停止 · 等待导航校准");
            Assert(view.PhaseDescription.Contains("保留", StringComparison.Ordinal) && view.PhaseDescription.Contains("不会自动恢复", StringComparison.Ordinal));
            Assert(view.StartHint.Contains("导航校准", StringComparison.Ordinal));
            Assert(File.ReadAllBytes(path).SequenceEqual(before) && File.GetLastWriteTimeUtc(path) == written);
        });
        Case("running_calibration_request_keeps_stop_available", () =>
        {
            var view = new DesktopViewModel(RequestFixture("running", "navigation calibration"), false);
            view.Apply(Snapshot(Array.Empty<ErrorReportRecord>(), "{\"state\":\"mastery\"}"));
            Assert(view.HasCalibrationRequest && !view.CanStart && view.CanStop);
            Assert(view.PhaseDescription.Contains("当前对战与奖励循环", StringComparison.Ordinal) && view.PhaseDescription.Contains("后暂停", StringComparison.Ordinal));
            view.SetBusy("stop"); Assert(!view.CanStop); view.SetBusy(""); Assert(view.CanStop);
        });
        Case("unknown_drain_reason_does_not_claim_calibration", () =>
        {
            var view = new DesktopViewModel(RequestFixture("unknown", "Operator requested a manual pause for maintenance."), false);
            view.Apply(Snapshot(Array.Empty<ErrorReportRecord>(), "{}", "stopped"));
            Assert(view.HasStopRequest && !view.HasCalibrationRequest && !view.CanStart);
            Assert(!view.Phase.Contains("校准", StringComparison.Ordinal) && !view.PhaseDescription.Contains("校准", StringComparison.Ordinal));
            Assert(!view.StartHint.Contains("校准", StringComparison.Ordinal));
        });
        Case("unreadable_drain_request_is_friendly_and_fail_closed", () =>
        {
            string root = RequestFixture("locked", "navigation calibration");
            using var exclusive = new FileStream(RequestPath(root), FileMode.Open, FileAccess.ReadWrite, FileShare.None);
            var view = new DesktopViewModel(root, false);
            view.Apply(Snapshot(Array.Empty<ErrorReportRecord>(), "{}", "stopped"));
            Assert(view.HasStopRequest && !view.HasCalibrationRequest && !view.CanStart);
            Assert(view.StopRequestReadError.Length > 0 && view.StartHint.Contains("稍后重试", StringComparison.Ordinal));
            Assert(view.PhaseDescription == view.StopRequestReadError);
        });
        Case("ordinary_stopped_remains_manual_startable", () =>
        {
            string root = Path.Combine(FixtureRoot, "ordinary-stopped-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            var view = new DesktopViewModel(root, false);
            view.Apply(Snapshot(Array.Empty<ErrorReportRecord>(), "{}", "stopped"));
            Assert(!view.HasStopRequest && !view.HasCalibrationRequest && view.CanStart && !view.CanStop);
            Assert(view.Phase == "任务已停止" && !view.PhaseDescription.Contains("校准", StringComparison.Ordinal));
        });
        Case("pause_report_binding_is_only_active_for_paused_session_match", () =>
        {
            var view = new DesktopViewModel(FixtureRoot, false);
            view.Apply(Snapshot(new[] { latest, old }, "{}", "stopped"));
            Assert(!view.HasPauseReport && view.ReportBadgeText == "2份");
            Assert(view.LastReportSummary == latest.Reason && view.LastReportTime == "2026-10-04 09:12:00");
            view.Apply(Snapshot(new[] { latest, old }, "{\"session\":\"fixture-session-latest\"}", "paused"));
            Assert(view.HasPauseReport && view.CurrentPauseReport?.Record.EventId == "latest");
            view.Apply(Snapshot(Array.Empty<ErrorReportRecord>(), "{}", "paused"));
            Assert(!view.HasPauseReport && view.ReportBadgeText == "0份");
            Assert(view.LastReportSummary == "暂无历史错误报告" && view.LastReportTime == "—");
        });
        Case("percentages_use_compact_one_decimal_format", () =>
        {
            var percentSnapshot = Snapshot(Array.Empty<ErrorReportRecord>(), "{}");
            percentSnapshot.Scopes["random"].Total = new BattleSummary { Total = 100, Wins = 22, Losses = 70, Draws = 5, Unknown = 3, WinRate = 0.22 };
            percentSnapshot.Scopes["random"].Versions[0].WinRate = 0.22;
            var view = new DesktopViewModel(FixtureRoot, false); view.Apply(percentSnapshot);
            Assert(view.WinRate == "22.0%" && view.RecentRate == "25.0%" && view.Versions.Single().Rate == "22.0%");
        });
        Case("recent_battles_preserve_latest_ten_rows", () =>
        {
            var recentSnapshot = Snapshot(Array.Empty<ErrorReportRecord>(), "{}");
            recentSnapshot.Scopes["random"].Records = Enumerable.Range(1, 12).Reverse().Select(index => Battle("胜利", index)).ToList();
            var view = new DesktopViewModel(FixtureRoot, false); view.Apply(recentSnapshot);
            Assert(view.RecentBattles.Count == 10 && view.RecentBattles.First().Battle == 12 && view.RecentBattles.Last().Battle == 3);
            Assert(view.Total == "4" && view.WinRate == "25.0%", "展示行数不能改写后端统计口径");
        });
        Case("polish_binding_notifications_update_after_refresh", () =>
        {
            var view = new DesktopViewModel(RequestFixture("notifications", "导航校准"), false);
            var changed = new HashSet<string>();
            view.PropertyChanged += (_, args) => { if (args.PropertyName is not null) changed.Add(args.PropertyName); };
            view.Apply(Snapshot(new[] { latest, old }, "{}", "stopped"));
            foreach (string property in new[] { "HasStopRequest", "HasCalibrationRequest", "CanStart", "StartHint", "HasPauseReport", "ReportBadgeText", "LastReportSummary", "LastReportTime" })
                Assert(changed.Contains(property), "未通知绑定：" + property);
        });
        Case("preview_preserves_calibration_description_without_controls", () =>
        {
            var view = new DesktopViewModel(RequestFixture("preview", "navigation calibration"), true);
            view.Apply(Snapshot(Array.Empty<ErrorReportRecord>(), "{}", "stopped"));
            Assert(view.HasCalibrationRequest && !view.CanStart && !view.CanStop);
            Assert(view.PhaseDescription.StartsWith("只读预览", StringComparison.Ordinal) && view.PhaseDescription.Contains("不会自动恢复", StringComparison.Ordinal));
        });
        Case("production_calibration_request_is_read_only", () =>
        {
            const string dataRoot = @"D:\codex\CodexWork\clash";
            string path = RequestPath(dataRoot);
            Assert(File.Exists(path), "本轮明确保留的生产请求应仍存在");
            byte[] before = SHA256.HashData(File.ReadAllBytes(path)); DateTime written = File.GetLastWriteTimeUtc(path);
            var view = new DesktopViewModel(dataRoot, false);
            view.Apply(Snapshot(Array.Empty<ErrorReportRecord>(), "{}", "stopped"));
            Assert(view.HasCalibrationRequest && !view.CanStart);
            Assert(SHA256.HashData(File.ReadAllBytes(path)).SequenceEqual(before) && File.GetLastWriteTimeUtc(path) == written);
        });
        Case("start_entry_rechecks_new_drain_before_next_snapshot", () =>
        {
            string root = Path.Combine(FixtureRoot, "entry-guard-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            var view = new DesktopViewModel(root, false);
            view.Apply(Snapshot(Array.Empty<ErrorReportRecord>(), "{}", "stopped"));
            Assert(view.CanStart && !view.HasStopRequest);
            var changed = new HashSet<string>();
            view.PropertyChanged += (_, args) => { if (args.PropertyName is not null) changed.Add(args.PropertyName); };
            string path = RequestPath(root); Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            File.WriteAllText(path, "Finish this cycle, then pause for navigation calibration.");
            byte[] original = File.ReadAllBytes(path); DateTime written = File.GetLastWriteTimeUtc(path);
            // There is deliberately no Apply() between the file appearing
            // and the same synchronous guard used by the Start command.
            view.RefreshStopRequest();
            Assert(!view.CanStart && view.HasStopRequest && view.HasCalibrationRequest);
            Assert(view.Phase == "任务已停止 · 等待导航校准" && view.StartHint.Contains("导航校准", StringComparison.Ordinal));
            foreach (string property in new[] { "CanStart", "StartHint", "HasStopRequest", "HasCalibrationRequest", "StopRequestReadError", "Phase", "PhaseDescription", "StateColor", "StateBackground" })
                Assert(changed.Contains(property), "入口检查未通知绑定：" + property);
            Assert(File.ReadAllBytes(path).SequenceEqual(original) && File.GetLastWriteTimeUtc(path) == written);
        });
        Case("damaged_historical_log_text_is_preserved_with_clear_notice", () =>
        {
            var view = new DesktopViewModel(FixtureRoot, false);
            var logs = Snapshot(Array.Empty<ErrorReportRecord>(), "{}");
            logs.RecentEvents = new List<string> { "正常原始事件", "历史事件包含\uFFFD损坏字符" };
            var changed = new HashSet<string>();
            view.PropertyChanged += (_, args) => { if (args.PropertyName is not null) changed.Add(args.PropertyName); };
            view.Apply(logs);
            Assert(view.LogText == string.Join(Environment.NewLine, logs.RecentEvents));
            Assert(view.LogNotice == "部分历史日志文字无法正常显示，原始记录仍保留。");
            Assert(changed.Contains("LogNotice"));
            logs.RecentEvents = new List<string> { "文字显示正常的新快照" }; view.Apply(logs);
            Assert(view.LogNotice == "" && view.LogText == "文字显示正常的新快照");
        });
        Case("request_stop_warning_palette_keeps_pause_red_and_normal_stop_gray", () =>
        {
            var requested = new DesktopViewModel(RequestFixture("palette-calibration", "navigation calibration"), false);
            requested.Apply(Snapshot(Array.Empty<ErrorReportRecord>(), "{}", "stopped"));
            Assert(((SolidColorBrush)requested.StateColor).Color == Color.FromRgb(0xB6, 0x81, 0x21));
            Assert(((SolidColorBrush)requested.StateBackground).Color == Color.FromRgb(0xFF, 0xF6, 0xDF));
            requested.Apply(Snapshot(Array.Empty<ErrorReportRecord>(), "{}", "paused"));
            Assert(((SolidColorBrush)requested.StateColor).Color == Color.FromRgb(0xBF, 0x5B, 0x68));
            Assert(((SolidColorBrush)requested.StateBackground).Color == Color.FromRgb(0xFC, 0xEC, 0xEE));
            var unknown = new DesktopViewModel(RequestFixture("palette-other", "manual maintenance stop"), false);
            unknown.Apply(Snapshot(Array.Empty<ErrorReportRecord>(), "{}", "stopped"));
            Assert(!unknown.HasCalibrationRequest && ((SolidColorBrush)unknown.StateColor).Color == Color.FromRgb(0xB6, 0x81, 0x21));
            var ordinary = new DesktopViewModel(FixtureRoot, false);
            ordinary.Apply(Snapshot(Array.Empty<ErrorReportRecord>(), "{}", "stopped"));
            Assert(((SolidColorBrush)ordinary.StateColor).Color == Color.FromRgb(0x75, 0x82, 0x9B));
            Assert(((SolidColorBrush)ordinary.StateBackground).Color == Color.FromRgb(0xED, 0xF1, 0xF7));
        });
        Case("busy_hero_tracks_commands_and_restores_latest_snapshot", () =>
        {
            var view = new DesktopViewModel(FixtureRoot, false);
            view.Apply(Snapshot(Array.Empty<ErrorReportRecord>(), "{}", "stopped"));
            view.SetBusy("start");
            Assert(view.IsBusy && view.Phase == "正在启动任务" && view.PhaseDescription.Contains("连接", StringComparison.Ordinal));
            Assert(!view.CanStart && !view.CanStop);
            view.Apply(Snapshot(Array.Empty<ErrorReportRecord>(), "{\"state\":\"battle\"}"));
            Assert(view.Phase == "正在启动任务", "刷新真实快照不能盖掉仍在进行的启动操作");
            view.SetBusy(""); Assert(!view.IsBusy && view.Phase == "随机卡组对战中" && view.CanStop);
            view.SetBusy("stop"); Assert(view.Phase == "正在停止任务" && view.PhaseDescription.Contains("正在停止", StringComparison.Ordinal));
            view.Apply(Snapshot(Array.Empty<ErrorReportRecord>(), "{}", "stopped"));
            Assert(view.Phase == "正在停止任务");
            view.SetBusy(""); Assert(view.Phase == "任务已停止" && view.CanStart);
        });
        Case("busy_stop_completion_restores_retained_calibration_request", () =>
        {
            string root = RequestFixture("busy-restored", "navigation calibration");
            string path = RequestPath(root); byte[] contents = File.ReadAllBytes(path);
            var view = new DesktopViewModel(root, false);
            view.Apply(Snapshot(Array.Empty<ErrorReportRecord>(), "{\"state\":\"mastery\"}"));
            view.SetBusy("stop"); Assert(view.Phase == "正在停止任务");
            view.Apply(Snapshot(Array.Empty<ErrorReportRecord>(), "{}", "stopped"));
            view.SetBusy("");
            Assert(view.Phase == "任务已停止 · 等待导航校准" && !view.CanStart);
            Assert(view.PhaseDescription.Contains("不会自动恢复", StringComparison.Ordinal));
            Assert(File.ReadAllBytes(path).SequenceEqual(contents));
        });
        Case("busy_can_render_before_initial_snapshot", () =>
        {
            var view = new DesktopViewModel(FixtureRoot, false);
            view.SetBusy("start"); Assert(view.Phase == "正在启动任务");
            view.SetBusy(""); Assert(view.Phase == "正在读取状态" && !view.CanStart);
        });
        Case("current_pause_reason_uses_matching_session_not_latest_history", () =>
        {
            var view = new DesktopViewModel(FixtureRoot, false);
            view.Apply(Snapshot(new[] { latest, old }, "{\"session\":\"fixture-session-old\"}", "paused"));
            Assert(view.HasPauseReport && view.CurrentPauseReport?.Record.EventId == "old");
            Assert(view.PhaseDescription == old.Reason && view.LastReportSummary == latest.Reason);
            Assert(view.Reports.Count == 2, "关联当前暂停不能丢弃其他历史报告");
            view.Apply(Snapshot(new[] { latest, old }, "{\"session\":\"fixture-session-old\"}", "running"));
            Assert(!view.HasPauseReport && view.CurrentPauseReport is null);
        });
        Case("pending_report_is_not_current_until_saved_and_notifies_bindings", () =>
        {
            var view = new DesktopViewModel(FixtureRoot, false);
            var pending = Snapshot(new[] { latest, old }, "{\"session\":\"fixture-session-old\"}", "paused");
            pending.ErrorReportPending = true; view.Apply(pending);
            Assert(!view.HasPauseReport && view.CurrentPauseReport is null && view.PhaseDescription.Contains("生成中", StringComparison.Ordinal));
            Assert(!view.PhaseDescription.Contains(old.Reason, StringComparison.Ordinal));
            view.SelectedReport = view.Reports.Single(row => row.Record.EventId == "old");
            var changed = new HashSet<string>();
            view.PropertyChanged += (_, args) => { if (args.PropertyName is not null) changed.Add(args.PropertyName); };
            pending.ErrorReportPending = false; view.Apply(pending);
            Assert(view.HasPauseReport && view.CurrentPauseReport?.Record.EventId == "old" && view.PhaseDescription == old.Reason);
            Assert(view.SelectedReport?.Record.EventId == "old" && view.Reports.Count == 2);
            Assert(changed.Contains("CurrentPauseReport") && changed.Contains("HasPauseReport") && changed.Contains("PhaseDescription"));
        });
        Case("missing_or_unmatched_pause_session_never_borrows_history_reason", () =>
        {
            var view = new DesktopViewModel(FixtureRoot, false);
            foreach (string live in new[] { "{\"session\":\"unknown-current-session\"}", "{}" })
            {
                view.Apply(Snapshot(new[] { latest, old }, live, "paused"));
                Assert(!view.HasPauseReport && view.CurrentPauseReport is null && view.Reports.Count == 2);
                Assert(view.PhaseDescription.Contains("尚未保存", StringComparison.Ordinal));
                Assert(!view.PhaseDescription.Contains(latest.Reason, StringComparison.Ordinal) && !view.PhaseDescription.Contains(old.Reason, StringComparison.Ordinal));
            }
        });
        Case("new_matching_pause_report_preserves_old_selection_and_updates_reason", () =>
        {
            var view = new DesktopViewModel(FixtureRoot, false);
            const string currentLive = "{\"session\":\"fixture-session-current-pause\"}";
            view.Apply(Snapshot(new[] { latest, old }, currentLive, "paused"));
            view.SelectedReport = view.Reports.Single(row => row.Record.EventId == "old");
            Assert(!view.HasPauseReport);
            ErrorReportRecord current = Report("current-pause", "2026-10-04T18:10:00+08:00", "当前会话的明确暂停原因", 77);
            view.Apply(Snapshot(new[] { current, latest, old }, currentLive, "paused"));
            Assert(view.HasPauseReport && view.CurrentPauseReport?.Record.EventId == "current-pause");
            Assert(view.PhaseDescription == current.Reason && view.SelectedReport?.Record.EventId == "old" && view.Reports.Count == 3);
        });
        Case("legacy_report_runtime_session_can_be_exactly_matched", () =>
        {
            ErrorReportRecord legacy = Report("runtime-only", "2026-10-04T18:15:00+08:00", "旧报告保留的运行会话原因", 65);
            legacy.Session = null;
            var view = new DesktopViewModel(FixtureRoot, false);
            view.Apply(Snapshot(new[] { latest, legacy }, "{\"session\":\"fixture-session-runtime-only\"}", "paused"));
            Assert(view.HasPauseReport && view.CurrentPauseReport?.Record.EventId == "runtime-only" && view.PhaseDescription == legacy.Reason);
        });
        Case("pause_report_status_is_not_overwritten_by_drain_read_error", () =>
        {
            string root = RequestFixture("pause-locked", "navigation calibration");
            using var exclusive = new FileStream(RequestPath(root), FileMode.Open, FileAccess.ReadWrite, FileShare.None);
            var view = new DesktopViewModel(root, false);
            var pause = Snapshot(new[] { latest, old }, "{\"session\":\"fixture-session-latest\"}", "paused");
            view.Apply(pause);
            Assert(view.HasPauseReport && view.PhaseDescription == latest.Reason);
            Assert(view.StopRequestReadError.Length > 0 && !view.CanStart);
            pause.ErrorReportPending = true; view.Apply(pause);
            Assert(!view.HasPauseReport && view.PhaseDescription.Contains("生成中", StringComparison.Ordinal));
        });
        var result = new { status = Failed == 0 ? "ok" : "failed", count = Results.Count, failed = Failed,
            cases = Results, fixture_root = FixtureRoot, ui_created = false, bot_started_or_stopped = false };
        string json = JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = true });
        File.WriteAllText(Path.Combine(ProjectRoot, "result.json"), json);
        Console.WriteLine(json);
        Environment.ExitCode = Failed == 0 ? 0 : 1;
    }

    private static void Case(string name, Action run)
    {
        try { run(); Results.Add(new { name, passed = true }); }
        catch (Exception error) { Failed++; Results.Add(new { name, passed = false, error = error.GetType().Name + ": " + error.Message, stack = error.StackTrace }); }
    }
    private static void Assert(bool value, string message = "fixture期望未满足")
    { if (!value) throw new InvalidOperationException(message); }
    private static string RequestPath(string dataRoot) => Path.Combine(dataRoot, "work", "random-mastery", "DRAIN");
    private static string RequestFixture(string name, string content)
    {
        string root = Path.Combine(FixtureRoot, "request-" + name + "-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(Path.GetDirectoryName(RequestPath(root))!);
        File.WriteAllText(RequestPath(root), content);
        return root;
    }

    private static ErrorReportRecord Report(string id, string stamp, string reason, byte color)
    {
        string folder = Path.Combine(FixtureRoot, "outputs", "error-reports", id);
        Directory.CreateDirectory(folder);
        string markdown = Path.Combine(folder, "report.md"), png = Path.Combine(folder, "game.png");
        File.WriteAllText(markdown, "# 任务专属测试报告\n" + reason);
        byte[] pixels = { color, 80, 120, 255, color, 80, 120, 255, color, 80, 120, 255, color, 80, 120, 255 };
        var image = BitmapSource.Create(2, 2, 96, 96, PixelFormats.Bgra32, null, pixels, 8);
        image.Freeze(); var encoder = new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create(image));
        using (var stream = File.Create(png)) encoder.Save(stream);
        return new ErrorReportRecord { EventId = id, CreatedAt = stamp, Reason = reason, ReportDir = folder, ReportMd = markdown,
            GamePng = png, ScreenshotStatus = "captured", Session = "fixture-session-" + id, Runtime = JsonSerializer.SerializeToElement(new { session = "fixture-session-" + id }) };
    }
    private static ConsoleSnapshot Snapshot(IEnumerable<ErrorReportRecord> reports, string live, string state = "running")
    {
        var history = new HistorySnapshot { FirstAt = "2026-10-03 09:00:00", Total = new BattleSummary { Total = 4, Wins = 1, Losses = 1, Unknown = 1, Draws = 1, WinRate = 0.25 },
            Recent = new BattleSummary { Total = 4, Wins = 1, Losses = 1, Unknown = 1, Draws = 1, WinRate = 0.25 },
            Records = new List<BattleRecord> { Battle("胜利", 4), Battle("失败", 3), Battle("未知", 2), Battle("平局", 1) },
            RecentResults = new List<string> { "平局", "未知", "失败", "胜利" },
            Versions = new List<StrategyVersion> { new() { Total = 4, Wins = 1, Losses = 1, Unknown = 1, Draws = 1, WinRate = 0.25, Policy = "random-mastery-v2-fixture" } } };
        var all = new HistorySnapshot { Total = history.Total, Records = history.Records.Concat(new[] { Battle("胜利", 10) }).ToList() };
        using var document = JsonDocument.Parse(live);
        return new ConsoleSnapshot { State = state, Live = document.RootElement.Clone(), UpdatedAt = "2026-10-04T16:00:00+08:00", Reports = reports.ToList(),
            Scopes = new Dictionary<string, HistorySnapshot> { ["random"] = history, ["all"] = all },
            RewardTotals = new RewardTotals { Rewards = 5, Coins = 1234 }, Runtime = new RuntimeSnapshot { DataRoot = FixtureRoot } };
    }
    private static BattleRecord Battle(string result, int count) => new() { Strategy = "random", Session = "fixture", Battle = count,
        Time = "2026-10-04 14:00:00", Result = result, Confirmed = 12, Attempts = 15, Policy = "random-mastery-v2-fixture" };
}
