# 错误报告历史列表修复

今天两份暂停报告原本都已保存，旧页面只读取 `latest-error-report.json`，所以只能看到最新一份。此次把页面改为直接发现报告目录中的历史记录，按暂停时间倒序列出，并提供所选报告的详情、截图和文件打开入口。

| 暂停时间（北京时间） | 原因 | 原始文件 |
| --- | --- | --- |
| 2026-10-04 11:44:18 | 未确认 deck 页面，暂停操作 | report.md、report.json、game.png 齐全 |
| 2026-10-04 08:00:06 | 导航后未确认经典1V1大厅 | report.md、report.json、game.png 齐全 |

操作方法：双击桌面“皇室战争助手”，点击左侧“错误报告”。左侧列表显示全部历史，点击任意一行，右侧显示该次报告。顶部“打开所选报告”和“查看截图”对应当前选中的事件。选中旧报告后，定时刷新或新增报告会保留当前选择与阅读位置。

所有原始报告仍在 `D:\codex\CodexWork\clash\outputs\error-reports`。两张截图为 419×633，实际哈希与各自报告记录相符。六个原始历史文件读取前后的 SHA256 完全一致，见 `work\error-history-20261004\original-report-hashes.json` 和 `history-verification.json`。

修改了 `scripts\cn_bot_control.py` 的历史列表和选中报告展示，扩展 `pyclashbot\utils\cn_error_report.py` 的只读历史发现接口。发现历史不依赖最新索引；单条损坏记录不会影响其他正常报告。重启软件后会重新发现全部历史。

新版程序独立保存于 `outputs\desktop-app-history-20261004`，数据仍使用原项目目录。桌面快捷方式已经更新，并保留旧快捷方式备份于 `work\error-history-20261004\shortcut-backup`；旧程序目录仍保留。已在旧任务完成一局闭环后正常退出旧软件、从桌面打开新版并点击开始恢复无限对战。正式页面显示两份历史，实际选中 08:00 记录后，右侧原因、报告路径与截图路径全部对应旧事件，并通过“查看截图”在 Windows 照片中打开了原始截图。刷新保持旧选择。最终核验时间为北京时间 2026-10-04 12:44，验收见 `ERROR_REPORT_HISTORY_ACCEPTANCE_20261004.json`。

验证：项目 Ruff 和 Python 编译通过；169 项测试、6 项子测试通过，1 项需要 Windows 文件 symlink 权限的实际测试跳过，实际目录 junction 和 reparse 回归通过。完整日志位于 `work\error-history-20261004\tests-final-all.log`。

回退时先从新版应用菜单退出软件、停止任务，再用备份的旧快捷方式指向旧程序。修改前源代码备份位于 `work\error-history-20261004\backup`。历史报告与截图独立保存，回退软件入口不会改变它们。
