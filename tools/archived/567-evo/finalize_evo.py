"""Freeze the evolution adaptation evidence and retain every test stage."""
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
session = "20260928-155830"
stage_ids = ("20260928-152613", "20260928-153455", "20260928-155128", session)
gate_path = root / "work/567-validation" / session / "validation-passed.json"
assert gate_path.is_file()
gate = json.loads(gate_path.read_text(encoding="utf-8"))
assert gate["closed_loops"] >= 10 and gate["next_battle_started"]
all_events = []
for line in (output / "cn-567-strategy.jsonl").read_text(encoding="utf-8").splitlines():
    try:
        all_events.append(json.loads(line))
    except json.JSONDecodeError:
        continue


def stage_summary(stage, limit=None):
    events = [r for r in all_events if r.get("session") == stage]
    ends = [r for r in events if r["event"] == "battle_end"]
    if limit is not None:
        ends = ends[:limit]
        assert len(ends) == limit
    completed_ids = {r["battle"] for r in ends}
    forms = {form: {"attempts": 0, "confirmed": 0} for form in ("normal", "evolved", "uncertain")}
    for row in events:
        if row["event"] != "play" or row["battle"] not in completed_ids or row["decision"]["card"] != "bomber":
            continue
        variant = row["decision"].get("variant")
        form = "evolved" if variant in {"evo_bomber", "cn_evo_bomber"} else "normal" if variant == "bomber" else "uncertain"
        forms[form]["attempts"] += 1
        forms[form]["confirmed"] += int(bool(row["confirmed"]))
    for row in ends:
        evidence = row["evidence"]
        assert hashlib.sha256(Path(evidence["path"]).read_bytes()).hexdigest() == evidence["sha256"]
    results = Counter(r["result"] for r in ends)
    return {"session": stage, "policy": events[0]["policy_version"], "completed": len(ends),
            "wins": results["胜利"], "losses": results["失败"], "unknown": len(ends)-results["胜利"]-results["失败"],
            "attempts": sum(r["attempts"] for r in ends), "confirmed": sum(r["confirmed"] for r in ends),
            "unconfirmed": sum(r["attempts"]-r["confirmed"] for r in ends),
            "bomber_forms": forms, "battles": ends,
            "recoveries": sum(r["event"] == "recovery" and r.get("battle") in completed_ids for r in events)}


candidate = stage_summary(session, 10)
stages = [stage_summary(stage, 10 if stage == session else None) for stage in stage_ids]
report = {"created_at": datetime.now().isoformat(), "functional_status": "PASS_EVOLUTION_IDENTITY_DEPLOYMENT_AND_LOOP",
          "effectiveness_status": "HOLD_NO_DEMONSTRATED_WIN_RATE_IMPROVEMENT",
          "fixed_first10": candidate, "all_test_stages": stages, "gate": gate,
          "baseline_v2": {"session": "20260928-134106", "first10": {"wins": 3, "losses": 7},
                          "all27": {"wins": 7, "losses": 20}},
          "validation": {"pytest_passed": 339, "pytest_subtests_passed": 167, "python_compile": "passed"},
          "limits": ["Different opponents and small samples; neither a positive nor negative causal win-rate claim is established.",
                     "Earlier calibration and rejected intermediate-stage losses are preserved, not omitted.",
                     "Only current hand art establishes evolution readiness; the deck slot and cycle count do not.",
                     "Accepted deployments do not prove damage, defense success, or additional bounce hits.",
                     "A quiet detector does not establish a truly empty board; missed enemy types remain a material limitation.",
                     "Opening damage is visible princess health-bar estimation, with explicit missing/incomplete windows; king damage is not measured."]}
(output / "567-v3-evo-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
flat, tiles = [], []
for row in candidate["battles"]:
    item = {"battle": row["battle"], "result": row["result"], "attempts": row["attempts"], "confirmed": row["confirmed"]}
    for form in ("normal", "evolved", "uncertain"):
        counts = row.get("bomber_forms", {}).get(form, {})
        item[form+"_bomber_attempts"] = counts.get("attempts", 0)
        item[form+"_bomber_confirmed"] = counts.get("confirmed", 0)
    for side in ("left", "right"):
        hp = row["opening_45s"][side]
        item[side+"_observed_loss_fraction"] = hp["observed_loss_fraction"]
        item[side+"_complete_45s_window"] = hp["complete_45s_window"]
    flat.append(item)
    image = cv2.imread(row["evidence"]["path"])
    tile = cv2.copyMakeBorder(cv2.resize(image[:405], (209, 202)), 25, 0, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    text = f"#{row['battle']} {'WIN' if row['result']=='胜利' else 'LOSS' if row['result']=='失败' else 'UNKNOWN'}"
    cv2.putText(tile, text, (5, 17), cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 0, 0), 1)
    tiles.append(tile)
with (output / "567-v3-evo-first10.csv").open("w", encoding="utf-8-sig", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=list(flat[0]))
    writer.writeheader()
    writer.writerows(flat)
cv2.imwrite(str(output / "567-v3-evo-results.png"), np.vstack([np.hstack(tiles[:5]), np.hstack(tiles[5:])]))
print(json.dumps([{k: v for k, v in stage.items() if k != "battles"} for stage in stages], ensure_ascii=False, indent=2))
