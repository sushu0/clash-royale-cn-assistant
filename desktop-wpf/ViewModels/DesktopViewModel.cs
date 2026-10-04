using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using ClashAssistant.Desktop.Models;

namespace ClashAssistant.Desktop.ViewModels;

public sealed class DesktopViewModel : INotifyPropertyChanged
{
    public event PropertyChangedEventHandler? PropertyChanged;
    private readonly string _dataRoot;
    private readonly bool _preview;
    private ConsoleSnapshot? _snapshot;
    private string _state = "connecting", _busy = "", _notice = "正在连接本机任务…", _updated = "";
    private string _phase = "正在读取状态", _description = "连接后可查看战绩和任务进展。", _session = "", _deployments = "", _decision = "";
    private string _total = "—", _wins = "—", _losses = "—", _rate = "—", _recent = "—", _totalNote = "", _recentNote = "";
    private string _coins = "—", _rewards = "—", _historyNote = "", _logs = "", _logNotice = "", _scope = "random", _emulator = "等待连接";
    private int _page;
    private string _battleSignature = "", _versionSignature = "", _reportSignature = "", _chipSignature = "";
    private ErrorRow? _selectedReport;
    private ImageSource? _reportImage;
    private string _reportText = "", _imageNote = "选择报告查看当时保存的游戏画面。";
    private bool _hasStopRequest, _hasCalibrationRequest, _stateConfirmed, _backendBusyConfirmed;
    private string _stopRequestReadError = "";
    public DesktopViewModel(string dataRoot, bool preview) { _dataRoot = dataRoot; _preview = preview; }
    private void Set<T>(ref T field, T value, [CallerMemberName] string? name = null)
    { if (EqualityComparer<T>.Default.Equals(field, value)) return; field = value; Changed(name); }
    private void Changed(string? name) => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
    private static Brush Color(string value) { var brush = (SolidColorBrush)new BrushConverter().ConvertFromString(value)!; brush.Freeze(); return brush; }
    private string BusyCommand => _busy.Length > 0 ? _busy : _backendBusyConfirmed ? _snapshot?.Busy ?? "" : "";
    public bool IsBusy => BusyCommand.Length > 0;
    public string State => _state;
    public bool StateConfirmed => _stateConfirmed;
    public bool CanStart => !_preview && !IsBusy && string.IsNullOrEmpty(_snapshot?.Busy) && StateConfirmed && !HasStopRequest && _snapshot is not null && (_state == "stopped" || _state == "paused");
    public bool CanStop => !_preview && BusyCommand != "stop" && (BusyCommand == "start" || _state is "running" or "starting" or "stopping" || (!StateConfirmed && _snapshot is not null));
    public bool HasStopRequest => _hasStopRequest;
    public bool HasCalibrationRequest => _hasCalibrationRequest;
    public ErrorRow? CurrentPauseReport
    {
        get
        {
            if (_state != "paused" || _snapshot is null || _snapshot.ErrorReportPending) return null;
            string session = Text(_snapshot.Live, "session");
            if (string.IsNullOrWhiteSpace(session)) return null;
            return Reports.FirstOrDefault(row => string.Equals(
                string.IsNullOrWhiteSpace(row.Record.Session) ? Text(row.Record.Runtime, "session") : row.Record.Session,
                session, StringComparison.Ordinal));
        }
    }
    public bool HasPauseReport => CurrentPauseReport is not null;
    public string StopRequestReadError => _stopRequestReadError;
    public string StartHint => _stopRequestReadError.Length > 0 ? _stopRequestReadError
        : HasCalibrationRequest ? "导航校准请求已保留；完成校准并确认请求处理后，再手动开始。"
        : HasStopRequest ? "停止请求已保留；确认请求原因并处理后，再手动开始。"
        : _preview ? "当前为只读预览，开始与停止操作不可用。"
        : IsBusy ? "请等待当前操作完成。"
        : !StateConfirmed ? "正在确认任务是否已停止，确认前不能重新启动。"
        : _snapshot is null ? "正在确认本机任务状态。"
        : _state is "running" or "starting" ? "任务正在运行，可使用停止任务。"
        : _state == "paused" ? "请先查看暂停原因并处理，再手动开始。"
        : "点击开始运行，进入连续 1V1 对战。";
    public string StateLabel => IsBusy ? (BusyCommand == "start" ? "●  正在启动" : "●  正在停止") : !StateConfirmed && _snapshot is not null ? "●  状态待确认" : _state switch { "running" => "●  运行中", "starting" => "●  恢复中", "stopping" => "●  正在停止", "paused" => "●  已暂停", "stopped" => "●  已停止", _ => "●  连接中" };
    public Brush StateColor => Color(IsBusy || !StateConfirmed || _state is "starting" or "stopping" || (_state == "stopped" && HasStopRequest) ? "#B68121" : _state == "running" ? "#198C6E" : _state == "paused" ? "#BF5B68" : "#75829B");
    public Brush StateBackground => Color(IsBusy || !StateConfirmed || _state is "starting" or "stopping" || (_state == "stopped" && HasStopRequest) ? "#FFF6DF" : _state == "running" ? "#E6F5EF" : _state == "paused" ? "#FCECEE" : "#EDF1F7");
    public string Notice { get => _notice; set => Set(ref _notice, value); }
    public string UpdatedText { get => _updated; private set => Set(ref _updated, value); }
    public string Phase { get => _phase; private set => Set(ref _phase, value); }
    public string PhaseDescription { get => _description; private set => Set(ref _description, value); }
    public string SessionText { get => _session; private set => Set(ref _session, value); }
    public string DeploymentText { get => _deployments; private set => Set(ref _deployments, value); }
    public string DecisionText { get => _decision; private set => Set(ref _decision, value); }
    public string Total { get => _total; private set => Set(ref _total, value); }
    public string Wins { get => _wins; private set => Set(ref _wins, value); }
    public string Losses { get => _losses; private set => Set(ref _losses, value); }
    public string WinRate { get => _rate; private set => Set(ref _rate, value); }
    public string RecentRate { get => _recent; private set => Set(ref _recent, value); }
    public string TotalNote { get => _totalNote; private set => Set(ref _totalNote, value); }
    public string RecentNote { get => _recentNote; private set => Set(ref _recentNote, value); }
    public string Coins { get => _coins; private set => Set(ref _coins, value); }
    public string Rewards { get => _rewards; private set => Set(ref _rewards, value); }
    public string HistoryNote { get => _historyNote; private set => Set(ref _historyNote, value); }
    public string LogText { get => _logs; private set => Set(ref _logs, value); }
    public string LogNotice { get => _logNotice; private set => Set(ref _logNotice, value); }
    public string EmulatorStatus { get => _emulator; set => Set(ref _emulator, value); }
    public string PageTitle => new[] { "对战工作台", "对局记录", "策略统计", "错误报告", "运行日志" }[_page];
    public string PageSubtitle => new[] { "查看任务进展，让每一场对战有据可查", "已结算对局与对应的原始证据", "观察各策略版本的实际运行结果", "每次异常独立留档，历史原因与截图完整保留", "跟踪最近事件、出牌决策和运行提醒" }[_page];
    public void SelectPage(int value) { _page = Math.Clamp(value, 0, 4); Changed(nameof(PageTitle)); Changed(nameof(PageSubtitle)); }
    public ObservableCollection<BattleRow> Battles { get; } = new();
    public ObservableCollection<BattleRow> RecentBattles { get; } = new();
    public ObservableCollection<VersionRow> Versions { get; } = new();
    public ObservableCollection<ResultChip> ResultChips { get; } = new();
    public ObservableCollection<ErrorRow> Reports { get; } = new();
    public int ReportCount => Reports.Count;
    public string ReportCountText => $"历史错误报告 · 共 {Reports.Count} 份";
    public string ReportBadgeText => $"{Reports.Count}份";
    public string LastReportSummary => Reports.FirstOrDefault()?.Reason ?? "暂无历史错误报告";
    public string LastReportTime => Reports.FirstOrDefault()?.TimeLabel ?? "—";
    public ErrorRow? SelectedReport
    {
        get => _selectedReport;
        set
        {
            if (ReferenceEquals(_selectedReport, value)) return;
            _selectedReport = value;
            LoadReport();
            foreach (string key in new[] { nameof(SelectedReport), nameof(SelectedReportTitle), nameof(SelectedReportReason), nameof(SelectedReportMeta), nameof(HasSelectedReport), nameof(HasSelectedScreenshot), nameof(ReportImage), nameof(ReportText), nameof(ReportImageNote) }) Changed(key);
        }
    }
    public string SelectedReportTitle => SelectedReport is null ? "暂无错误报告" : "暂停详情";
    public string SelectedReportReason => SelectedReport?.Reason ?? "任务异常暂停后，会自动保留原因与游戏截图。";
    public string SelectedReportMeta => SelectedReport is null ? "" : $"{SelectedReport.TimeLabel}\n运行会话：{SelectedReport.Record.Session ?? "未记录"}";
    public bool HasSelectedReport => SelectedReport?.Record.ReportMd is string path && File.Exists(path);
    public bool HasSelectedScreenshot => SelectedReport?.Record.GamePng is string path && File.Exists(path);
    public ImageSource? ReportImage => _reportImage;
    public string ReportText => _reportText;
    public string ReportImageNote => _imageNote;

