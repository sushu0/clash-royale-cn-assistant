# 游戏更新后的图片识别维护

本指南面向从 `main` 源码运行或参与适配的使用者。2026-10-08 同步了源码，没有更新 2026-10-05 的 Release 安装包。游戏的美术、卡牌费用、弹窗、按钮和页面布局变化，可能分别影响检测、策略和导航；拿到新源码或通过资源自检都不能证明自己的游戏版本已经兼容。

## 先确认画面和实际运行版本

当前国服画面固定为 **宽 419 × 高 633、160 DPI**，OpenCV 数组形状为 `(633, 419, 3)`，通道顺序是 **BGR**。PNG 文件本身不是“BGR 文件”；经 `cv2.imdecode(..., cv2.IMREAD_COLOR)` 读取后的数组才是 BGR。用 Pillow/RGB 处理后再计算指纹时，需要明确转换，避免同一图片得到不同特征。

截图使用已运行的 MEmu 0 号实例；ADB serial、memuc 安装目录和实例必须指向同一目标。普通 Python/原始 WPF 使用 `D:\codex` 下的数据根，分享版使用安装目录的 `data`。不要靠日期或文件名猜后端版本：核对当前前端配置的 `backend_path`、实际后端目录和 Git 提交。源码文件、冻结包中的 `source` 镜像和真正执行的字节码是不同对象。

