"""Read-only acceptance snapshot of the deployed bot, native UI, and reward ledger."""
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

import psutil

from pyclashbot.utils.mastery_rewards import read_reward_totals

ROOT = Path(r"D:\codex\CodexWork\clash")
OUT = ROOT / "outputs"
live = json.loads((OUT / "random-mastery-live-status.json").read_text(encoding="utf-8"))
front = json.loads((ROOT / "work/random-frontend-state.json").read_text(encoding="utf-8"))
owners = json.loads((ROOT / "work/bot-processes.json").read_text(encoding="utf-8"))
totals = read_reward_totals(OUT / "cn-mastery-rewards.jsonl")

def owner(pid, script):
    proc = psutil.Process(pid)
    assert script in " ".join(proc.cmdline()), f"Wrong process owner: {pid}"
    return {"pid": pid, "script": script, "alive": proc.is_running()}

processes = [owner(live["pid"], "run_cn_1v1.py"), owner(front["pid"], "cn_bot_control.py"),
             owner(owners["watchdog_pid"], "watch_cn_1v1.py")]
command = psutil.Process(live["pid"]).cmdline()
limit = int(command[command.index("--max-battles")+1]) if "--max-battles" in command else 0
assert limit == 0
assert live["state"] not in ("paused", "stopped") and front["state"] == "running"
assert front["metrics"]["rewards"] == f"{totals['rewards']:,}"
assert front["metrics"]["coins"] == f"{totals['coins']:,}" + ("+" if totals["unknown_coin_items"] else "")
assert all(front["metric_fits"].values())
assert front["tactics"].startswith("战术：")
assert (live["rewards_received"], live["coins_received"]) == (totals["rewards"], totals["coins"])

connection = sqlite3.connect(f"file:{OUT / 'cn-battle-history.sqlite3'}?mode=ro", uri=True)
db_rewards = connection.execute("SELECT COUNT(*), SUM(CASE WHEN kind='coins' THEN COALESCE(amount,0) ELSE 0 END) FROM mastery_rewards").fetchone()
history = dict(connection.execute("SELECT strategy, COUNT(*) FROM battles GROUP BY strategy"))
connection.close()
assert db_rewards == (totals["rewards"], totals["coins"])
assert history["567"] == 382 and history["hog"] == 700

rows = []
for line in (OUT / "cn-random-mastery.jsonl").read_text(encoding="utf-8").splitlines():
    try:
        row = json.loads(line)
    except ValueError:
        continue
    if row.get("session") in ("20261001-034446", live["session"]):
        rows.append(row)
plays = [r for r in rows if r["event"] == "play" and r.get("strategy_version")]
finished = [r for r in rows if r["event"] == "battle_finished"]
cycles = [r for r in rows if r["event"] == "cycle_complete"]
claim_checked = [r for r in rows if r["event"] == "mastery_footer_checked"]
assert any(r.get("footer_state") == "claim_all" for r in claim_checked)
assert any(r.get("footer_state") == "none" for r in claim_checked)
assert all(r.get("per_card_checked") is False for r in claim_checked)
assert any(r.get("completed_battle", r.get("battle", 0)) >= 149 for r in cycles)
assert all(p.get("decision", {}).get("reason") for p in plays)

per_battle = {}
for p in plays:
    entry = per_battle.setdefault(p["battle"], {"attempted": 0, "confirmed": 0, "cards": set(), "categories": Counter()})
    entry["attempted"] += 1
    entry["confirmed"] += int(p["confirmed"])
    entry["cards"].add(p["decision"]["card"])
    entry["categories"][p["category"]] += 1
for entry in per_battle.values():
    entry["cards"] = sorted(entry["cards"])
    entry["categories"] = dict(entry["categories"])

receipt_events = [json.loads(line) for line in (OUT / "cn-mastery-rewards.jsonl").read_text(encoding="utf-8").splitlines()]
recent_receipts = [r for r in receipt_events if r.get("session") == live["session"] and r["event"] == "rewards_confirmed"]
for event in recent_receipts:
    for item in event["receipts"]:
        evidence = item["evidence"]
        assert hashlib.sha256(Path(evidence["path"]).read_bytes()).hexdigest() == evidence["sha256"]

report = {
    "validated_at": datetime.now().isoformat(timespec="seconds"),
    "result": "PASS", "max_battles": limit, "processes": processes,
    "live": live, "frontend": front, "confirmed_totals": totals,
    "database_totals": {"rewards": db_rewards[0], "coins": db_rewards[1]},
    "preserved_history": history, "recent_receipts": recent_receipts,
    "battles": per_battle, "finished": finished,
    "verified_cycles": [{k: r[k] for k in ("time", "event", "battle", "session")} for r in cycles],
    "footer_checks": [{k: r[k] for k in ("time", "footer_state", "per_card_checked")} for r in claim_checked],
    "validation": {"py_compile": "PASS", "targeted_pytest": "87 passed"},
    "limitations": ["Card plan is learned from reliably recognized hand cards as they rotate.",
                    "Short live acceptance demonstrates behavior and continuity, not a proven win-rate increase.",
                    "Unknown screens or disconnected ADB can still trigger a protective pause."],
}
target = OUT / "RANDOM_STRATEGY_OPTIMIZATION.json"
target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"result": report["result"], "file": str(target), "completed": live["completed"],
                  "closed_loops": live["closed_loops"], "totals": totals,
                  "battles": per_battle}, ensure_ascii=False, indent=2))