    public void SetBusy(string command)
    {
        _busy = command;
        if (command.Length > 0) { _stateConfirmed = false; _backendBusyConfirmed = false; }
        foreach (string key in new[] { nameof(IsBusy), nameof(StateConfirmed), nameof(CanStart), nameof(CanStop), nameof(StartHint), nameof(StateLabel), nameof(StateColor), nameof(StateBackground) }) Changed(key);
        RefreshStopRequest();
    }

    public void MarkStateUnconfirmed()
    {
        _stateConfirmed = false;
        _backendBusyConfirmed = false;
        foreach (string key in new[] { nameof(IsBusy), nameof(StateConfirmed), nameof(CanStart), nameof(CanStop), nameof(StartHint), nameof(StateLabel), nameof(StateColor), nameof(StateBackground) }) Changed(key);
        UpdatePhase(_snapshot);
    }

    public void RefreshStopRequest()
    {
        ReadStopRequest();
        foreach (string key in new[] { nameof(CanStart), nameof(HasStopRequest), nameof(HasCalibrationRequest), nameof(StartHint), nameof(StopRequestReadError), nameof(StateColor), nameof(StateBackground) }) Changed(key);
        UpdatePhase(_snapshot);
    }

    private void UpdatePhase(ConsoleSnapshot? snapshot)
    {
        if (IsBusy)
        {
            Phase = BusyCommand == "start" ? "正在启动任务" : "正在停止任务";
            PhaseDescription = BusyCommand == "start" ? "正在检查本机连接和游戏启动条件，准备开始任务，请稍候。" : "正在停止后台对战任务，请稍候。";
            return;
        }
        if (snapshot is null)
        {
            Phase = "正在读取状态";
            PhaseDescription = "连接后可查看战绩和任务进展。";
            return;
        }
        if (!StateConfirmed)
        {
            Phase = "正在确认任务状态";
            PhaseDescription = "正在核实后台任务是否仍在运行；确认前暂停开始操作，可再次发送停止请求。";
            return;
        }
        string phase = Text(snapshot.Live, "state");
        Phase = _state switch
        {
            "running" => phase switch { "generating_deck" => "正在生成随机卡组", "matching" => "正在匹配经典 1V1", "returning" => "正在完成结算", "mastery" => "正在检查奖励", _ => "随机卡组对战中" },
            "starting" => "正在连接与恢复", "stopping" => "正在停止任务", "paused" => "任务已暂停",
            "stopped" => HasCalibrationRequest ? "任务已停止 · 等待导航校准" : HasStopRequest ? "任务已停止 · 保留停止请求" : "任务已停止", _ => "正在连接任务"
        };
        PhaseDescription = _state == "paused" ? snapshot.ErrorReportPending ? "本次暂停错误报告生成中，原因与截图保存完成后可查看。"
            : CurrentPauseReport is ErrorRow report ? report.Reason.Length > 0 ? report.Reason : "本次暂停报告已保存，请查看详情。"
            : "本次暂停报告尚未保存或未关联当前会话；历史报告继续保留，请查看运行日志。"
            : _state == "stopped" && HasCalibrationRequest ? "导航校准请求已保留，任务不会自动恢复。完成导航校准并确认请求处理后，再手动开始。"
            : _state == "stopped" && HasStopRequest ? "停止请求已保留，原因尚未确认；任务不会自动恢复。确认并处理请求后，再手动开始。"
            : _state == "stopped" ? "任务已停止，点击开始运行可手动进入连续 1V1 对战。"
            : _state == "stopping" ? "停止请求已接收，正在确认执行进程与看门狗全部退出；此时不能开始新任务。"
            : HasCalibrationRequest ? "已收到导航校准请求，完成当前对战与奖励循环后暂停；请求会继续保留，不会自动恢复。"
            : HasStopRequest ? "已收到停止请求，将完成当前循环后暂停；请求内容已保留。"
            : "自动换卡组、出牌、结算并检查奖励，持续进入下一场。";
        if (_stopRequestReadError.Length > 0 && _state != "paused") PhaseDescription = _stopRequestReadError;
        if (_preview) PhaseDescription = "只读预览 · " + PhaseDescription;
    }

