# 新页面导航独立集成检查

本次只修改 `py-clash-bot/tests/test_cn_learned_navigation_integration.py`，没有修改 loop、识别器或游戏。另写入本目录审计资料；执行的所有测试均为离线，不连接模拟器、不发送游戏输入。

## 验证结果

- 使用项目验证环境 `work/repair-20261003/verification-env/Scripts/python.exe` 对新增测试执行 `-m py_compile`：通过。
- `D:/codex/bin/ruff.exe check tests/test_cn_learned_navigation_integration.py`，使用项目 Ruff 规则：通过。
- 新增集成测试为 34 例，结合 `test_cn_learned_page_navigation.py`、`test_cn_daily_gift_integration.py`、`test_cn_daily_gift.py`、`test_cn_navigation_recovery.py`、`test_cn_random_recovery.py` 离线联跑：**196 passed in 19.90s**。
- pytest 临时目录为本任务的 `pytest-nav-integration-final`，未触碰正式记录或游戏设备。

## 实际覆盖的契约

- Random `_startup_frame`：锦标赛帮助 → 创建界面 → 锦标赛 → 大厅，逐步读取新截图返回，不将嵌套页面直接视为未知故障。
- Random `_require`：已记住的模态页先闭合，读取新大厅后再切换卡组；只在新截图确认 deck 后返回。
- Random `_navigate`：通过两个嵌套页返回后，再从新大厅执行主页面切换；截图和证据引用同一帧。
- `pending_battle`、`pending_claim_all` 和 `matching/battle` 状态阻止观战退出和普通页面恢复；奖励 receipt、claim ID 与计数保持不变。
- idle 状态的观战使用一次 Android Back，再识别退出确认，再返回 TV，最后读取大厅；未再次读取旧画面或发盲点。
- Random 三个入口均最多发送 12 次页面返回输入，然后 bounded 暂停；Chinese 同样最多 12 次，在确认大厅后清零。
- Chinese 将 burger、settings、more settings、inbox 识别为 `navigation`；burger 先闭合，下次读取经典大厅才开始匹配。
- Chinese 在 battle、match、result 状态不能点击已学习的 overlay 或退出观战，已有 reward context 不能由普通导航接管。

## 来源与资源身份检查

最初检查指出的新 detector 和资源身份缺口已由 root 修复；重新读取源码确认：

- 两 loops 的 source identity 纳入 `detection/cn_daily_gift.py`、`detection/cn_page_navigation.py`；Chinese 另纳入 `bot/nav.py` 与 `bot/state_detect.py`。
- 两 loops 的 asset identity 纳入 `cn_daily_gift` 和 `cn_pages` 文件夹的 PNG/JSON，包含页面 manifest。
- Random policy 为 `random-mastery-v25-learned-navigation-20261004`。

这是源码审计，未证明冻结包已包含这些文件；新包仍须进行 copied source 哈希和 lib 编译模块验证。

## 静态页面审计范围

`saved-page-classification-audit.json` 使用当前实际 detector，对已保存截图做纯只读识别。生成时是 49 张截图、27 条 manifest 页面定义，36 张有识别结果；13 张未识别均为仍在采集/扩展中的表情市场和商店页面，具体名称在 JSON 的 `uncovered` 字段。

该数目是 2026-10-04 14:22 左右的瞬时快照，其他 agent 继续加入模板后需要刷新。它不代表完整按钮覆盖，也未验证部署后真实导航、每日下一次弹窗、开始对战或无限循环恢复。
