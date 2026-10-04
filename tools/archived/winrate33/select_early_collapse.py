"""Select first observed friendly Princess Tower half-health screenshots."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PILOTS = [ROOT / f"pilot-{number:02d}" for number in range(2, 15)]
selected = []
for pilot in PILOTS:
    events = [json.loads(line) for line in (pilot / "events.jsonl").read_text(encoding="utf-8").splitlines()
              if line.strip()]
    starts = {event["battle"]: datetime.fromisoformat(event["time"])
              for event in events if event["event"] == "battle_start" and not event.get("resumed")}
    losses = {event["battle"] for event in events
              if event["event"] == "battle_end" and event["result"] != "胜利"}
    seen = set()
    for event in events:
        battle = event.get("battle")
        if battle not in losses or battle in seen or event.get("event") not in ("play", "observe"):
            continue
        cues = event.get("cues") or {}
        own = cues.get("own_tower_fill") or {}
        valid = [(side, value) for side, value in own.items()
                 if isinstance(value, (int, float)) and 0 < value <= 0.5]
        if not valid:
            continue
        evidence = event.get("evidence_before") if event["event"] == "play" else event.get("evidence")
        if not evidence or not evidence.get("sha256"):
            continue
        frozen = pilot / "evidence" / f"{evidence['sha256']}.png"
        if not frozen.is_file() or hashlib.sha256(frozen.read_bytes()).hexdigest() != evidence["sha256"]:
            raise RuntimeError(f"Missing or changed evidence: {pilot.name} #{battle}")
        seen.add(battle)
        moment = datetime.fromisoformat(event["time"])
        selected.append({"pilot": pilot.name, "battle": battle,
                         "seconds_from_start": round((moment - starts[battle]).total_seconds()),
                         "time": event["time"], "own_tower_fill": own,
                         "red_markers": cues.get("enemies", []),
                         "far_warnings": cues.get("far_warnings", []),
                         "sha256": evidence["sha256"], "frozen_png": str(frozen)})

selected.sort(key=lambda item: (item["seconds_from_start"], item["pilot"], item["battle"]))
output = ROOT / "early-half-tower-losses-02-through-14.json"
output.write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"losses_with_readable_half_tower_frame": len(selected),
                  "under_45_seconds": sum(item["seconds_from_start"] <= 45 for item in selected),
                  "first_20": selected[:20]}, ensure_ascii=False, indent=2))
