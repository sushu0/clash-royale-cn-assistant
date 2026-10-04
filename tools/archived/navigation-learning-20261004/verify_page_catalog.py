"""Replay captured page evidence and persist the bounded recognition outcomes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import cv2

from pyclashbot.bot.cn_1v1_loop import ChineseVision
from pyclashbot.detection.cn_page_navigation import cn_navigation_step, learned_pages

ROOT = Path(__file__).resolve().parent


def main():
    vision = ChineseVision()
    rows = []
    excluded = []
    for path in sorted((ROOT / "pages").glob("*.png")):
        frame = cv2.imread(str(path))
        if frame is None or frame.shape != (633, 419, 3):
            excluded.append(path.name)
            continue
        step = cn_navigation_step(frame)
        rows.append({
            "capture": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "shape": list(frame.shape) if frame is not None else None,
            "classification": vision.classify(frame)[0] if frame is not None else "invalid",
            "navigation": asdict(step) if step is not None else None,
        })
    report = {
        "observed_date": "2026-10-04",
        "calibrated_rules": len(learned_pages()),
        "captured_frames": len(rows),
        "excluded_non_frames": excluded,
        "recognized_navigation": sum(row["navigation"] is not None for row in rows),
        "unrecognized_frames": [row["capture"] for row in rows if row["classification"] == "unknown"],
        "pages": rows,
    }
    path = ROOT / "page-replay.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "pages"}))


if __name__ == "__main__":
    main()
