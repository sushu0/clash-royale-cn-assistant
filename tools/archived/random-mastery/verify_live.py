"""Verify chronological real events rather than process existence alone."""
import hashlib
import json
from pathlib import Path

import psutil

ROOT = Path(r"D:\codex\CodexWork\clash")
trace = ROOT / "outputs" / "cn-random-mastery.jsonl"
events = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines() if line.strip()]
status = json.loads((ROOT / "outputs/random-mastery-live-status.json").read_text(encoding="utf-8"))
checks = {}
checks["actual_deck_changed"] = any(e["event"] == "deck_generated" and e["changed_slots"] > 0 for e in events)
finished_index = next((i for i, e in enumerate(events) if e["event"] == "battle_finished" and e["cards_confirmed"] > 0), None)
checks["completed_battle_with_confirmed_cards"] = finished_index is not None
after = events[finished_index+1:] if finished_index is not None else []
checks["returned_lobby_after_result"] = any(e["event"] == "returned_lobby" for e in after)
mastery_index = next((i for i, e in enumerate(after) if e["event"] == "mastery_checked" and e.get("method") == "claim_all_footer_only" and e.get("no_rewards_remaining") and not e.get("per_card_checked")), None)
checks["mastery_claim_all_footer_checked"] = mastery_index is not None
tail = after[mastery_index+1:] if mastery_index is not None else []
checks["closed_cycle"] = any(e["event"] == "cycle_complete" for e in tail)
new_deck_index = next((i for i, e in enumerate(tail) if e["event"] == "deck_generated"), None)
checks["next_deck_generated"] = new_deck_index is not None
next_events = tail[new_deck_index+1:] if new_deck_index is not None else []
checks["next_battle_started"] = any(e["event"] == "battle_started" for e in next_events)
try:
    process = psutil.Process(status["pid"])
    alive = process.is_running() and "run_cn_1v1.py" in " ".join(process.cmdline())
except psutil.Error:
    alive = False
checks["verified_process_running"] = alive and status["state"] not in ("paused", "stopped")
checks["unlimited_mode"] = any(e["event"] == "started" and e.get("max_battles") == 0 and e["session"] == status["session"] for e in events)
verified_evidence = []
for e in events:
    if e["event"] not in ("deck_generated", "battle_finished", "mastery_checked", "battle_started"):
        continue
    for key in ("evidence", "evidence_before", "evidence_after"):
        item = e.get(key)
        if not item:
            continue
        path = Path(item["path"])
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]:
            verified_evidence.append({"event": e["event"], "time": e["time"], **item})
claims = [e for e in events if e["event"] == "claim_all_confirmed"]
report = {
    "accepted": all(checks.values()), "checks": checks, "live_status": status,
    "completed_battles": [e for e in events if e["event"] == "battle_finished"],
    "mastery_checks": [e for e in events if e["event"] == "mastery_checked"],
    "actual_claim_all_confirmations": len(claims), "live_reward_claim_branch_verified": bool(claims),
    "limitation": "No live claim-all confirmation unless actual_claim_all_confirmations is positive. Unknown claim popups pause without recording success.",
    "verified_evidence": verified_evidence,
    "repairs": [e for e in events if e["event"] == "paused"],
}
path = ROOT / "outputs" / "RANDOM_MASTERY_ACCEPTANCE.json"
path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"accepted": report["accepted"], "checks": checks,
                  "claimed": len(claims), "verified_evidence_count": len(verified_evidence)}, ensure_ascii=False, indent=2))
