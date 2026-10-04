"""Offline motion confirmation for dark body candidates from frozen images."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("sources", nargs="*", type=Path)
parser.add_argument("--output", type=Path)
args = parser.parse_args()
sources = args.sources or [Path(__file__).resolve().parent / "dark-threat-probe-10-11.json"]
rows = [row for source in sources for row in json.loads(source.read_text(encoding="utf-8"))]
unique = {(r["pilot"], r["battle"], r["time"], tuple(r["marker"])): r for r in rows}
by_battle = defaultdict(list)
for row in unique.values():
    if row["dark_pixels"] >= 330 and 190 <= row["marker"][1] <= 310:
        by_battle[(row["pilot"], row["battle"])].append(row)

confirmed = []
for (pilot, battle), frames in by_battle.items():
    frames.sort(key=lambda row: (row["time"], row["marker"][1]))
    for row in frames:
        if row["dark_pixels"] < 400:
            continue
        x, y = row["marker"]
        now = datetime.fromisoformat(row["time"])
        for prior in frames:
            earlier = datetime.fromisoformat(prior["time"])
            elapsed = (now - earlier).total_seconds()
            px, py = prior["marker"]
            if (0 < elapsed <= 6 and abs(x - px) <= 35 and 18 <= y - py <= 90):
                confirmed.append({"pilot": pilot, "battle": battle, "time": row["time"],
                                  "from": prior["marker"], "to": row["marker"],
                                  "elapsed": elapsed, "dark": row["dark_pixels"],
                                  "sha256": row["sha256"]})
                break

confirmed.sort(key=lambda item: (item["pilot"], item["battle"], item["time"]))
if args.output:
    args.output.write_text(json.dumps(confirmed, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"count": len(confirmed), "confirmations": confirmed[:20]}, ensure_ascii=False, indent=2))
