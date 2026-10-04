# 构建与验证

本仓库有 Python 控制台、原始 WPF 开发版和分享版 WPF 前端。构建前请先阅读 [根 README](../README.md) 的客户端、模拟器、许可和运行范围。

## 环境

| 工具 | 用途 |
| --- | --- |
| Windows 64 位 | WPF 桌面、Windows 冻结构建与当前中文客户端路径 |
| Python 3.12 | Python 项目唯一声明支持的主次版本范围 |
| uv | 按 `pyproject.toml` 和 `uv.lock` 同步依赖与开发工具 |
| .NET 10 SDK | 两个 WPF 项目当前均为 `net10.0-windows`；.NET 8 SDK 不能直接构建这个目标 |
| MEmu / ADB / 腾讯国服游戏 | 实机运行时自行配置，构建和离线测试本身不需要开始游戏 |

下面示例假设仓库克隆到 `D:\codex\projects\clash-royale-cn-assistant`，已安装 Git、uv 和 .NET 10 SDK，并在普通 PowerShell 中可找到它们。构建过程可以下载锁文件中声明的依赖；不需要原作者的 `Initialize-CodexEnvironment.ps1`。

## 独立构建目录

```powershell
Set-Location -LiteralPath 'D:\codex\projects\clash-royale-cn-assistant'
$repo = (Get-Location).Path
New-Item -ItemType Directory -Force -Path "$repo\work\temp", "$repo\outputs" | Out-Null
$env:TEMP = "$repo\work\temp"
$env:TMP = $env:TEMP
$env:UV_CACHE_DIR = "$repo\work\uv-cache"
$env:UV_PYTHON_INSTALL_DIR = "$repo\work\python"
$env:NUGET_PACKAGES = "$repo\work\nuget-packages"
$env:DOTNET_CLI_HOME = "$repo\work\dotnet-cli"
Set-Location -LiteralPath "$repo\py-clash-bot"
uv sync --locked --group build --python 3.12
uv lock --check
```

`--locked` 不会默默重生成依赖锁。同步后的 `.venv` 是项目环境，runner 的 JSON 配置应选择这个解释器。已有机器上运行中的机器人使用什么环境，应先查清后再独立构建，避免覆盖它的依赖。

## 原始 Python 桌面包

冻结脚本的输出与工作目录明确要求在 `D:\codex` 下：

```powershell
$env:PYCLASHBOT_DESKTOP_OUTPUT = "$repo\outputs\python-desktop"
$env:PYCLASHBOT_DESKTOP_WORK = "$repo\work\python-desktop-build"
uv run --locked --no-sync python scripts/build_cn_desktop.py build_exe
```

生成的是包含 Python 运行时、识别素材和对应源码的 `ClashAssistant.exe` 目录包。该入口是 Python 桌面壳，不是 WPF 前端。不要只复制单个 exe；保留它旁边的依赖与资源。

可以校验包内资源，结果文件放在构建目录中：

```powershell
& "$repo\outputs\python-desktop\ClashAssistant.exe" --self-check --self-check-output "$repo\outputs\python-desktop-self-check.json"
Get-Content -LiteralPath "$repo\outputs\python-desktop-self-check.json"
```

资源自检不连接 ADB、不启动 VM、不发出游戏输入。普通运行数据依旧要求位于 `D:\codex`。源码的 `scripts/setup_msi.py` 还保留 Windows MSI 构建，macOS 的 `scripts/setup_macos.py` 保留旧通用 GUI 打包；它们与分享版 WPF 应分别验证。

## 原始 WPF 开发版

先构建 Python JSONL 后端，输出位于 `backend`，然后把 WPF 前端发布到同一级的 `app`：

```powershell
# 当前目录为仓库中的 py-clash-bot。
$env:PYCLASHBOT_WPF_BACKEND_OUTPUT = "$repo\outputs\wpf\backend"
$env:PYCLASHBOT_WPF_BACKEND_WORK = "$repo\work\wpf-backend-build"
uv run --locked --no-sync python scripts/build_wpf_backend.py build_exe

Set-Location -LiteralPath $repo
dotnet publish .\desktop-wpf\ClashAssistant.Desktop.csproj -c Release -r win-x64 --self-contained true -o "$repo\outputs\wpf\app"
```

目标结构为：

```text
outputs/wpf/
├─ app/       # ClashAssistant.Desktop.exe、wpf-runtime.json 和 .NET 组件
└─ backend/   # ClashBackend.exe、lib、scripts、source、assets 和识别资源
```

`app/wpf-runtime.json` 的 `backend_path` 默认为 `../backend/ClashBackend.exe`。其 `data_root` 必须是 `D:\codex` 下的运行目录。为该数据根提供 `work/runtime-config.json`，填写自己的 ADB、MEmu 和设备地址。冻结后端调度自己，不需要 JSON 的外部 `python` 字段。

