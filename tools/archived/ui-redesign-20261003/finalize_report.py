"""Persist the design acceptance record without changing robot state."""

import ast
import difflib
import hashlib
import json
from pathlib import Path

TASK = Path(r"D:\codex\CodexWork\clash")
REPO = TASK / "py-clash-bot"
WORK = TASK / "work" / "ui-redesign-20261003"
OUTPUTS = TASK / "outputs"
source = REPO / "scripts" / "cn_bot_control.py"
theme = REPO / "pyclashbot" / "interface" / "cn_console_theme.py"
backup = WORK / "cn_bot_control.before.py"
before_text = backup.read_text(encoding="utf-8")
after_text = source.read_text(encoding="utf-8")
before = ast.parse(before_text)
after = ast.parse(after_text)


def method(tree, name):
    control = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ControlWindow")
    return ast.dump(next(node for node in control.body if isinstance(node, ast.FunctionDef) and node.name == name))


unchanged = {name: method(before, name) == method(after, name) for name in (
    "_start", "_stop", "_action", "_start_worker", "_stop_worker", "_history_worker", "_on_close", "_open_result",
)}
assert all(unchanged.values()), unchanged
qa = json.loads((WORK / "qa" / "validation.json").read_text(encoding="utf-8"))
assert qa["passed"]
live = json.loads((TASK / "work" / "random-frontend-state.json").read_text(encoding="utf-8"))
assert live["state"] == "running"
assert live["hero_content_fits"] and all(live["metric_fits"].values())
files = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (source, theme, backup)}
rollback = {"restore": [{"backup": str(backup), "target": str(source), "sha256": files[str(backup)]}],
            "new_module": str(theme), "note": "Close only the console window, restore the source, then reopen the console. The unused theme module can remain; do not reset the repository or stop robot workers."}
(WORK / "rollback.json").write_text(json.dumps(rollback, ensure_ascii=False, indent=2), encoding="utf-8")
(WORK / "console-ui.patch").write_text("".join(difflib.unified_diff(
    before_text.splitlines(keepends=True), after_text.splitlines(keepends=True),
    fromfile="scripts/cn_bot_control.py (before)", tofile="scripts/cn_bot_control.py (after)")), encoding="utf-8")
acceptance = {"qa": qa, "existing_tests": {"passed": 39, "failed": 0}, "ruff": "passed",
              "py_compile": "passed", "live_at_acceptance": live, "behavior_methods_unchanged": unchanged,
              "sha256": files, "screenshot": str(OUTPUTS / "console-redesign-live.jpg"),
              "screenshot_method": "Windows Computer Use get_window_state; returned JPEG saved unchanged",
              "gui_observed": ["Three sidebar pages switch", "Record selection enables evidence button", "Robot remains running while settlements and rewards increase"],
              "fidelity_checked": ["sidebar and content grid", "palette", "heading and metric hierarchy", "grouped statistics", "reward panel", "result-only semantic colors", "source note and small-window fit"]}