    public void Apply(ConsoleSnapshot snapshot)
    {
        _snapshot = snapshot;
        _state = snapshot.State;
        _backendBusyConfirmed = true;
        _stateConfirmed = !IsBusy;
        Changed(nameof(StateConfirmed));
        RefreshStopRequest();
        foreach (string key in new[] { nameof(State), nameof(IsBusy), nameof(CanStop), nameof(StateLabel), nameof(StateColor), nameof(StateBackground) }) Changed(key);
        SessionText = (_state is "running" or "starting" ? "当前会话：" : "最近会话：") + (Text(snapshot.Live, "session") is { Length: > 0 } session ? session : "等待开始");
        int? confirmed = Number(snapshot.Live, "cards_confirmed");
        DeploymentText = confirmed.HasValue ? $"{(_state is "running" or "starting" ? "本局" : "上局")}已确认出牌 {confirmed.Value} 次" : "等待本局出牌记录";
        DecisionText = Text(snapshot.Live, "decision_reason");
        UpdatedText = "已同步 " + (DateTimeOffset.TryParse(snapshot.UpdatedAt, out var stamp) ? stamp.ToString("HH:mm:ss") : snapshot.UpdatedAt);
        if (snapshot.HistoryError is { Length: > 0 }) Notice = "战绩读取提醒：" + snapshot.HistoryError;
        Rewards = snapshot.RewardTotals.Rewards.ToString("N0");
        Coins = snapshot.RewardTotals.Coins.ToString("N0") + (snapshot.RewardTotals.UnknownCoinItems > 0 ? "+" : "");
        LogText = string.Join(Environment.NewLine, snapshot.RecentEvents);
        LogNotice = LogText.Contains('\uFFFD') ? "部分历史日志文字无法正常显示，原始记录仍保留。" : "";
        ApplyHistory();
        string reports = JsonSerializer.Serialize(snapshot.Reports);
        if (reports != _reportSignature)
        {
            _reportSignature = reports;
            string? old = SelectedReport?.Record.ReportDir;
            Reports.Clear();
            foreach (var row in snapshot.Reports) Reports.Add(new ErrorRow(row));
            SelectedReport = Reports.FirstOrDefault(row => row.Record.ReportDir == old) ?? Reports.FirstOrDefault();
            Changed(nameof(ReportCount)); Changed(nameof(ReportCountText)); Changed(nameof(ReportBadgeText));
            Changed(nameof(LastReportSummary)); Changed(nameof(LastReportTime));
        }
        Changed(nameof(CurrentPauseReport)); Changed(nameof(HasPauseReport));
        // New or completed reports can arrive without another state change.
        // Recompute the paused explanation only after the report rows update.
        UpdatePhase(snapshot);
    }

