"""Install a verified backend for the next launch without touching the live UI."""

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(r"D:\codex\CodexWork\clash")
TASK = ROOT / "work/loss-optimization-20261004"
OUTPUT = ROOT / "outputs/loss-review-20261005"
BACKEND = ROOT / "outputs/wpf-desktop-loss-optimized-20261005/backend/ClashBackend.exe"
CONFIG = ROOT / "outputs/wpf-desktop-20261004/app/wpf-runtime.json"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


package = read(TASK / "frozen-backend-verification-stable.json")
assert package["passed"] is True
assert Path(package["backend"]["path"]) == BACKEND
assert package["checks"]["readonly_probe"]["passed"] is True
replay = read(TASK / "agent-replay/decision-replay.json")
strategy = ROOT / "py-clash-bot/pyclashbot/bot/random_deck_strategy.py"
assert hashlib.sha256(strategy.read_bytes()).hexdigest() == replay["new_source_sha256"]
test_log = (TASK / "pytest-scoped-latest.log").read_text(encoding="utf-8-sig")
assert "194 passed" in test_log and "FAILED" not in test_log
baseline = read(TASK / "deployment-baseline.json")
current = read(CONFIG)
assert current == baseline["config"], "Runtime config changed concurrently; preserve its owner"
current["backend_path"] = str(BACKEND)
temporary = CONFIG.with_suffix(".loss-review.tmp")
temporary.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
os.replace(temporary, CONFIG)
assert read(CONFIG) == current
summary = read(OUTPUT / "review-summary.json")
summary.update({
    "created_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
    "strategy_version": "random-rules-v2.4-20261004-loss-review",
    "policy_version": "random-mastery-v26-loss-review-20261004",
    "replay": replay["summary"],
    "validation": {
        "final_relevant_tests": 194, "new_rule_regressions": 31, "new_evidence_regressions": 6,
        "py_compile": "PASS", "ruff_check": "PASS", "ruff_format": "PASS", "scoped_ty": "PASS",
        "frozen_backend": "PASS", "readonly_probe": "PASS",
        "prior_full_suite": "1625 passed, 1 skipped, 15 deselected, 172 subtests; before final budget refinement",
    },
    "installation": {
        "backend": str(BACKEND), "runtime_config": str(CONFIG), "next_launch_only": True,
        "live_backend_reloaded": False, "live_robot_started_or_stopped": False,
        "desktop_window_operated_after_user_background_constraint": False,
        "rollback_config": str(TASK / "backup/wpf-runtime.json"),
    },
    "changed_project_files": [
        str(strategy), str(ROOT / "py-clash-bot/pyclashbot/bot/cn_random_mastery_loop.py"),
        str(ROOT / "py-clash-bot/tests/test_random_loss_regressions.py"),
        str(ROOT / "py-clash-bot/tests/test_cn_random_loss_evidence.py"),
    ],
})
(OUTPUT / "review-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
paths = [
    ROOT / "outputs/cn-random-mastery.jsonl", ROOT / "outputs/cn-hog-strategy.jsonl", ROOT / "outputs/cn-567-strategy.jsonl",
    strategy, ROOT / "py-clash-bot/pyclashbot/bot/cn_random_mastery_loop.py", CONFIG, BACKEND,
    OUTPUT / "all-reviewed-failures.csv", OUTPUT / "review-summary.json", TASK / "agent-replay/decision-replay.json",
    TASK / "frozen-backend-verification-stable.json",
]
manifest = [{"path": str(path), "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in paths]
(OUTPUT / "delivery-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
report = f"""失败对局全量复核与策略优化交付
完成时间：{summary['created_at']}

已逐局盘点原记录失败1928场：随机984、hog632、567312。
另有4场原记未知、历史独立复核为失败，仍单列且不改原数据库。
自动失败中的1263场结果截图保留原SHA256，全部离线重识别为失败；加4场补充合计1267张。
剩余665场缺少可核验原结果截图，保留为日志证据，不能称完整图像回放。
截图和trace均为抽样证据，没有完整连续录像，不能断言每局唯一败因。

当前随机策略已更新至v2.4，对局循环标记v26。
1. 当前唯一可执行对空牌在远端警戒和近期压力期间保留，不用于普通后场轮转或支援。
2. 根据当前可靠防守牌的费用留水，排除即将花掉的卡槽后再算未来预算；压力期间不压低预算强推重费牌。
3. 法术不登记为持续守军；敌军仍可见时重新考虑有效防守；没有有效守牌时如实等待。
4. 支援、普通轮转、闲置建筑/采集器及满水特殊解手遵守预算条件。
5. 后续抽样战斗帧及出牌前后帧按内容SHA保存，避免48槽覆盖；出牌证据带尝试编号和决策。
   此保存方式只保护新证据，无法恢复此前已覆盖的图片；磁盘占用将随保留对局增长。

历史同观测回放223场v2.3已完成对局，17819条场景、4390条出牌。
唯一对空误用36个候选中34个旧行为可严格复现，这34个全部阻断；另外2个不计入确定修复分母。
法术后错误等待5/5消除，其中4个恢复有效响应，1个确实没有有效守牌。
预算31个场景全部保留原场景所需其他守军费用，其中旧行为可复现28个；残留0。
这些是规则回归结论，不能换算为已提升的胜率。

最终相关离线测试194通过，含31个策略回归与6个证据持久性回归。
py_compile、Ruff检查/格式、相关ty检查通过；冻结包源码、编译模块、图片资源及只读探针通过。
早先全套1625测试和172子测试通过，随后最终预算修改以相关194测试补验。

新桌面后端：{BACKEND}
已修改现有wpf-runtime.json的下次启动后端路径；没有退出、重启或操控当前窗口，没有开新对局。
正在运行的程序仍保留它启动时加载的后端；用户正常退出并再次打开助手后新策略才生效。

逐局CSV：{OUTPUT / 'all-reviewed-failures.csv'}
汇总JSON：{OUTPUT / 'review-summary.json'}
原始审计和可复运行脚本：{TASK}
回放报告：{TASK / 'agent-replay/decision-replay.json'}
冻结包验证：{TASK / 'frozen-backend-verification-stable.json'}

回退：保留原导航后端，恢复 {TASK / 'backup/wpf-runtime.json'} 到现有配置后，在方便时正常重开助手。
源码回退使用backup中的原两文件，先核对仅撤销本任务差异，保留其他同步改动。
原对局日志、战绩数据库、奖励账本、历史截图未修改。
"""
(OUTPUT / "失败对局复核与策略优化报告.txt").write_text(report, encoding="utf-8-sig")
assert len(list(csv_rows := (OUTPUT / "all-reviewed-failures.csv").open(encoding="utf-8-sig"))) > 1932
print(json.dumps({"installed_for_next_launch": True, "backend": str(BACKEND), "report": str(OUTPUT / "失败对局复核与策略优化报告.txt")}, ensure_ascii=False))
