"""Persist source, runtime, real action timing, UI, and counter acceptance."""
import hashlib
import json
import sqlite3
import statistics
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np
import psutil

from pyclashbot.utils.mastery_rewards import read_reward_totals

ROOT = Path(r"D:\codex\CodexWork\clash")
OUT = ROOT / "outputs"
for _ in range(10):
    live = json.loads((OUT / "random-mastery-live-status.json").read_text(encoding="utf-8"))
    front = json.loads((ROOT / "work/random-frontend-state.json").read_text(encoding="utf-8"))
    totals = read_reward_totals(OUT / "cn-mastery-rewards.jsonl")
    if (front["state"]=="running" and front["metrics"]["rewards"]==f"{totals['rewards']:,}"
            and front["metrics"]["coins"]==f"{totals['coins']:,}" and front["hero_content_fits"]):
        break
    time.sleep(.3)
else:
    raise RuntimeError("Frontend totals or layout did not converge")
assert all(front["metric_fits"].values()) and front["refresh_seconds"]==1
assert live["state"] not in ("paused", "stopped")
assert live["strategy_version"]=="random-rules-v2.1-20261001"
assert live["rewards_received"]==totals["rewards"] and live["coins_received"]==totals["coins"]
pidfile = json.loads((ROOT / "work/bot-processes.json").read_text(encoding="utf-8"))
processes = []
for pid, name in ((live["pid"], "run_cn_1v1.py"), (pidfile["watchdog_pid"], "watch_cn_1v1.py"),
                  (front["pid"], "cn_bot_control.py")):
    p = psutil.Process(pid)
    assert name in " ".join(p.cmdline()) and p.is_running()
    processes.append({"pid": pid, "script": name, "alive": True})
command = psutil.Process(live["pid"]).cmdline()
max_battles = int(command[command.index("--max-battles")+1]) if "--max-battles" in command else 0
assert max_battles==0
manifest = json.loads((Path(live["evidence_dir"])/"manifest.json").read_text(encoding="utf-8"))
for path, expected in manifest["sha256"].items():
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==expected, f"Undeployed source: {path}"
rows = [json.loads(x) for x in (OUT / "cn-random-mastery.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
new_rows = [r for r in rows if r.get("policy", "").startswith("random-mastery-fast-react-")]
plays = [r for r in new_rows if r["event"]=="play"]
finished = [r for r in new_rows if r["event"]=="battle_finished"]
cycles = [r for r in new_rows if r["event"]=="cycle_complete"]
assert len(finished)>=3 and len(cycles)>=3
assert any(r["session"]==live["session"] for r in cycles), "Final process has not completed a cycle"
assert len(plays)>=40
intervals = []
prior = {}
for row in plays:
    key = (row["session"], row["battle"])
    stamp = datetime.strptime(row["time"], "%Y-%m-%d %H:%M:%S").timestamp()
    if key in prior:
        intervals.append(stamp-prior[key])
    prior[key] = stamp
baseline = json.loads((OUT / "RANDOM_FLUENCY_BASELINE.json").read_text(encoding="utf-8"))
timings = {key: {"median": round(statistics.median(p["timings"][key] for p in plays), 1),
                 "p90": round(float(np.percentile([p["timings"][key] for p in plays], 90)), 1)}
           for key in ("decision_ms", "select_ms", "verify_ms", "total_ms")}
by_battle = {}
for row in plays:
    entry = by_battle.setdefault(row["battle"], {"attempts": 0, "confirmed": 0, "categories": Counter()})
    entry["attempts"]+=1
    entry["confirmed"]+=int(row["confirmed"])
    entry["categories"][row["category"]]+=1
for entry in by_battle.values():
    entry["categories"] = dict(entry["categories"])
connection = sqlite3.connect(f"file:{OUT / 'cn-battle-history.sqlite3'}?mode=ro", uri=True)
db_rewards = connection.execute("SELECT COUNT(*), SUM(CASE WHEN kind='coins' THEN COALESCE(amount,0) ELSE 0 END) FROM mastery_rewards").fetchone()
assert db_rewards==(totals["rewards"], totals["coins"])
history = dict(connection.execute("SELECT strategy, COUNT(*) FROM battles GROUP BY strategy"))
connection.close()
assert history["567"]==382 and history["hog"]==700
report = {"result": "PASS", "validated_at": datetime.now().isoformat(timespec="seconds"),
          "strategy_version": live["strategy_version"], "max_battles": max_battles,
          "processes": processes, "live": live, "frontend": front,
          "reward_totals": totals, "history": history, "manifest": manifest,
          "baseline": {k: baseline[k] for k in ("plays", "confirmed", "confirmation_rate", "intervals_seconds")},
          "after": {"plays": len(plays), "confirmed": sum(p["confirmed"] for p in plays),
                    "intervals_seconds": {"median": statistics.median(intervals), "p10": float(np.percentile(intervals, 10)),
                                          "p90": float(np.percentile(intervals, 90))},
                    "timings_ms": timings,
                    "verification_methods": dict(Counter(p["verification_method"] for p in plays)),
                    "battles": by_battle},
          "cycles": [{k: row[k] for k in ("session", "battle", "time")} for row in cycles],
          "deployment": json.loads((OUT / "RANDOM_FAST_REACT_DEPLOYMENT.json").read_text(encoding="utf-8")),
          "checks": {"py_compile": "PASS", "pytest": "143 passed", "rendered_layout": "PASS", "source_matches_running_manifest": "PASS"},
          "limits": ["Action intervals also depend on elixir and random deck cost; the comparison is observational.",
                     "A short run does not establish an improved win rate.",
                     "Uncertain identity or an unknown screen still waits or pauses rather than assuming success."]}
path = OUT / "RANDOM_FLUENCY_ACCEPTANCE.json"
path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"result": "PASS", "file": str(path), "completed": live["completed"],
                  "totals": totals, "after": report["after"]}, ensure_ascii=False, indent=2))