原始 WPF 的前端和后端程序路径也要求在 `D:\codex` 下。只修改 `wpf-runtime.json` 为另一个盘符不会解除这些代码中的检查。

## 从源码构建完整分享版

`desktop-portable/` 从原始桌面版扩展了 `DesktopSettings` 和 `SetupWindow`。运行时 `distribution: true`，配置中使用相对路径：

```json
{
  "distribution": true,
  "data_root": "../data",
  "backend_path": "../backend/ClashBackend.exe"
}
```

分享版 Python 后端位于 `portable-backend/`，保留独立依赖锁和安装目录内的数据路径实现。它与 `desktop-portable/` 一起由 `tools/build_portable.py` 组装。仓库根目录运行：

```powershell
Set-Location -LiteralPath $repo
uv run --project portable-backend --locked --group build python tools/build_portable.py --dotnet dotnet
```

默认构建工作目录为 `.build/portable`，完整产物位于 `dist/portable`：

```text
dist/portable/
├─ app/       # WPF 前端
├─ backend/   # Python 冻结后端、运行时、识别资源和对应源码
└─ data/      # 当前安装的运行数据根，初始不带作者的运行历史
```

可以先检查源码、资源和构建工具条件：

```powershell
uv run --project portable-backend --locked --group build python tools/build_portable.py --check --dotnet dotnet
```

`--check` 检查源码、资源与工具，不开始游戏或生成完整应用；uv 仍可能按锁安装该项目的构建依赖。真正的构建还需要走上面的完整命令。当前发布源码的构建结果应以对应验证记录为准，单独的条件检查不代表完整构建已通过。

`desktop-portable/Assets/` 中的两个桌面图标是项目资源。分享版使用安装目录的 `data` 保存配置、临时文件、日志和对局证据，不把原作者的个人运行状态作为默认配置。打开 `dist/portable/app/ClashAssistant.Desktop.exe` 后，首次运行自动打开设置窗口；`--setup` 也能重新打开设置。在设置中选择自己已经安装的 ADB 和 MEmu，首次设置和“检测环境”均不启动后端战斗任务。

如果只想编译前端，可以运行 `dotnet publish .\desktop-portable\ClashAssistant.Desktop.csproj -c Release -r win-x64 --self-contained true -o "$repo\outputs\portable-frontend"`。这只产生前端，不能替代完整构建。原始 `py-clash-bot/scripts/build_wpf_backend.py` 生成的后端仍有 `D:\codex` 检查；分享版必须使用与它匹配的 `portable-backend/`。

历史工具中的 `prepare_backend.py` 记录了对旧冻结包的改造方法，其输入是已组装的冻结后端，且可能带原作者的构建路径与工具前提。新用户应从当前分享版源码和 `tools/build_portable.py` 开始。安装器源码用于包装已经组装好的 payload，也不能代替前端、后端和资源的构建。

## 验证层次

1. **源码与依赖**：`uv lock --check`、Ruff、ty、默认离线 pytest。
2. **资源**：Python 桌面包的 `--self-check`，确认参考模板、OCR 脚本和环境身份。
3. **前端与后端连接**：核对完整目录、相对路径和只读快照；`--preview` 使用只读后端，不允许开始或停止任务。
4. **本机运行**：自行设置 MEmu 0 号实例、419 × 633 / 160 DPI、腾讯版游戏与设备地址，分别观察启动、对局、结算、奖励、暂停和停止确认。

每一层只能证明它实际检查的内容。离线测试通过不能替代冻结包检查；包能打开不能替代实机闭环；短期对局不能证明长期胜率。

分享版的 `--settings-check` 读取路径设置并结束，不创建主界面或开始任务；它只校验设置，并不证明后端资源或设备可用。源码目前将 `--settings-check-output` 的结果文件限制在 `D:\codex` 下，这是开发验证接口的单独限制，普通分享版运行与首次设置仍使用安装目录。无输出文件的 WinExe 调用可能没有可见终端输出。

## 回退与自己的数据

需要回退时，先在界面停止任务，确认对应进程结束，再切换到此前保存的完整程序目录和依赖环境。保留自己的 `data` 或原始运行数据根中的 `work`、`outputs`，不要清空历史、断点、奖励收据与结算截图。SQLite 索引可从原始 JSONL 重建，丢失的截图像素无法用哈希恢复。

构建工具会生成新的工作目录与产物，清理前先确认不是自己的运行目录。公开源码中的历史文档可能记录了原作者的绝对路径；它们用于理解当时的实验，不是新用户必须复制的安装位置。