已克隆用户先按 [README 的更新步骤](../README.md#更新已有源码) 执行 `git pull --ff-only origin main`，然后使用同一项目的 Python 3.12 与依赖锁。普通源码环境中运行：

```powershell
# 当前目录为仓库中的 py-clash-bot；$repo、$data 及运行配置见根 README。
uv sync --locked --python 3.12
uv lock --check
uv run --locked --no-sync python -m scripts.cn_windows_entry --self-check
```

`--self-check` 检查 ChineseVision 资源、手牌校准、威胁模板与 OCR 脚本，并输出环境身份；不会启动模拟器、连接 ADB 或输入游戏操作。它不是所有检测器和所有新游戏画面的兼容性测试，商店、弹窗与卡牌变化仍需对应离线回归。

## 采集一张只读截图

先主动停止机器人，手动打开目标页面。下面读取自己配置中的 ADB 和 serial，只执行 `exec-out screencap -p`，不会打开游戏、点击、滑动、购买或恢复任务。设备需事先运行并已连接；命令不会代替首次配置。

在仓库的 `py-clash-bot` 目录执行。新 shell 先恢复根 README 中的环境变量，尤其是 `PYCLASHBOT_CONFIG`：

```powershell
$config = Get-Content -LiteralPath $env:PYCLASHBOT_CONFIG -Raw | ConvertFrom-Json
$adb = $config.adb
$serial = $config.serial
$capture = "$repo\work\vision-maintenance\screen.png"

@'
import subprocess
import sys
from pathlib import Path
import cv2
import numpy as np

adb, serial, destination = sys.argv[1:]
result = subprocess.run(
    [adb, "-s", serial, "exec-out", "screencap", "-p"],
    check=True, capture_output=True, timeout=10,
)
raw = result.stdout
frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
if frame is None or frame.shape != (633, 419, 3):
    raise SystemExit("Expected a native 419x633 three-channel screenshot")
target = Path(destination)
target.parent.mkdir(parents=True, exist_ok=True)
target.write_bytes(raw)
print(target)
'@ | uv run --locked --no-sync python - "$adb" "$serial" "$capture"
```

用 Python 保存原始字节可避开不同 PowerShell 版本的二进制重定向行为。代码验证截图尺寸，不验证 DPI；DPI 需用首次设置的只读检测，或执行 `& $adb -s $serial shell wm density` 核对有效值。`shell wm size` 不带数值也是只读查询，带数值则会修改设备。

完整截图先保留在自己的 `work`。发布复现素材前检查昵称、账号信息、聊天等无关内容；测试若需要完整尺寸，应保留检测区域和几何尺寸，仅处理与识别无关的私人区域，并记录这种处理。不要把自己的运行数据库、日志、配置或整份错误档案作为公开测试夹具。

## 按问题选择源码和素材

下面路径相对于 `py-clash-bot/`；分享版有对应的 `portable-backend/` 副本。

| 现象 | 主要检查位置 | 维护重点 |
| --- | --- | --- |
| 卡牌身份、手牌费用或策略角色错误 | `pyclashbot/detection/cn_random_hand.py`、`cn_random_ui.py`、`pyclashbot/bot/card_detection.py`、`random_card_roles.py`；`reference_images/cn_random_cards/` | 将视觉识别、实际费用和角色规则分别核实；不要只修改一个成本常量就宣称模板已适配 |
| 目标或敌方单位判断异常 | `pyclashbot/detection/cn_battle_cues.py`、`cn_threats.py`；`reference_images/cn_threats/`、`cn_567_threats/`、`cn_enemy_tags/` | 原始画面、独立校准样本、颜色与多帧证据；未匹配应保持未知 |
| 新页面、返回按钮或弹窗挡住操作 | `pyclashbot/detection/cn_page_navigation.py`、`pyclashbot/bot/state_detect.py`、`nav.py`；`reference_images/cn_pages/manifest.json` | 至少两处独立页面特征、已命名返回路线与上下文限制；暗化背景不能授权点击 |
| 每日礼物、拼图或奖励未结束 | `pyclashbot/detection/cn_daily_gift.py`、`cn_puzzle_reward.py`、`pyclashbot/bot/cn_random_mastery_loop.py` | 区分入口、选择、揭晓、继续和返回状态；仅在已确认奖励上下文中输入 |
| 每日精选价格、币种或结果错误 | `pyclashbot/detection/cn_shop_daily.py`、`pyclashbot/bot/cn_shop_daily_state.py`；`reference_images/cn_shop_daily/` | 每日标题、商品位置、免费/金币/宝石、确认弹窗和结果收据分别验证；结果不确定时不重复购买 |
| 截图尺寸、坐标或输入位置不对 | `pyclashbot/bot/coords.py`、`pyclashbot/emulators/` | 固定尺寸、DPI、命名坐标和 ROI；不把未知画面修成强制点击 |

新坐标与 ROI 集中放入 `bot/coords.py`。纯检测只返回观察，不控制设备；状态、流程、预算和购买确认归 bot 层。通用 `find_image` 使用灰度匹配，无法区分只有颜色变化的状态；国服检测器还各自检查颜色、亮度、独立特征或上下文，不应统一降低阈值绕过这些条件。

**已知待核验项：虚空。** 当前 `random_card_roles.py` 的 `catalog()` 仍把 `void` 定义为 3 费，并归入法术角色；代码还保留原来的卡牌指纹。2026-10-07 本机诊断把新画面的适配列为待验证。本次同步保留该事实，没有把它标为已修复。需取得当前客户端的原生手牌截图，分别检查身份、显示费用、角色和实际部署确认，再增加回归。

## 更新模板、manifest 与哈希

先保存能够复现失败的夹具，再从原始截图裁取有独立意义的 PNG。保持原分辨率，不放大缩小，不使用全黑、全白或大块背景作为按钮证据。旧模板仍可能服务另一种合法画面，优先增加受限变体；是否替换应由反例和覆盖情况决定。

清单结构不是统一格式，按具体加载器维护：

- `cn_random_cards/hand_calibration_20261003/manifest.json` 的 `samples[].file/sha256` 对应校准图片，加载器会核对实际字节。
- `cn_threats/manifest.json` 与 `cn_567_threats/manifest.json` 是条目列表，包含 `file`、`template_sha256`、`source`、`source_sha256`、角色、阈值和锚点；567 还要求独立校准来源等字段。源截图和裁剪模板是不同文件，哈希不可混用。
- `cn_pages/manifest.json` 描述页面、独立 cues、ROI、返回路线和源图身份。加载器检查分辨率与路线/ROI 合同，并不等于为每张图执行统一的 SHA 检查；保留真实来源，并用对应测试核查。
- 商店 PNG 由 `cn_shop_daily.py` 按名称加载，当前该素材目录没有通用 manifest。测试夹具 `tests/fixtures/cn_shop_daily/` 则有 `manifest.json` 和专项清单，不要虚构一个并不存在的自动更新命令。

用实际文件计算校验值；将结果填入所属清单已有的字段，并复核引用和大小写约定：

```powershell
$source = "$repo\work\vision-maintenance\screen.png"
$template = "$repo\py-clash-bot\pyclashbot\detection\reference_images\对应目录\对应模板.png"
(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
(Get-FileHash -LiteralPath $template -Algorithm SHA256).Hash.ToLowerInvariant()
```

示例中的模板路径需要替换。`source_sha256` 应来自清单引用的源图，`template_sha256` 来自最终裁剪 PNG；重编码、匿名化或重新裁剪后都应重新计算。不要批量替换旧记录的哈希来掩盖缺图或不匹配，也不要声称仅更新 manifest 就已经修好了检测。

部分检测器会在进程内缓存清单或模板。更改后退出并重新打开正在验证的进程，确认它加载了新素材；修改磁盘文件不代表现有进程立即使用了新版本。

## 先回归失败，再观察实机

把经过复核的必要夹具放入 `tests/fixtures/<对应功能>/`，保留明确预期和来源。正例之外应包含容易混淆的反例：例如商店暗化背景、宝石确认、缺失币种、奖励数量被误读为价格、另一个页面同色按钮；导航还需覆盖动画、弹窗遮挡和只有一处页面特征的情况。

在 `py-clash-bot/` 的锁定环境中执行相关离线测试，例如：

```powershell
uv run --locked --no-sync pytest -q tests/test_cn_shop_daily_detection.py tests/test_cn_shop_daily_flow.py tests/test_shop_daily_history.py tests/test_cn_wpf_shop_today.py
uv run --locked --no-sync pytest -q tests/test_cn_learned_page_navigation.py tests/test_cn_puzzle_reward_detection.py tests/test_cn_daily_gift.py tests/test_cn_random_hand_calibration.py tests/test_cn_threats.py tests/test_cn_567_threats.py
uv run --locked --no-sync pytest -q tests/test_cn_auto_repair.py
```

按本次修改挑选相关测试，通过后再运行项目检查：

```powershell
uv lock --check
uv run --locked --no-sync ruff check .
uv run --locked --no-sync ruff format --check .
uv run --locked --no-sync ty check
uv run --locked --no-sync pytest -q -p no:cacheprovider --basetemp="$repo\work\pytest-vision"
uv run --locked --no-sync python -m scripts.cn_windows_entry --self-check
```

默认 pytest 排除 `emulator` 标记。`--integration` 和 `make test-emulator` 会启动或重启模拟器并发送游戏输入，应在自己的设备上单独决定和执行，不属于只读诊断。离线通过后，手动启动有限实机观察，检查当前画面、身份/费用、一次实际动作确认及对应流程的返回或收据；异常仍保持暂停。资源健康、进程存在和一条启动日志不能代替游戏闭环，更不能证明胜率改善。

## 同步两份后端并重构冻结程序

公开仓库的 `py-clash-bot/` 与 `portable-backend/` 是两份独立 Python 项目。共享的检测器、规则、坐标、必要参考素材和清单应同步到两边，再分别按各自 `uv.lock` 检查；分享版的安装目录数据根、Unicode 图片 I/O 和首次设置约束要保留，不能用普通版路径模块覆盖它们。现有回归和夹具位于 `py-clash-bot/tests/`，分享版没有单独的 `tests/` 目录；不要把对普通版执行的测试计作已验证分享版冻结产物。

在仓库根目录可以检查分享版资源及共享的纯识别回归。普通版的 `PYCLASHBOT_DATA_ROOT` 不能沿用给分享版；下面暂时使用分享版源码默认的仓库 `data`，将分享版放在导入路径前面，结束后恢复本 shell 原值：

```powershell
uv sync --project portable-backend --locked --group build --python 3.12
$previousDataRoot = $env:PYCLASHBOT_DATA_ROOT
$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYCLASHBOT_DATA_ROOT = "$repo\data"
    $env:PYTHONPATH = "$repo\portable-backend;$repo\py-clash-bot"
    uv run --project portable-backend --locked --no-sync python -m scripts.cn_windows_entry --self-check
    uv run --project portable-backend --locked --no-sync python -m pytest -c "$repo\py-clash-bot\pyproject.toml" --import-mode=importlib "$repo\py-clash-bot\tests\test_cn_shop_daily_detection.py" "$repo\py-clash-bot\tests\test_cn_puzzle_reward_detection.py" -q
} finally {
    $env:PYCLASHBOT_DATA_ROOT = $previousDataRoot
    $env:PYTHONPATH = $previousPythonPath
}
```

这里使用分享版 Python 环境。共享命令针对纯检测器，不把主 Python 的整个测试目录直接视为分享版套件：例如 ErrorReporter、自动修复与临时数据根的测试还受两版本不同的目录合同影响。普通版完整离线测试仍是主要开发回归。分享版还需下面的完整构建、冻结资源检查与前后端只读连接，不能借用作者正在运行的数据目录。

更新 WPF 或冻结后端时，按 [BUILD.md](BUILD.md) 的对应流程重新构建。分享版完整构建入口是：

```powershell
uv run --project portable-backend --locked --group build python tools/build_portable.py --dotnet dotnet
```

组装后复核实际 `backend` 资源和冻结自检，以及同一程序目录的前后端只读连接。不要只替换安装包 `source` 中的 `.py`，也不要把一次业务文件修补当成同时更新了 `.pyc`、入口、`library.zip` 和素材。保留旧完整程序目录及自己的 `data` 便于回退；这套构建说明供源码使用者执行，本次仓库更新没有另行生成或上传安装包。

## 暂停报告与修复辅助

错误报告在自己的 `outputs/error-reports/<事件>/` 保留 `report.json`、`report.md` 和可用的 `game.png`，用于核对当前会话和截图。图片缺失就按缺失记录，不能拿旧截图当当前故障。

`cn_auto_repair.py` 可查询本地队列状态；普通源码环境中：

```powershell
uv run --locked --no-sync python scripts/cn_auto_repair.py --data-root "$data" status
```

`status` 不修游戏；`poll` 会维护 case 和证据快照，`claim`、`finish`、`configure` 也会写修复状态，不能统称为只读命令。脚本不调用模型 API、不修源码、不部署冻结代码、不点击恢复。定时唤醒和真正修复需要使用者自己的工作流；克隆仓库不会获得作者本机的调度和授权。详见 [接口与证据合同](../py-clash-bot/docs/cn_auto_repair.md)。
