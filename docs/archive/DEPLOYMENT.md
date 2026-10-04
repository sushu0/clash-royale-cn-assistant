# 国服《皇室战争》最小 1v1 自动循环

## 当前部署

- 上游项目：`pyclashbot/py-clash-bot`，检出提交 `34d11e577689510a75f3e5fac0104214102b664d`；本机做了局部适配。
- 模拟器：MEmu 9.5.7.1，Android 9，DirectX 渲染，419×633、160 DPI。当前 ADB 序列号为 `127.0.0.1:21503`。
- MEmu 实际安装目录：`D:\codex\CodexWork\clash\work\downloads\Microvirt`。这是正在运行的安装，不能把它当作临时下载目录清理。
- 游戏：腾讯包 `com.tencent.tmgp.supercell.clashroyale`，版本 38.3.1。APK 来自腾讯游戏官网下载配置指向的应用宝 CDN，SHA-256 为 `7FFB7BAD5E83FDDCE881EB85C3FF5276FFAA4BFF46BB1240A1B7654CB10BF3C5`。
- Python 3.12 环境：`D:\codex\CodexWork\clash\work\venv`；已以 editable 模式安装上游项目及依赖。

## 运行方式

后台守护进程运行 `scripts/run_cn_1v1.py`，只做大厅启动、简单可用卡出牌、结算返回、下一场和故障恢复。日志分别在：

2026-09-25 后续更新：默认出牌逻辑已换成国服 2.6 速猪规则，支持精英冰人与已验证的进化卡图。规则、边界、来源和回退见同目录 `HOG_STRATEGY.md`；详细策略轨迹见 `cn-hog-strategy.jsonl`。下文原10场验收记录属于基础连续对战循环，不作为新策略胜率提升证明。

- `D:\codex\CodexWork\clash\outputs\cn-battles-live.log`：简要对战与恢复事件。
- `D:\codex\CodexWork\clash\outputs\cn-watchdog.log`：进程守护事件。
- `D:\codex\CodexWork\clash\outputs\acceptance.json`：独立日志校验结果。

### 图形控制窗口

双击 `D:\codex\CodexWork\clash\outputs\打开机器人控制台.cmd` 打开 Windows 控制窗口。窗口显示后台状态、当前运行已完成场次、当前连续完成场次和最近日志。点击“启动机器人”会检查并启动 MEmu/ADB，重新打开国服客户端，再拉起守护进程；点击“停止机器人”只停止本任务的后台进程，保留模拟器和游戏。关闭控制窗口本身不会停止机器人。

如果 Windows 会话重启，可从 `D:\codex` 运行：

```powershell
& 'D:\codex\CodexWork\clash\py-clash-bot\scripts\start_cn_1v1.ps1'
```

需要停止时，可从 `D:\codex` 运行：

```powershell
& 'D:\codex\CodexWork\clash\work\venv\Scripts\python.exe' 'D:\codex\CodexWork\clash\py-clash-bot\scripts\stop_cn_1v1.py' --pid-file 'D:\codex\CodexWork\clash\work\bot-processes.json'
```

停止脚本会先核对 PID 对应的命令行，再停止本任务的守护进程和运行器；不会卸载 MEmu 或删除游戏数据。这也是本次部署的直接回退方法。

## 验收与边界

从 `2026-09-25 05:35:27` 到 `06:00:37`，运行器连续完成 10 场，每场均有确认出牌；第 11 场于 `06:01:05` 自动开始。独立校验器返回 `accepted: true`，该段没有恢复事件。随后实测了 ADB 断开自动重连，以及游戏进程被停止后的自动拉起和战斗接管。

当前账号由用户在模拟器内自行登录；运行器不处理微信／QQ 认证。连接弹窗尚无真实样本模板，出现无法识别的弹窗时依靠有界超时和应用重启恢复。长期运行依赖当前 Windows 会话；重启 Windows 后使用上述启动脚本恢复。
