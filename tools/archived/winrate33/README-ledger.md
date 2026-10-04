# 固定 100 场只读取证 Ledger

`trial_ledger.py` 只读取生产 trace、运行 manifest、源码和资产哈希；只写自己的 `work/winrate33/<trial>` 目录。它不启动、停止或操作机器人。

## 启动

在 `D:\codex\CodexWork\clash` 工作目录中执行。必须在看到新会话 `batch_start` 后、首个 fresh `battle_start` 之前立即创建 ledger。请在同一个启动脚本中完成，避免模型往返延迟。首次会话应从大厅开始；没有可归属 OPEN slot 的 resumed 会触发 HOLD。

```powershell
$trialSession = '替换为实际trace会话ID'
& 'work\venv\Scripts\python.exe' -u 'work\winrate33\trial_ledger.py' `
  --first-session $trialSession `
  --trial-dir "work\winrate33\trials\$trialSession-fixed100" `
  --target-count 100 `
  --min-confirmed-wins 33
```

首会话使用 trace 目录 ID，不使用可能晚 1 秒的日志启动时间。`trial.json` 一旦存在，anchor、目标、所需胜场和版本 fingerprint 都不能改；同目录以相同命令重启会恢复原窗口。不得修改 `created_at` 绕过前瞻计划门。

同一 trial 目录只运行一个 helper。需要一次读取时可使用 `--once`；不要与同目录持续运行的实例并发写。持续实例会自动重新读取复核文件，无需为刷新复核另起进程。

## 主要产物

- `trial.json`、`frozen-manifest.json`：固定计划和版本。
- `run-manifests/`：各次运行的 manifest。
- `transactions/`：先持久化、再推进游标的原始事件与证据元数据；重启按顺序回放。
- `evidence/<sha256>.png`：不可变证据副本，结果与异常上下文保留。
- `cursor.json`：读取位置；恢复以最后持久化 transaction 为准。
- `control-holds.json`：版本或数据源异常 HOLD，跨 helper 重启保留。
- `ledger.json`：当前 slot、自动结果、已图审胜场、缺失证据与 HOLD。
- `review-snapshots/`：复核输入的历史快照，保留修订轨迹。

## 独立图审输入

将复核写入同目录的 `reviews.json` 数组。`trial_id` 是 trial 目录名；`slot` 是全局 1–100 序号，不是每个 runner 重置后的局号。SHA 必须属于该 slot 的已验证结果图片。只在实际查看后填写 reviewer。

```json
[
  {
    "trial_id": "实际trial目录名",
    "slot": 1,
    "result": "胜利",
    "sha256": "该slot的结果图片完整SHA256",
    "reviewer": "实际复核者",
    "note": "记录双方皇冠/获胜标识等观察"
  }
]
```

自动 UNKNOWN 可被图审判为胜、负或仍未知，自动标签不会被改写。中断且确实没有结果图时，只允许明确记录非胜：

```json
{
  "trial_id": "实际trial目录名",
  "slot": 2,
  "result": "未知",
  "basis": "no_result_available",
  "reason": "实际缺失和已审阅事件的说明",
  "reviewer": "实际复核者"
}
```

需要纠正既有不同结论时，新条目须用 `supersedes` 指向旧条目的 `review_id`，旧条目保留。错误 SHA、跨 slot 图像和冲突复核不会增加已确认胜场。

## 边界与状态

- `COLLECTING`：尚未形成 100 个关闭槽；纯静默不会关闭 OPEN。
- `HOLD`：版本不符、交错会话、孤立 resumed/end、计划晚于首局或数据源损坏。不会自动新建样本。原始事件与已入组局保留。
- `WINDOW_CLOSED_NOT_YET_QUALIFIED`：100 槽已关闭，但确认胜数、未知复核或证据条件未达标；不会用后来的胜局替换前面的失败局。
- `PASS`：100 槽全部关闭，至少 33 个独立图审胜，证据和身份门通过。helper 此时退出，机器人不会被 helper 控制。

恢复接管只合并唯一 OPEN slot。fresh 开局遇到旧 OPEN，将旧局保留为中断未知；`battle_abandoned` 也保留为未知。没有归属的恢复/结果会 HOLD，不能猜断电丢局是胜局。未知仍占 100 的分母。

源文件和资产变化在窗口采集过程中锁定 HOLD；100 槽关闭后不再接收后续游戏。已冻结的窗口和复核仍可继续读取。生产代码需要修改时，应由主任务明确结束/保留旧试验，再以新版本创建新的 trial；helper 不会自行做这件事。

## 验证

```powershell
work\venv\Scripts\python.exe -m py_compile work\winrate33\trial_ledger.py work\winrate33\test_trial_ledger.py
work\venv\Scripts\python.exe -B -m unittest discover -s work\winrate33 -p test_trial_ledger.py -v
```

15 项纯回放测试已通过，覆盖跨会话恢复合并、未知保留、局号复用、版本 HOLD、固定窗口、重复事件、孤立事件、前瞻计划门以及 32/33 胜阈值。测试没有运行机器人或接触设备；尚未将 helper 启动到正式百场试验。
