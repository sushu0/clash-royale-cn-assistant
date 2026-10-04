# py-clash-bot

当前维护和验证的入口是 **Windows 国服控制台**：`scripts/cn_windows_entry.py`，源码命令 `pyclashbot-cn`，控制台实现 `scripts/cn_bot_control.py`。它通过已有 MEmu/ADB 设备运行随机卡组熟练度循环，也保留 567 双空军和野猪模式、战绩索引及结算证据。

`python -m pyclashbot` 仍是旧通用 GUI；macOS DMG 也保留这个独立入口。旧 GUI 的英文客户端识别、BlueStacks、Google Play Games 与当前国服控制台是不同的运行路径。本次 Windows 离线验证不代表 macOS、全球服客户端或任意模拟器组合已完成实机验收。

## Windows 本地运行

项目、运行数据、缓存和验证环境均放在 `D:\codex`。当前源码根目录为 `D:\codex\CodexWork\clash\py-clash-bot`。需要 Python 3.12；直接运行依赖和开发工具版本由 `pyproject.toml`、`uv.lock` 一起固定。

```powershell
Set-Location -LiteralPath D:\codex\CodexWork\clash\py-clash-bot
. D:\codex\bin\Initialize-CodexEnvironment.ps1
uv sync --locked --python 3.12
uv run --locked --no-sync pyclashbot-cn --self-check
uv run --locked --no-sync pyclashbot-cn
```

`--self-check` 检查包内识别资源和环境信息，不启动 VM、不连接游戏、不发出游戏输入。打开控制台也不自动开始对战；使用窗口的策略选择和启动按钮进入相应运行链。已有策略选择会保留；没有保存选择时兼容默认值为 567，当前机器保存的模式是随机卡组。战绩范围筛选只影响查看，不负责选择机器人模式。

源码入口启动 watchdog/runner 时使用运行配置中的 `python`，默认沿用数据根的 `work\venv\Scripts\python.exe`。如果创建了新的 `.venv` 或隔离验证环境，应在新的配置文件里明确填写对应解释器；不要对正在对战的旧环境执行依赖同步。安装后的 Windows 可执行文件通过 `--component` 调度自身，不依赖源码目录或外部 Python。

`make setup`、`make cn` / `make dev`、`make cn-check` 提供同样的源码入口。PowerShell 可以直接使用上面的 `uv` 命令，无需安装 GNU Make。

## 运行配置

`pyclashbot/utils/runtime_config.py` 统一解析控制台、runner 和冻结程序的路径。Windows 的普通运行数据根必须位于 `D:\codex`；源码默认使用仓库的父目录，冻结程序及位于其他路径的 Windows checkout 默认使用 `D:\codex\apps\pyclashbot`。

| 配置 | 用途及默认值 |
| --- | --- |
| `PYCLASHBOT_DATA_ROOT` | `work`、`outputs`、日志、断点、证据和进程锁的父目录 |
| `PYCLASHBOT_CONFIG` | JSON 配置路径，默认 `<数据根>\work\runtime-config.json` |
| `PYCLASHBOT_ADB` | 现有 ADB 路径；覆盖 JSON 的 `adb`，没有配置时沿用本机 D 盘平台工具路径 |
| `PYCLASHBOT_MEMUC` | 现有 MEmu 控制工具路径；覆盖 JSON 的 `memuc`，默认 `<数据根>\work\downloads\Microvirt\MEmu\memuc.exe` |
| `PYCLASHBOT_GAME_PACKAGE` | `cn` / `global` 或对应完整游戏包名；默认腾讯国服，显式选择仅改变启动包，不切换识别模板 |
| `UV_PROJECT_ENVIRONMENT` | uv 项目环境位置；隔离验证时填写 `D:\codex` 下的新目录 |

配置文件可指定 `python`、`adb`、`memuc`、`serial`、`vm_index`。下面仅是配置结构示例，请填写已安装的工具和实际目标实例：

```json
{
  "python": "D:\\codex\\CodexWork\\clash\\py-clash-bot\\.venv\\Scripts\\python.exe",
  "adb": "D:\\codex\\tools\\android-platform-tools\\adb.exe",
  "memuc": "D:\\codex\\apps\\MEmu\\memuc.exe",
  "serial": "127.0.0.1:21503",
  "vm_index": 0
}
```

当前国服识别坐标基于 **419×633、160 dpi** 的画面。ADB serial 和 VM index 必须指向同一目标。更换客户端、分辨率或素材需要重新验证检测与部署；成功识别包名或发送点击不能替代画面验收。单设备进程锁阻止两个策略同时对同一运行数据根的目标设备发出输入。

## 模拟器边界

国服控制台沿用已配置的 MEmu 实例。旧通用 MEmu 后端使用专用 `pyclashbot-136` VM；两者不要混为同一实例或同一 Android 版本。MEmu 重启只停止选定 VM，不按全机进程名清理用户其他实例。

旧 BlueStacks 后端要求唯一、明确命名为 `pyclashbot-136` 的 Android 13（Tiramisu 64-bit）实例；没有 Google 登录不代表可接管。Google Play 后端只管理所发现安装的默认 VM，对未知自定义 ADB 传输拒绝生命周期操作。所有通用 ADB 命令都有默认期限；MEmu 截图最多三次并有总期限。用户原来的显示 override 会精确恢复，原本没有 override 时使用 `wm reset`。

## 验证、打包和数据

```powershell
uv lock --check
uv run --locked --no-sync ruff check .
uv run --locked --no-sync ruff format --check .
uv run --locked --no-sync ty check
uv run --locked --no-sync pytest -q
```

默认 pytest 排除 `emulator` 实机项目。`make dev-validation` 运行只读格式/静态检查、类型检查和离线测试；`make lint` 执行会修复格式的 pre-commit。`make test-emulator` / `--integration` 会启动或重启选定模拟器并发送游戏输入，属于单独的实机验收步骤。

CI 在 Windows 执行离线行为测试，在 Windows/Linux 执行共享静态检查；打包与发布需要通过这些检查。所有 CI 安装使用 `--locked`，Ruff、ty、pre-commit 从同一个项目锁获得。PR 工作流只有读取仓库内容的权限；Discord 公告仅在仓库变量 `ANNOUNCE_DISCORD=true` 时启用。

`make build-msi TARGET_VERSION=v0.0.0-local` 构建 Windows 国服入口；`make build-dmg TARGET_VERSION=v0.0.0-local` 构建旧 macOS GUI。它们使用 build 依赖组并将资源放入包内。构建成功、冻结程序资源自检成功和实际游戏闭环成功分别记录；前两者不证明胜率或跨平台实机兼容性。

`outputs` 中的原始 JSONL 是战绩与奖励证据来源，SQLite 是可重建索引。结算、恢复和领奖关键截图按内容保留；普通观察可以轮换。旧版已经覆盖的截图无法从哈希恢复，证据缺失应继续显示。断点、结果待发布文件和进程身份记录均有验证及原子落盘；备份、离线检查和回退方法见 [运行与验证说明](docs/runtime-and-validation.md)。

进一步说明：[国服控制台与策略历史](docs/cn-console-and-v4.md) · [开发约定](CONTRIBUTING.md)。

## License

Source: [NC-CL-1.0](LICENSE) · Assets: [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) · [Commercial inquiries](LICENSE)。Clash Royale 游戏素材归 Supercell 所有，项目中的参考图仅用于识别。上游源码与发布信息见 [pyclashbot/py-clash-bot](https://github.com/pyclashbot/py-clash-bot)。
