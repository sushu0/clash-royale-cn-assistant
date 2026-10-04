# 皇室战争页面识别更新部署复核

本文件为只读审计得出的操作方案。截至本次审计，尚未执行新构建、软件切换或快捷方式替换，也未证明全部页面覆盖。部署操作者应在源代码验证完成后执行下列步骤。不得覆盖旧包或丢弃已有前端修改。

## 当前证据

- 当前 GUI PID 为 `19296`，实际路径为 `D:\codex\CodexWork\clash\outputs\desktop-app-history-20261004\ClashAssistant.exe`。执行切换前必须重新查询；PID 是瞬时观察值。
- 桌面快捷方式为 `D:\codex\profile\Desktop\皇室战争助手.lnk`，实际目标为上述旧包，参数为空。审计时 SHA-256 为 `9CD8EF859D33330801D5595C1FF332D63ADC8DC9EBBB28996CE68A0FADB8D707`。
- `desktop-runtime.json` 指向共享数据根 `D:\codex\CodexWork\clash`；新包沿用此根，保留战绩、奖励记录、两份异常报告与选定策略。
- 冻结包的 watchdog 和 runner 均由相同 EXE 的 `--component` 分派，实际导入 `lib` 下编译模块。只修改仓库或包内 `source` 副本不能更新运行逻辑。
- 验证环境是 `work\repair-20261003\verification-env\Scripts\python.exe`，实测 Python `3.12.14`、cx_Freeze `8.6.4`、pytest `9.1.1`。
- 审计时仓库中的 `scripts\cn_bot_control.py`、`scripts\watch_cn_1v1.py`、`pyclashbot\interface\cn_console_theme.py`、`pyclashbot\interface\cn_native_view.py` 与旧包内 copied source 的哈希相同。构建前须再复核，确保另一聊天的前端变化未被遗失。
- 08:00 报告原因是“导航后未确认经典1V1大厅”；11:44 报告原因是“未确认 deck 页面，暂停操作”。报告中的 `game_input_sent=false` 指报告采集本身没有输入，不代表之前的机器人没有点击。

## 构建与不发输入的包装校验

仅在 root 确认源码稳定、相关测试已通过后运行。若指定的新输出目录已有文件，先选用新的任务后缀，不要覆盖。

```powershell
. 'D:\codex\bin\Initialize-CodexEnvironment.ps1'
Set-Location -LiteralPath 'D:\codex\CodexWork\clash\py-clash-bot'
$env:PYCLASHBOT_DESKTOP_OUTPUT = 'D:\codex\CodexWork\clash\outputs\desktop-app-navigation-20261004'
$env:PYCLASHBOT_DESKTOP_WORK = 'D:\codex\CodexWork\clash\work\navigation-learning-20261004\build'
& 'D:\codex\CodexWork\clash\work\repair-20261003\verification-env\Scripts\python.exe' scripts/build_cn_desktop.py build_exe
```

构建应直接显示日志或由工具保留运行会话。不可将新 GUI 提前开启后仍保留旧 GUI。

```powershell
. 'D:\codex\bin\Initialize-CodexEnvironment.ps1'
Set-Location -LiteralPath 'D:\codex\CodexWork\clash'
$selfCheckArgs = @('--self-check', '--self-check-output', 'D:\codex\CodexWork\clash\work\navigation-learning-20261004\package-self-check.json')
$checkedProcess = Start-Process -FilePath 'D:\codex\CodexWork\clash\outputs\desktop-app-navigation-20261004\ClashAssistant.exe' -ArgumentList $selfCheckArgs -WindowStyle Hidden -PassThru -Wait
if ($checkedProcess.ExitCode -ne 0) { throw "Self-check failed: $($checkedProcess.ExitCode)" }
Get-Content -LiteralPath 'D:\codex\CodexWork\clash\work\navigation-learning-20261004\package-self-check.json'
```