    private void ReadStopRequest()
    {
        _hasStopRequest = false; _hasCalibrationRequest = false; _stopRequestReadError = "";
        string path = Path.Combine(_dataRoot, "work", "random-mastery", "DRAIN");
        try
        {
            FileAttributes attributes = File.GetAttributes(path);
            _hasStopRequest = true;
            if ((attributes & (FileAttributes.Directory | FileAttributes.ReparsePoint)) != 0)
            {
                _stopRequestReadError = "停止请求暂时无法确认，已保留请求并暂停开始操作；请检查本机请求文件。";
                return;
            }
            using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
            using var reader = new StreamReader(stream, Encoding.UTF8, true);
            char[] buffer = new char[4096];
            int count = reader.ReadBlock(buffer, 0, buffer.Length);
            string content = new(buffer, 0, count);
            _hasCalibrationRequest = Regex.IsMatch(content, @"\bnavigation\s+calibration\b", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)
                || content.Contains("导航校准", StringComparison.Ordinal);
        }
        catch (FileNotFoundException) { }
        catch (DirectoryNotFoundException) { }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            // An unreadable stop request cannot become permission to restart.
            _hasStopRequest = true;
            _stopRequestReadError = "停止请求暂时无法读取，已保留请求并暂停开始操作；请稍后重试。";
        }
    }

    public void SelectScope(string value) { _scope = value; _battleSignature = ""; _versionSignature = ""; ApplyHistory(); }
    private void ApplyHistory()
    {
        if (_snapshot is null) return;
        var main = _snapshot.Scopes.GetValueOrDefault("random") ?? new HistorySnapshot();
        Total = main.Total.Total.ToString("N0"); Wins = main.Total.Wins.ToString("N0"); Losses = main.Total.Losses.ToString("N0");
        WinRate = Rate(main.Total.WinRate); RecentRate = Rate(main.Recent.WinRate);
        TotalNote = $"未知 {main.Total.Unknown} · 平局 {main.Total.Draws}";
        RecentNote = $"{main.Recent.Wins} 胜 / {main.Recent.Total} 局";
        var selected = _snapshot.Scopes.GetValueOrDefault(_scope) ?? main;
        HistoryNote = $"{selected.FirstAt?.Split(' ')[0] ?? "—"} 起 · 胜率包含未知和平局 · 未结算不计入" + (selected.Conflicts > 0 ? $" · 冲突 {selected.Conflicts}" : "");
        string battles = JsonSerializer.Serialize(selected.Records);
        if (battles != _battleSignature)
        {
            _battleSignature = battles; Battles.Clear();
            foreach (var row in selected.Records) Battles.Add(new BattleRow(row));
        }
        var recent = main.Records.Take(10).Select(row => new BattleRow(row)).ToArray();
        if (JsonSerializer.Serialize(recent.Select(row => row.Record)) != JsonSerializer.Serialize(RecentBattles.Select(row => row.Record)))
        { RecentBattles.Clear(); foreach (var row in recent) RecentBattles.Add(row); }
        string versions = JsonSerializer.Serialize(selected.Versions);
        if (versions != _versionSignature)
        { _versionSignature = versions; Versions.Clear(); foreach (var row in selected.Versions) Versions.Add(new VersionRow(row)); }
        string chips = string.Join("|", main.RecentResults);
        if (chips != _chipSignature || ResultChips.Count == 0)
        {
            _chipSignature = chips; ResultChips.Clear();
            foreach (var result in Enumerable.Repeat("", Math.Max(0, 20 - main.RecentResults.Count)).Concat(main.RecentResults.TakeLast(20)))
                ResultChips.Add(new ResultChip(result == "胜利" ? "胜" : result == "失败" ? "负" : result == "平局" ? "平" : result == "未知" ? "?" : "·", Color(result == "胜利" ? "#E5F5EF" : result == "失败" ? "#F9EDEF" : "#EFF2F8"), Color(result == "胜利" ? "#219574" : result == "失败" ? "#C96B75" : "#9BA8BD")));
        }
    }

    private void LoadReport()
    {
        _reportImage = null; _reportText = ""; _imageNote = "本次没有可用截图，文本报告仍保留。";
        if (SelectedReport is null) return;
        try
        {
            string? markdown = LocalEvidence(SelectedReport.Record.ReportMd, Path.Combine(_dataRoot, "outputs", "error-reports"), ".md");
            if (markdown is not null && new FileInfo(markdown).Length <= 4 * 1024 * 1024) _reportText = File.ReadAllText(markdown);
            string? picture = LocalEvidence(SelectedReport.Record.GamePng, Path.Combine(_dataRoot, "outputs", "error-reports"), ".png");
            if (picture is not null && new FileInfo(picture).Length <= 12 * 1024 * 1024)
            {
                using var stream = File.OpenRead(picture);
                var image = new BitmapImage(); image.BeginInit(); image.CacheOption = BitmapCacheOption.OnLoad; image.DecodePixelWidth = 440; image.StreamSource = stream; image.EndInit(); image.Freeze();
                _reportImage = image; _imageNote = "暂停当时自动保存的原始游戏截图";
            }
        }
        catch (Exception error) { _imageNote = "报告资源读取失败：" + error.Message; }
    }

    public static string? LocalEvidence(string? value, string root, string extension)
    {
        if (string.IsNullOrWhiteSpace(value)) return null;
        string path = Path.GetFullPath(value), boundary = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        if (!path.StartsWith(boundary, StringComparison.OrdinalIgnoreCase) || !path.EndsWith(extension, StringComparison.OrdinalIgnoreCase) || !File.Exists(path)) return null;
        for (string? current = path; current is not null && current.Length >= boundary.Length - 1; current = Path.GetDirectoryName(current))
            if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0) return null;
        return path;
    }

    internal static string Text(JsonElement value, string key) => value.ValueKind == JsonValueKind.Object && value.TryGetProperty(key, out var field) ? field.ValueKind == JsonValueKind.String ? field.GetString() ?? "" : field.ToString() : "";
    internal static int? Number(JsonElement value, string key) => value.ValueKind == JsonValueKind.Object && value.TryGetProperty(key, out var field) && field.ValueKind == JsonValueKind.Number && field.TryGetInt32(out int number) ? number : null;
    internal static string Rate(double? value) => value.HasValue ? (value.Value * 100).ToString("F1", CultureInfo.InvariantCulture) + "%" : "—";
    internal static string Policy(string? value)
    {
        if (value is null) return "未记录版本";
        var version = Regex.Match(value, @"-v(\d+)");
        return value.StartsWith("random-mastery", StringComparison.Ordinal) ? "随机卡组 · 领奖" + (version.Success ? " · v" + version.Groups[1].Value : "") : value;
    }
}

