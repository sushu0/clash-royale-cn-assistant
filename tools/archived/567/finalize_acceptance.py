"""Freeze the first ten fully closed v1.3 matches, separate from ongoing play."""
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

root = Path(__file__).resolve().parents[2]
output = root / "outputs"
session = "20260928-122306"
evidence_dir = root / "work/567-validation" / session
gate = json.loads((evidence_dir / "validation-passed.json").read_text(encoding="utf-8"))
assert gate["closed_loops"] >= 10 and gate["next_battle_started"]
events = []
for line in (output / "cn-567-strategy.jsonl").read_text(encoding="utf-8").splitlines():
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        continue
    if event.get("session") == session:
        events.append(event)
ends = [r for r in events if r["event"] == "battle_end"][:10]
assert len(ends) == 10
assert [r["battle"] for r in ends] == list(range(1, 11))
assert all(r["confirmed"] > 0 for r in ends)
assert any(r["event"] == "battle_start" and r["battle"] == 11 and not r["resumed"] for r in events)
rows, tiles = [], []
for event in ends:
    evidence = event["evidence"]
    path = Path(evidence["path"])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == evidence["sha256"]
    row = {"battle": event["battle"], "result": event["result"],
           "confirmed": event["confirmed"], "attempts": event["attempts"],
           "failures": event["attempts"]-event["confirmed"]}
    for lane in ("left", "right"):
        item = event["opening_45s"][lane]
        row[lane+"_observed_loss_percent"] = (round(item["observed_loss_fraction"]*100, 1)
                                                if item["observed_loss_fraction"] is not None else None)
        row[lane+"_complete_45s"] = item["complete_45s_window"]
    rows.append(row)
    frame = cv2.imread(str(path))
    tile = cv2.resize(frame[:405], (209, 202))
    tile = cv2.copyMakeBorder(tile, 25, 0, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    label = f"#{event['battle']}  {'WIN' if event['result']=='胜利' else 'LOSS' if event['result']=='失败' else 'UNKNOWN'}"
    cv2.putText(tile, label, (5, 17), cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 0, 0), 1)
    tiles.append(tile)
sheet = np.vstack([np.hstack(tiles[:5]), np.hstack(tiles[5:])])
cv2.imwrite(str(output / "567-ten-results-audit.png"), sheet)
counts = Counter(r["result"] for r in ends)
report = {"status": "CLOSED_LOOP_VALIDATION_PASSED", "session": session,
          "policy_version": gate["policy_version"], "mode": "classic_1v1",
          "gate_time": gate["time"], "recorded_at": datetime.now().isoformat(),
          "completed": 10, "wins": counts["胜利"], "losses": counts["失败"], "unknown": counts["未知"],
          "deployment_attempts": sum(r["attempts"] for r in ends),
          "confirmed_deployments": sum(r["confirmed"] for r in ends),
          "deployment_failures": sum(r["attempts"]-r["confirmed"] for r in ends),
          "recoveries_before_gate": sum(r["event"] == "recovery" and r["time"] <= gate["time"] for r in events),
          "next_battle_start_verified": True, "result_evidence_hashes_verified": 10,
          "gate": gate, "battles": rows,
          "tower_metric_limit": "Visible princess-tower health-bar estimate only. Incomplete windows are partial observations, not full 45s losses; king tower not measured.",
          "performance_conclusion": "No effectiveness claim; continue playing regardless of losses."}
(output / "567-ten-match-acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
with (output / "567-ten-match-details.csv").open("w", encoding="utf-8-sig", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
print(json.dumps({k: report[k] for k in ("status", "completed", "wins", "losses", "unknown", "deployment_attempts", "confirmed_deployments", "deployment_failures", "recoveries_before_gate")}, ensure_ascii=False))
