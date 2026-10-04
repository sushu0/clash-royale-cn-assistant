"""Read-only, observational Hog-to-tower-health windows for frozen pilots.

Damage in a window can also come from another friendly unit or spell. This is
only a coordinate experiment diagnostic, never a causal win-rate claim.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import statistics


def analyze(folder: Path) -> dict:
    status = json.loads((folder / "capture-status.json").read_text(encoding="utf-8"))
    if status["status"] != "complete" or not status["verified_final_lobby"]:
        raise RuntimeError(f"Pilot is incomplete: {folder}")
    events = [json.loads(line) for line in (folder / "events.jsonl").read_text(encoding="utf-8").splitlines()
              if line.strip()]
    plays = [e for e in events if e.get("event") == "play" and e.get("decision", {}).get("card") == "hog"]
    observations = [e for e in events if e.get("event") in ("play", "observe") and e.get("cues")]
    windows = []
    for hog in plays:
        lane = "left" if hog["decision"]["point"][0] < 209 else "right"
        baseline = hog["cues"]["enemy_tower_fill"].get(lane)
        started = datetime.fromisoformat(hog["time"])
        later = [e for e in observations if e.get("battle") == hog["battle"]
                 and 0 < (datetime.fromisoformat(e["time"]) - started).total_seconds() <= 10]
        fills = [e["cues"]["enemy_tower_fill"].get(lane) for e in later]
        fills = [float(value) for value in fills if isinstance(value, (int, float)) and 0 < value <= 1]
        if any(e["cues"].get("enemy_towers", {}).get(lane) is False for e in later):
            fills.append(0.0)
        change = round(max(0.0, float(baseline) - min(fills)), 3) if isinstance(baseline, (int, float)) and fills else None
        windows.append({"battle": hog["battle"], "time": hog["time"], "point": hog["decision"]["point"],
                        "confirmed": hog["confirmed"], "baseline_fill": baseline,
                        "lowest_following_fill": min(fills) if fills else None,
                        "fill_decline_10_seconds": change})
    readable = [w["fill_decline_10_seconds"] for w in windows if w["fill_decline_10_seconds"] is not None]
    summary = {"pilot": folder.name, "hog_attempts": len(windows),
               "confirmed_hogs": sum(w["confirmed"] for w in windows),
               "readable_windows": len(readable),
               "windows_with_at_least_5pct_decline": sum(value >= 0.05 for value in readable),
               "median_fill_decline": round(statistics.median(readable), 3) if readable else None,
               "mean_fill_decline": round(statistics.mean(readable), 3) if readable else None,
               "missing_windows_retained": len(windows) - len(readable)}
    return {"summary": summary, "windows": windows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = analyze(args.batch_dir)
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
