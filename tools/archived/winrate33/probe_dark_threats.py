"""Offline plaque-adjacent dark-blob probe; never used by the live bot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def sample(pilot: Path) -> list[dict]:
    entries = []
    for line in (pilot / "events.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("event") not in ("play", "observe") or not event.get("cues"):
            continue
        evidence = event.get("evidence_before") if event["event"] == "play" else event.get("evidence")
        if not evidence or not evidence.get("sha256"):
            continue
        image = pilot / "evidence" / f"{evidence['sha256']}.png"
        if not image.is_file():
            continue
        frame = cv2.imread(str(image))
        if frame is None:
            continue
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        for x, y in event["cues"].get("enemies", []) + event["cues"].get("far_warnings", []):
            if not 200 <= y <= 370 or not 30 <= x <= 389:
                continue
            patch = hsv[y - 10:y + 30, x - 20:x + 20]
            dark = (patch[:, :, 2] < 90) & (patch[:, :, 1] < 150)
            count = int(np.count_nonzero(dark))
            entries.append({"pilot": pilot.name, "battle": event.get("battle"),
                            "time": event["time"], "marker": [x, y],
                            "dark_pixels": count, "sha256": evidence["sha256"]})
    return entries


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("pilots", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rows = [row for pilot in args.pilots for row in sample(pilot)]
    rows.sort(key=lambda row: row["dark_pixels"], reverse=True)
    if args.output:
        args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"rows": len(rows), "above_280": sum(row["dark_pixels"] >= 280 for row in rows),
                      "top": rows[:15]}, ensure_ascii=False, indent=2))
