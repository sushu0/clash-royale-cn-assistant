"""Freeze equal-size first-ten results plus the complete v1.3 baseline."""
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
baseline = "20260928-122306"
candidate = "20260928-134106"
gate_path = root / "work/567-validation" / candidate / "validation-passed.json"
assert gate_path.is_file(), "Candidate's ten-loop gate is still pending"
gate = json.loads(gate_path.read_text(encoding="utf-8"))
assert gate["closed_loops"] >= 10 and gate["next_battle_started"]
events = []
for line in (output / "cn-567-strategy.jsonl").read_text(encoding="utf-8").splitlines():
    try:
        events.append(json.loads(line))
    except json.JSONDecodeError:
        continue


def summarize(session, count):
    rows = [r for r in events if r.get("session") == session]
    ends = [r for r in rows if r["event"] == "battle_end"][:count]
    assert len(ends) == count and [r["battle"] for r in ends] == list(range(1, count+1))
    scores = Counter(r["result"] for r in ends)
    for row in ends:
        evidence = row["evidence"]
        assert hashlib.sha256(Path(evidence["path"]).read_bytes()).hexdigest() == evidence["sha256"]
    observations = [r for r in rows if r["event"] == "observe" and r["battle"] <= count]
    full_pressure = [r for r in observations if r.get("cues", {}).get("elixir") == 10
                     and r.get("policy_observation", {}).get("pressure")]
    return {"session": session, "count": count, "wins": scores["胜利"], "losses": scores["失败"],
            "unknown": count-scores["胜利"]-scores["失败"], "wins_per_completed": scores["胜利"]/count,
            "attempts": sum(r["attempts"] for r in ends), "confirmed": sum(r["confirmed"] for r in ends),
            "unconfirmed": sum(r["attempts"]-r["confirmed"] for r in ends),
            "recoveries": sum(r["event"] == "recovery" and r["battle"] <= count for r in rows),
            "observations": len(observations), "full_elixir_pressure_observations": len(full_pressure),
            "result_evidence_hashes_verified": count, "battles": ends}


old10, old25, new10 = summarize(baseline, 10), summarize(baseline, 25), summarize(candidate, 10)
report = {"status": "FIXED_TEN_GAME_COMPARISON", "created_at": datetime.now().isoformat(),
          "baseline_first10": old10, "baseline_all25": old25, "candidate_first10": new10, "gate": gate,
          "win_rate_point_difference_first10": new10["wins_per_completed"]-old10["wins_per_completed"],
          "limitations": ["Consecutive batches, not randomized paired opponents; small samples do not establish long-term win rate.",
                          "Wait observations are sampled records, not elapsed idle time.",
                          "Tower losses use visible health-bar fractions; incomplete windows and missing reads remain explicit.",
                          "Unconfirmed deployments include one terminal-animation case and one corrupted black screenshot; no success was invented."]}
(output / "567-v2-comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
csv_rows = []
tiles = []
for row in new10["battles"]:
    item = {"battle": row["battle"], "result": row["result"], "confirmed": row["confirmed"], "attempts": row["attempts"]}
    for side in ("left", "right"):
        hp = row["opening_45s"][side]
        item[side+"_observed_loss_fraction"] = hp["observed_loss_fraction"]
        item[side+"_complete_45s_window"] = hp["complete_45s_window"]
    csv_rows.append(item)
    image = cv2.imread(row["evidence"]["path"])
    tile = cv2.copyMakeBorder(cv2.resize(image[:405], (209, 202)), 25, 0, 0, 0,
                             cv2.BORDER_CONSTANT, value=(255, 255, 255))
    text = f"#{row['battle']} {'WIN' if row['result']=='胜利' else 'LOSS' if row['result']=='失败' else 'UNKNOWN'}"
    cv2.putText(tile, text, (5, 17), cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 0, 0), 1)
    tiles.append(tile)
with (output / "567-v2-first10.csv").open("w", encoding="utf-8-sig", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=list(csv_rows[0]))
    writer.writeheader()
    writer.writerows(csv_rows)
cv2.imwrite(str(output / "567-v2-results-audit.png"), np.vstack([np.hstack(tiles[:5]), np.hstack(tiles[5:])]))
print(json.dumps({name: {k: v for k, v in data.items() if k != "battles"}
                  for name, data in (("old10", old10), ("old25", old25), ("new10", new10))}, ensure_ascii=False, indent=2))
