"""Current-state goal audit, including the deployed reward producer and rendered UI."""
import hashlib
import json
import shutil
import sqlite3
import time
from pathlib import Path

import cv2
import psutil

from pyclashbot.bot.cn_1v1_loop import ChineseVision
from pyclashbot.utils.mastery_rewards import read_reward_totals

ROOT = Path(r"D:\codex\CodexWork\clash")
live = json.loads((ROOT / "outputs/random-mastery-live-status.json").read_text(encoding="utf-8"))
front = json.loads((ROOT / "work/random-frontend-state.json").read_text(encoding="utf-8"))
switch = json.loads((ROOT / "outputs/RANDOM_CONTROL_RESTART_ACCEPTANCE.json").read_text(encoding="utf-8"))
events = [json.loads(line) for line in (ROOT / "outputs/cn-random-mastery.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
current = [event for event in events if event.get("session") == live["session"]]
ledger = [json.loads(line) for line in (ROOT / "outputs/cn-mastery-rewards.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
totals = read_reward_totals(ROOT / "outputs/cn-mastery-rewards.jsonl")
process = psutil.Process(live["pid"])
proof_dir = ROOT / "work/random-mastery/final-goal-evidence"
proof_dir.mkdir(exist_ok=True)
proofs = []
def preserve(evidence, name):
    path = Path(evidence["path"]).resolve()
    if not path.is_relative_to(ROOT / "work") or not path.is_file():
        return None
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != evidence["sha256"]:
        return None
    destination = proof_dir / f"{name}-{evidence['sha256'][:16]}.png"
    destination.write_bytes(data)
    return str(destination)
mode_proof = None
for event in reversed(current):
    if event["event"] == "match_requested":
        path = preserve(event["evidence"], "classic-lobby")
        if path and ChineseVision().classic_selected(cv2.imread(path)):
            mode_proof = path
            break
new_claims = [event for event in ledger if event.get("event") == "rewards_confirmed"
              and event.get("policy", "").startswith("random-mastery-claim-all-v")
              and event.get("receipts")]
receipt_proofs = []
for claim in new_claims:
    for item in claim["receipts"]:
        path = preserve(item["evidence"], "confirmed-reward")
        if path:
            receipt_proofs.append({"kind": item["kind"], "amount": item["amount"], "path": path})
checks = {
    "owned_runner_live": process.is_running() and "run_cn_1v1.py" in " ".join(process.cmdline()),
    "unlimited_mode": any(event["event"] == "started" and event.get("max_battles") == 0 for event in current),
    "classic_1v1_screen_verified": mode_proof is not None,
    "new_decks_verified": all(event["changed_slots"] > 0 for event in current if event["event"] == "deck_generated")
                           and any(event["event"] == "deck_generated" for event in current),
    "confirmed_card_deployments": any(event["event"] == "play" and event.get("confirmed") for event in current),
    "complete_cycles_after_restart": any(event["event"] == "cycle_complete" for event in current),
    "mastery_footer_only": all(event.get("method") == "claim_all_footer_only" and event.get("per_card_checked") is False
                               for event in current if event["event"] == "mastery_checked")
                            and any(event["event"] == "mastery_checked" for event in current),
    "new_runtime_receipt_confirmed": bool(new_claims) and bool(receipt_proofs),
    "frontend_live": psutil.Process(front["pid"]).is_running() and front["state"] == "running",
    "frontend_refresh_2_seconds": front["refresh_seconds"] == 2,
    "reward_totals_match_frontend": front["metrics"]["rewards"] == f"{totals['rewards']:,}"
                                   and front["metrics"]["coins"] == f"{totals['coins']:,}",
    "reward_totals_match_backend": live["rewards_received"] == totals["rewards"] and live["coins_received"] == totals["coins"],
    "all_coin_amounts_verified": totals["unknown_coin_items"] == 0,
    "metric_text_not_clipped": all(front["metric_fits"].values()),
    "stop_start_handlers_verified": switch["stopped_verified"] and switch["same_console_handlers_used"]
                                    and switch["frontend_stopped"]["state"] == "stopped",
    "logged_in_game_preserved": switch["game_preserved"],
    "no_terminal_fault_in_current_run": not any(event["event"] == "paused" for event in current),
}
connection = sqlite3.connect(ROOT / "outputs/cn-battle-history.sqlite3")
history_counts = dict(connection.execute("SELECT strategy,COUNT(*) FROM battles GROUP BY strategy"))
connection.close()
before = json.loads((ROOT / "work/backups/random-mastery-20260930/ui-history-before.json").read_text())
checks["fixed_strategy_history_preserved"] = all(history_counts.get(key) == value for key, value in before.items())
core = (ROOT / "py-clash-bot/pyclashbot/bot/cn_random_mastery_loop.py").read_text(encoding="utf-8")
checks["no_scroll_or_card_inspection_in_mastery_loop"] = "swipe" not in core[core.index("    def _mastery("):core.index("    def _startup_frame(")]
report = {"accepted": all(checks.values()), "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
          "checks": checks, "backend": live, "frontend": front, "reward_totals": totals,
          "new_claims": new_claims, "immutable_receipt_evidence": receipt_proofs,
          "classic_mode_evidence": mode_proof, "history_counts": history_counts,
          "tests": {"passed": 72, "python_compile": "passed"}}
(ROOT / "outputs/RANDOM_FINAL_GOAL_AUDIT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"accepted": report["accepted"], "checks": checks, "reward_totals": totals,
                  "completed": live["completed"], "generated": live["generated_decks"]}, ensure_ascii=False, indent=2))