(OUTPUTS / "console-redesign-validation.json").write_text(json.dumps(acceptance, ensure_ascii=False, indent=2), encoding="utf-8")
report = f'''# 皇室战争控制台：新版验收记录

新版已经写入实际入口 `scripts/cn_bot_control.py` 并打开正式窗口。后台机器人在验收期间持续运行；旧界面窗口和安全预览已关闭。此轮没有停止或重新启动机器人。

## 修改范围

- 修改 `D:\\codex\\CodexWork\\clash\\py-clash-bot\\scripts\\cn_bot_control.py`：将排版分为独立的侧栏、页头、运行摘要、战绩、奖励、详情和页脚构建方法；保留原数据接口与回调。
- 新增 `D:\\codex\\CodexWork\\clash\\py-clash-bot\\pyclashbot\\interface\\cn_console_theme.py`：统一颜色与原生圆角容器、按钮、趋势块、结果标签。
- 机器人策略、游戏识别、模拟器、历史日志与胜率定义均沿用原有实现。原仓库已有修改没有重置或提交。

## 验证结果

| 验证 | 结果 |
| --- | --- |
| 项目 Python 3.12 的 `-m py_compile`，两个源文件 | 通过 |
| 项目规则的 Ruff check，两个源文件 | 通过；中文界面文件明确允许全角中文标点 |
| `test_cn_control_random.py`、`test_battle_history.py`、`test_mastery_rewards.py` | 39 项通过 |
| 独立冻结历史索引的界面 QA | {qa['passed_count']} / {qa['check_count']} 通过 |
| 四个战绩范围、七项指标、三页面、按钮状态、选择/滚动、日志 | 通过 |
| 未核实金币显示与隐藏，结果标签点选/双击/滚轮 | 通过 |
| 1440×960、1280×900、较小窗口、1920×991 最大化 | 通过；最小客户区为 1080×840，小于最小值的请求由窗口限制 |
| 窗口与父容器边界、主摘要、指标宽度、统计口径说明 | 通过 |
| 测试进程对生产文件的写入或外部动作尝试 | 0 次；按钮测试使用 spy/stub |
| Windows 正式窗口观察 | 三页切换正常；选中记录后查看结算图按钮启用 |
| 启停、后台索引、关闭、结算图验证相关 8 个方法的 AST 与备份比较 | 全部一致 |

QA 报告在 `work/ui-redesign-20261003/qa/validation.json`，独立验证脚本在同一任务工作目录的 `validate_console.py`。正式截图是 Windows 工具返回的 JPEG，原样保存，不进行图片修饰。

## 实际运行证据

截至诊断时间 `{live['updated_at']}`，控制台进程为 `{live['pid']}`，机器人状态为 `{live['state']}`，当前阶段为“{live['phase']}”。累计已结算 `{live['metrics']['total']}`；累计奖励 `{live['metrics']['rewards']}`；累计金币 `{live['metrics']['coins']}`。这些是实时快照，后续会继续变化，不作为固定展示值。验收期间结算数从 810 增加到 811，领奖次数和金币也增长。

## 设计参考对照

已使用 `view_image` 同次查看 `console-design-concept.png` 和最新正式窗口 `console-redesign-live.jpg`，核对以下七个维度：

| 维度 | 实现与调整 |
| --- | --- |
| 主布局 | 墨绿侧栏与浅色内容；原三页导航；页面内容共享左边界 |
| 配色 | 统一品牌、文字、边界与状态色；删除整行红绿正文 |
| 层级 | 页面标题、运行阶段、指标数字、标签与解释具有固定等级 |
| 指标组织 | 同一战绩区域放五项指标；两个奖励指标独立成组 |
| 表格 | 使用真实记录、独立结果标签、浅色选择背景；1440×960 下可见五个完整结果标签 |
| 空间 | 修复奖励区撑高、表格说明被挤掉、底部半行标签；较小窗口使用更紧的边距 |
| 交互 | 保留现有功能；修复覆盖标签的滚轮转发和选中背景刷新；键盘支持 Tab/Enter/空格及 Ctrl+1/2/3 |

文案对照遵循现有真实状态与设计参考的字段。新增可见文字仅为原页面标题、分组名与必要状态说明；没有加入新产品功能或虚构数据。与参考图的有意差异包括：Windows 系统标题栏、实时数值与完整策略文案、原生控件字体与 DPI 渲染、金币金额待核实说明、滚动条及小窗口同时显示行数。图像生成参考是静态设计稿，实际界面全部由代码实现。

内置浏览器因缺少组件未用于本次验收；这是原生 Tk 应用，因此使用 Windows 窗口截图与原生控件检查验证，不使用网页或 Playwright 冒充桌面运行证据。在线设计资料与书籍查看范围见 `console-design-research.md`。

## 回退

只需关闭控制台窗口，将 `D:\\codex\\CodexWork\\clash\\work\\ui-redesign-20261003\\cn_bot_control.before.py` 复制回 `D:\\codex\\CodexWork\\clash\\py-clash-bot\\scripts\\cn_bot_control.py`，再用项目现有 Python 打开控制台。新增主题模块可以保留，旧入口不导入它。关闭控制台不停止机器人；不要点击“停止机器人”或重置整个仓库。

备份与映射在 `work/ui-redesign-20261003/rollback.json`；仅入口文件的修改差异在 `console-ui.patch`。SHA-256 已保存到同目录交付的 `console-redesign-validation.json`。
'''
(OUTPUTS / "console-redesign-validation.md").write_text(report, encoding="utf-8")
print(json.dumps({"passed": True, "qa_checks": qa["check_count"], "state": live["state"],
                  "report": str(OUTPUTS / "console-redesign-validation.md"), "methods_unchanged": unchanged}, ensure_ascii=False))