public sealed record ResultChip(string Text, Brush Background, Brush Foreground);
public sealed record BattleRow(BattleRecord Record)
{
    public string Time => Record.Time.Length > 5 ? Record.Time[5..] : Record.Time;
    public string Result => Record.Result;
    public int Battle => Record.Battle;
    public string Deployment => Record.Attempts.HasValue ? $"{Record.Confirmed ?? 0}/{Record.Attempts}" : "—";
    public string PolicyLabel => DesktopViewModel.Policy(Record.Policy);
    public string EvidenceStatus => Record.EvidenceStatus;
}
public sealed record VersionRow(StrategyVersion Record)
{
    public string Label => DesktopViewModel.Policy(Record.Policy) + (Record.StrategyHash is { Length: >= 8 } hash ? " · " + hash[..8] : " · 来源未记录");
    public int Total => Record.Total;
    public int Wins => Record.Wins;
    public int Losses => Record.Losses;
    public string Other => $"{Record.Draws} / {Record.Unknown}";
    public string Rate => DesktopViewModel.Rate(Record.WinRate);
}
public sealed record ErrorRow(ErrorReportRecord Record)
{
    public string TimeLabel => Record.DisplayTime.Replace('T', ' ')[..Math.Min(19, Record.DisplayTime.Length)];
    public string Reason => Record.Reason;
    public string ScreenshotLabel => Record.GamePng is not null ? "● 已保存原始截图" : Record.ScreenshotStatus == "pending" ? "截图采集中" : "截图不可用 · 文本记录保留";
}
