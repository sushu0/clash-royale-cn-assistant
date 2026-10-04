# 机器人控制台界面更新

## 已完成

- 浅灰背景、深蓝状态区、皇冠标识、统一字体与圆角卡片。
- 顶部显示实际后台运行状态；启动/停止按钮按运行与忙碌状态启用。
- 三张统计卡：本次运行已完成、连续完成、最近一局结果及出牌确认。
- 对战动态以时间、事件类型、简洁描述显示，并用颜色区分对战、胜利、失败、恢复。
- 可切换最近原始日志；自动滚动可关闭，重新勾选立即回到最新事件。
- 最大化时内容宽度受限并居中；卡片高度按实际字体请求高度确定，修复Windows缩放下文字裁切。

## 修改范围

只修改 `D:\codex\CodexWork\clash\py-clash-bot\scripts\cn_bot_control.py`。
启停线程、Queue、默认无限对战、MEmu/ADB配置、停止脚本、关闭窗口行为及2秒刷新机制保持原样。
未修改对战策略、模板或游戏配置。

## 验证

- `python -X utf8 -m py_compile scripts/cn_bot_control.py` 通过。
- `python -X utf8 -m unittest tests.test_cn_finite_batch -q` 4项通过。
- AST比较确认 `_tick`、`_action`、`_start`、`_stop`、`_start_worker`、`_stop_worker`、`_on_close`、`run` 与备份完全一致。
- 窗口组件检查：停止/运行/恢复/忙碌状态按钮规则、两种日志模式、空记录提示、主题颜色及卡片高度通过。该检查使用模拟状态，没有启停真实机器人。
- Computer Use真实窗口检查：普通窗口、最大化居中布局、原始日志切换、历史滚动、重新开启自动跟随均通过；真实新对局使场次和最近胜负同步更新。
- `git diff --check`通过；界面进程stderr为空。原后台PID仍为20048/30696，末次检查状态running。
- 最后小窗口尺寸检查/关闭旧窗口时Computer Use报告 `user input was detected in this window; call get_window_state before continuing`，并显示窗口已最小化；按Computer Use恢复规则停止继续操控。没有宣称最小尺寸已实机验收，也未强制关闭用户窗口。

## 使用

原入口保持有效：`D:\codex\CodexWork\clash\outputs\打开机器人控制台.cmd`。
新版窗口已启动。若仍看到旧样式，关闭旧控制台并从同一入口重新打开即可；关窗口不会停止后台机器人。
预览：`D:\codex\CodexWork\clash\outputs\control-panel-preview.png`（本次实机验证截图）。

## 回退

关闭控制台窗口后，将 `D:\codex\CodexWork\clash\work\backups\control-ui-20260926-192202\cn_bot_control.py` 复制回 `D:\codex\CodexWork\clash\py-clash-bot\scripts\cn_bot_control.py`，再从原入口打开。
本次仅界面回退，不需要停止对战进程。