现有 self-check 只检查基础手牌样本、威胁模板、OCR 资源和环境，不能单独证明新页面识别可用。另须验证新包 `lib\pyclashbot\detection\cn_daily_gift.pyc` 与 `cn_page_navigation.pyc` 存在，变更的 loop `.pyc` 已更新，copied source 与最终源码哈希一致，新增图片模板全部入包。新增检测器和返回导航需通过专门离线/运行验收。

## 安全切换 GUI 与快捷方式

1. 在旧 GUI 点击“停止任务”，确认 watchdog 与 runner 停止。若 PID 文件对应的进程已经不存在，保留现状，不能用陈旧 PID 强制终止其他进程。命令行停止冻结进程应由对应旧包的 EXE `--component stop_cn_1v1.py --pid-file ...` 执行，源解释器的停止命令不能可靠识别冻结进程。
2. 使用旧 GUI 的“应用 → 退出软件（停止任务）”。右上角 × 的行为是收进托盘，不是退出。正常退出会还原 MEmu 的嵌入窗口，释放 single-instance；不可用 `Stop-Process`、强杀 GUI 或 WM_CLOSE 替代。观察旧 PID 消失、MEmu 保持打开后再启动新 GUI。
3. 新 GUI 启动成功、页面可见、仍为同一数据根后再替换快捷方式。使用现有脚本自动备份旧 `.lnk`，保留脚本输出的回退路径。

```powershell
. 'D:\codex\bin\Initialize-CodexEnvironment.ps1'
Set-Location -LiteralPath 'D:\codex\CodexWork\clash'
& '.\py-clash-bot\scripts\install_cn_desktop_shortcut.ps1' -Executable 'D:\codex\CodexWork\clash\outputs\desktop-app-navigation-20261004\ClashAssistant.exe' -EvidenceDirectory 'D:\codex\CodexWork\clash\work\navigation-learning-20261004\deployment'
```

该脚本会读回 target、working directory、参数和 AppUserModelID，并记录 EXE/快捷方式哈希。此次桌面路径在 D 根之内；不新增 C 盘文件。

4. 观察 `work\random-frontend-state.json`：`frozen=true`，GUI PID 对应新包，旧战绩与错误历史可见。核实没有旧 GUI、旧 watchdog 或旧 runner 仍持有设备。
5. root 完成页面覆盖/返回验收后，在新 GUI 点击“开始运行”。核对新 watchdog、runner 的 EXE 都来自新包，日志/状态出现新的 session，策略保持 random、无限模式的 `max_battles=0`。至少实际观察经典 1V1 开始、出牌、结算与下一局重启；观察不到的阶段在报告中保留未验证。

## 回退

1. 若新识别/导航触发异常，先点击新 GUI“停止任务”，按上面正常退出流程释放嵌入窗口和单实例。
2. 保留新构建、报告和日志证据；不删除旧数据，不重置战绩数据库，不回滚奖励账本。
3. 使用部署证据 `deployment\desktop-shortcut.json` 的 `replaced_shortcut_backup.path`，核验备份哈希后，`Copy-Item -LiteralPath <该备份> -Destination 'D:\codex\profile\Desktop\皇室战争助手.lnk'` 恢复本次替换前的快捷方式，再读回 target 验证。不能使用更早的备份误退至更旧版本。
4. 开启 `outputs\desktop-app-history-20261004\ClashAssistant.exe`，确认旧 GUI 和历史数据恢复。旧包具有本次修复前的页面识别限制，避免声称回退仍可处理新每日弹窗。
5. 若需要源码回退，只对本任务实际变更文件使用 `work\navigation-learning-20261004\backup` 中对应的原始副本；先复核 diff 与哈希，保留其他聊天的前端改动。源码回退不会自行改变已经构建的冻结包。

## 交付验收记录要点

`inspect_capture_inventory.py` 仅枚举 `pages` PNG 尺寸、哈希及已备份/源文件路径，不发送游戏输入，也不将文件数量当作完整按钮覆盖。完成报告仍需关联每个页面的实际入口、返回按钮、识别条件、截图、验证结果，并明确没有访问/受权限或交易边界限制的按钮。
