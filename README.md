# 皇室战争国服助手

一个以 Windows 中文客户端为主要维护目标的《皇室战争》自动化实验项目：通过 MEmu 和 ADB 读取游戏画面，用图像识别与状态机完成随机卡组对战、熟练度奖励检查，并在桌面界面中保留对局、异常和截图证据。

本仓库由 [sushu0](https://github.com/sushu0) 公开维护，基于 [pyclashbot/py-clash-bot](https://github.com/pyclashbot/py-clash-bot) 修改。希望把中文客户端适配、策略实现、桌面程序和开发工具一并分享，方便大家阅读、复现和继续改进。源码与文档沿用上游的**非商业许可**；使用和再分发前请阅读 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)。

**2026-10-08 更新的是 `main` 分支源码和文档。** 本次同步了每日精选、免费奖励与购买统计、奖励弹窗处理、暂停修复辅助和桌面状态相关实现，没有制作新的安装包或更新 GitHub Release。2026-10-05 的安装包是当时的旧二进制；下载它不会自动获得当前 `main` 的后续修改。已有克隆的更新方法见下文，游戏画面变化后的适配方法见 [图片识别维护指南](docs/VISION_MAINTENANCE.md)。

## 已实现的内容

| 部分 | 内容 |
| --- | --- |
| 随机卡组熟练度 | 卡组生成、经典 1V1 循环、结算返回、熟练度页面检查与领取全部结果确认 |
| 三种策略 | 随机卡组 `random`、567 双空军 `567`、野猪 `hog`，保留各自的源码和历史记录读取 |
| 每日精选 | 手动触发商店检查、免费奖励领取和金币商品购买；跳过宝石商品，保留确认后的交易证据与当日统计 |
| 中文桌面程序 | WPF 对战工作台、模拟器画面嵌入、系统托盘、对局记录、策略统计、异常报告、运行日志 |
| 分享版首次设置 | 选择 MEmu/ADB、填写本机设备地址、只读检查分辨率、DPI 和腾讯版游戏是否安装 |
| 运行与恢复 | runner/watchdog、进程归属检查、设备输入锁、断点和停止确认 |
| 暂停修复辅助 | 本地异常 case 队列、独占 claim、停止意图门禁、失败冷却与闭环 proof 校验；实际修复由另行配置的 Codex 工作流完成 |
| 战绩与证据 | 原始 JSONL、可重建 SQLite 索引、结算截图哈希、未知结果和证据缺失显示 |
| 开发工具 | 锁定依赖、离线测试、Ruff、ty、冻结打包与桌面构建源码 |

它使用屏幕识别和固定坐标，没有游戏 API。维护范围与识别精度受客户端画面、模拟器和分辨率影响；本仓库没有承诺固定胜率或保证每种牌都能正确应对。

每日精选是会发送游戏操作的独立功能：先停止对战任务，再在 WPF 中主动触发。商品、币种、确认弹窗和交易结果需要分别识别；未知价格、证据不足或不确定的购买结果会停止或跳过，不重复尝试可能已经完成的交易。当日累计按已确认收据去重，不能把点击次数当成已购买数量。奖励弹窗和页面返回也依赖已校准画面，新增处理分支不代表新版游戏所有弹窗都已适配。

`scripts/cn_auto_repair.py` 提供状态和 case 管理，不会自行修改源码、部署后端或恢复游戏。仓库中记录的定时监测是作者本机 Codex chat 的工作流，克隆仓库不会复制或启用它。手动停止、关闭功能、claim 失效或证据不足均应阻止自动恢复；自己的调度与修复流程需另行配置。接口说明见 [暂停修复辅助](py-clash-bot/docs/cn_auto_repair.md)，其中本机路径和 chat 绑定仅是原环境记录。

## 选择运行方式

| 入口 | 适用场景 | 路径与环境 |
| --- | --- | --- |
| `desktop-portable/` + `portable-backend/` | 希望分享给其他 Windows 用户的桌面版本 | 程序使用安装目录内的 `app`、`backend`、`data`，运行数据不依赖原作者的 D 盘目录；首次启动有环境设置窗口 |
| `py-clash-bot/` | 阅读、调试 Python 核心，直接从源码运行 | Python 3.12；当前 Windows 实现要求运行数据位于 `D:\codex` 下 |
| `desktop-wpf/` | 原始 WPF 开发版 | .NET 10 Windows；后端和运行数据仍要求位于 `D:\codex` 下 |

分享版的前端与后端源码一并提供，`tools/build_portable.py` 负责从源码组装完整应用；普通用户无需复制作者的旧冻结包。仍需自行配置 MEmu、ADB 和游戏。构建命令与检查方式见 [构建说明](docs/BUILD.md)。实际可下载的安装包以仓库 [Releases](https://github.com/sushu0/clash-royale-cn-assistant/releases) 为准。

## 使用分享版桌面程序

完整应用的目录组织如下；`data` 是每位使用者自己的运行记录目录。

```text
安装目录/
├─ app/       # ClashAssistant.Desktop.exe、wpf-runtime.json 等
├─ backend/   # ClashBackend.exe、Python 运行时、识别素材及对应源码
├─ tools/     # 可选的 ADB 工具及其许可说明，也可在设置中选择自行安装的 ADB
└─ data/      # work/ 配置与状态；outputs/ 对局与证据
```

1. 自行安装 MEmu 和腾讯国服《皇室战争》，手动登录游戏。目前只支持 **MEmu 0 号实例**。
2. 在模拟器中设置 Android 有效分辨率为 **419 × 633**、DPI 为 **160**。确认 ADB 设备地址对应同一个实例。
3. 首次打开桌面程序，在设置窗口选择 `memuc.exe`、`adb.exe`，填写设备地址，例如 `127.0.0.1:21503`。便携后端只接受本机 `127.0.0.1:端口` 地址。
4. 点击“检测环境”，修正检查中显示的问题，再保存配置。检测会读取连接状态、屏幕参数和游戏安装信息；它不会启动模拟器、修改屏幕参数、登录游戏或输入对战操作。
5. 重新打开主界面，确认模式与目标设备，再手动点击“开始运行”。窗口启动与环境设置均不会自动开始对战。

可以用 `ClashAssistant.Desktop.exe --setup` 重新打开环境设置。配置保存到 `data/work/runtime-config.json`；数据保存到当前安装目录内的 `data`，移动应用时应完整保留目录关系。

**策略设置目前通过文件完成。** 桌面界面里的“随机卡组 / 567 历史 / 野猪历史 / 全部历史”只筛选战绩。先在界面停止任务，再把 `data/work/bot-selected-strategy.txt` 的内容设为 `random`、`567` 或 `hog`，之后再开始任务。没有有效的保存值时，Python 控制链兼容默认 `567`。随机卡组示例：

```powershell
# 替换成自己的实际安装目录；请先停止任务。
$installRoot = 'D:\Games\ClashAssistant'
New-Item -ItemType Directory -Force -Path "$installRoot\data\work" | Out-Null
Set-Content -LiteralPath "$installRoot\data\work\bot-selected-strategy.txt" -Value 'random' -Encoding ascii
```

只有提供了冻结后端、Python 运行时和依赖的完整分发包才可以免安装 Python。是否需要安装 .NET 运行时取决于前端构建方式；[构建说明](docs/BUILD.md) 使用自包含发布命令。

## 从 Python 源码运行

需要 Windows、Git、[uv](https://docs.astral.sh/uv/getting-started/installation/)，以及自行安装的 MEmu 和 ADB。以下步骤使用普通 PowerShell，不依赖原作者机器上的初始化脚本。

当前 Python 实现和原始 WPF 版会检查 `D:\codex` 存储边界。没有 D 盘的用户应使用完整分享版，或先参与改进源码的路径可移植性。

```powershell
New-Item -ItemType Directory -Force -Path 'D:\codex\projects' | Out-Null
Set-Location -LiteralPath 'D:\codex\projects'
git clone https://github.com/sushu0/clash-royale-cn-assistant.git
Set-Location -LiteralPath '.\clash-royale-cn-assistant'
$repo = (Get-Location).Path
$data = 'D:\codex\apps\clash-royale-cn-assistant'
New-Item -ItemType Directory -Force -Path "$repo\work\temp", "$data\work", "$data\outputs" | Out-Null

# 让本次 shell 的 Python、缓存和临时文件留在 D 盘。
$env:UV_CACHE_DIR = "$repo\work\uv-cache"
$env:UV_PYTHON_INSTALL_DIR = "$repo\work\python"
$env:TEMP = "$repo\work\temp"
$env:TMP = $env:TEMP
$env:PYCLASHBOT_DATA_ROOT = $data
$env:PYCLASHBOT_CONFIG = "$data\work\runtime-config.json"

Set-Location -LiteralPath "$repo\py-clash-bot"
uv sync --locked --python 3.12
```

在继续前，创建配置文件。请把下面两个工具路径和设备地址改成自己的实际安装信息；`python` 必须指向刚创建的项目环境，因为 runner/watchdog 会使用它启动子进程。

```powershell
$configuration = @{
    python = "$repo\py-clash-bot\.venv\Scripts\python.exe"
    adb = 'D:\Android\platform-tools\adb.exe'
    memuc = 'D:\MEmu\MEmu\memuc.exe'
    serial = '127.0.0.1:21503'
    vm_index = 0
} | ConvertTo-Json
[IO.File]::WriteAllText($env:PYCLASHBOT_CONFIG, $configuration, [Text.UTF8Encoding]::new($false))

# 先做资源与环境自检，再打开窗口。
uv run --locked --no-sync pyclashbot-cn --self-check
Set-Content -LiteralPath "$data\work\bot-selected-strategy.txt" -Value 'random' -Encoding ascii
uv run --locked --no-sync pyclashbot-cn
```

`--self-check` 校验包内识别资源并输出环境身份，不启动 VM、不连接游戏、不发出游戏输入。它通过后，仍需在自己的机器上确认界面、目标设备、结算、奖励和停止行为。

每次打开新 PowerShell 窗口，都需要重新设置本次使用的环境变量。切换虚拟环境时同步修改 JSON 的 `python` 字段；不要对正在运行的机器人环境做依赖升级。当前桌面启动链固定使用 MEmu 0 号实例，单独改 JSON 的 `vm_index` 不会把它切到其他实例。

## 更新已有源码

先在界面停止任务并退出正在使用的程序，保留自己的运行数据。下面假设已经按上文克隆并配置了项目；新 PowerShell 窗口需重新设置 `$repo`、`$data` 和运行环境变量。先检查工作树，本地修改应单独保存；`git pull --ff-only` 遇到分支分叉会停止，不要用强制重置覆盖自己的修改。

```powershell
Set-Location -LiteralPath 'D:\codex\projects\clash-royale-cn-assistant'
$repo = (Get-Location).Path
git status --short
git switch main
git pull --ff-only origin main

Set-Location -LiteralPath "$repo\py-clash-bot"
uv sync --locked --python 3.12
uv lock --check
uv run --locked --no-sync python -m scripts.cn_windows_entry --self-check
uv run --locked --no-sync pytest -q -p no:cacheprovider --basetemp="$repo\work\pytest-update"

# 配置和策略选择仍由自己的数据根提供；打开窗口不会自动开始对战。
uv run --locked --no-sync python -m scripts.cn_windows_entry
```

这会更新并运行 Python 源码。已安装的 `ClashBackend.exe`、WPF 程序和旧 Release 使用各自的冻结代码；只执行 `git pull` 或修改安装目录中的 `source` 副本不会更新它们。需要当前 WPF 功能时，应按 [构建说明](docs/BUILD.md) 从同一个 `main` 提交重新构建前端、后端和素材。完整更新方法、两后端素材同步与适配回归见 [图片识别维护指南](docs/VISION_MAINTENANCE.md)。

## 阅读源码

```text
.
├─ README.md / LICENSE / NOTICE
├─ py-clash-bot/
│  ├─ pyclashbot/bot/          # 状态机、中文循环和三种策略
│  ├─ pyclashbot/detection/    # 识别实现与参考素材
│  ├─ pyclashbot/emulators/    # 模拟器、ADB 和生命周期适配
│  ├─ pyclashbot/interface/    # Python 控制台及桌面相关代码
│  ├─ pyclashbot/utils/        # 战绩、证据、持久化、运行配置与进程归属
│  ├─ scripts/                # 控制台、runner、watchdog、后端与构建入口
│  ├─ tests/                  # 离线回归和单独标记的模拟器测试
│  └─ pyproject.toml / uv.lock
├─ desktop-wpf/               # 原始 WPF 开发版
├─ desktop-portable/          # 分享版 WPF 前端及首次设置
├─ portable-backend/          # 分享版 Python 后端及依赖锁
├─ tools/                     # 构建、组装、检查工具与注明前提的历史工具
└─ docs/BUILD.md              # 编译、组装与验证边界
```

核心流程是“读取画面 → 判断状态 → 选择策略动作 → 通过 ADB 输入 → 确认结果 → 保存记录”。WPF 通过本机 JSONL 协议调用 Python 后端，后端复用控制台的启动和停止逻辑。

详细资料：[国服控制台与 567 历史](py-clash-bot/docs/cn-console-and-v4.md)、[部署区域](py-clash-bot/docs/placement-zones.md)、[运行与验证](py-clash-bot/docs/runtime-and-validation.md)、[开发约定](py-clash-bot/CONTRIBUTING.md)。其中历史文档包含原作者的本机路径和旧版验证记录；新用户上手以本文的公开路径示例为准。

客户端更新后，先对照 [图片识别维护指南](docs/VISION_MAINTENANCE.md) 检查固定尺寸、卡牌费用、模板、状态判断和运行版本。当前 `void`（虚空）目录定义仍保留 3 费；2026-10-07 的本机诊断把它列为需针对新画面核验的适配项。本次源码同步没有把它标为已经修复，也没有承诺新版游戏全面兼容。

## 验证与数据解释

在上述项目环境中运行：

```powershell
uv lock --check
uv run --locked --no-sync ruff check .
uv run --locked --no-sync ruff format --check .
uv run --locked --no-sync ty check
uv run --locked --no-sync pytest -q -p no:cacheprovider --basetemp="$repo\work\pytest"
```

默认 pytest 排除 `emulator` 测试，离线测试不会启动模拟器。`--integration` 和 `make test-emulator` 是另一条实机测试路径，会启动或重启模拟器并发出游戏输入。源码自检、离线测试、前端构建、完整包运行和实机对战应分别验证。

原始 JSONL 是对局来源，SQLite 是可重建索引。界面胜率是自动识别胜场除以全部已结算场次，未知和平局计入分母，开始但没有结算的场次不计入。截图匹配会核对内容哈希；丢失或被覆盖的截图保持证据缺失。策略统计不能直接证明某次代码修改导致胜率提升。

离线测试夹具中的图片保留了游戏画面及其中可见的游戏昵称，用于复现识别行为。它们是测试素材，不能当作公开版的胜率验收结果。作者自己的运行数据库、日志、断点与个人配置不随源码发布。

旧通用 `python -m pyclashbot` GUI、BlueStacks、Google Play Games 和 macOS 打包源码也保留在 Python 项目中；本仓库的主要维护范围是上述 Windows 中文客户端路径，其他组合需要独立验证。

## 参与改进

欢迎提交复现清晰的 Issue 与 Pull Request。问题报告最好提供入口、版本、客户端、有效分辨率、DPI、使用的策略和经过脱敏的日志；只上传复现所需的局部截图，保留未知或失败状态。

修改检测与策略时，可以先增加对应离线回归，再做自己设备上的有限实机验证。新增坐标集中放入 `bot/coords.py`，持久化与进程操作沿用已有边界。贡献源码沿用 NC-CL-1.0，素材及文档沿用 CC BY-NC-SA 4.0；应保留上游署名和修改说明。

## 许可与致谢

- 上游：[pyclashbot/py-clash-bot](https://github.com/pyclashbot/py-clash-bot)，Matthew Miglio、Martin Miglio 与贡献者。
- 本仓库公开维护与中文客户端改作：sushu0；具体新增范围见 [NOTICE](NOTICE) 与 [发布说明](RELEASE_NOTES.md)。
- 源码：**py-clash-bot Non-Commercial Copyleft License 1.0（NC-CL-1.0）**。
- 图像、识别参考素材及文档：**Creative Commons Attribution-NonCommercial-ShareAlike 4.0（CC BY-NC-SA 4.0）**。
- Clash Royale 游戏素材归 Supercell 所有，项目参考图用于画面识别；本项目并非官方项目。

公开源代码允许按许可进行非商业使用、学习、修改和再分发；商业用途应按原许可证联系权利人取得授权。完整条款见 [LICENSE](LICENSE)，第三方依赖与工具保留各自的许可。
