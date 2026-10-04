"""Offline RGB-weight versus BGR-weight comparison on saved real frames."""
import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(r"D:\codex\CodexWork\clash\py-clash-bot")
OUTPUT = Path(r"D:\codex\CodexWork\clash\work\repair-20261003\gray-match-calibration.json")
bank = ROOT / "pyclashbot/detection/reference_images"
templates = [(path, cv2.imread(str(path))) for path in sorted(bank.rglob("*.png"))
             if not path.relative_to(bank).parts[0].startswith("cn_")]
frames = [(path, cv2.imread(str(path))) for path in sorted((ROOT / "tests/fixtures").rglob("*.png"))]
regressions, gains, peaks = [], [], []
for path, color in templates:
    old_template = cv2.cvtColor(color, cv2.COLOR_RGB2GRAY)
    new_template = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
    best_old, best_new = (-1, None), (-1, None)
    for frame_path, frame in frames:
        if frame is None or frame.shape[:2] != (633, 419):
            continue
        if color.shape[0] > frame.shape[0] or color.shape[1] > frame.shape[1]:
            continue
        old = float(cv2.minMaxLoc(cv2.matchTemplate(cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY), old_template, cv2.TM_CCOEFF_NORMED))[1])
        new = float(cv2.minMaxLoc(cv2.matchTemplate(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), new_template, cv2.TM_CCOEFF_NORMED))[1])
        if old > best_old[0]:
            best_old = (old, str(frame_path.relative_to(ROOT)))
        if new > best_new[0]:
            best_new = (new, str(frame_path.relative_to(ROOT)))
        entry = {"template": str(path.relative_to(ROOT)), "frame": str(frame_path.relative_to(ROOT)),
                 "old": round(old, 6), "new": round(new, 6)}
        for threshold in (.85, .88, .9, .98):
            if old >= threshold and new < threshold:
                regressions.append({**entry, "threshold": threshold})
            if old < threshold <= new:
                gains.append({**entry, "threshold": threshold})
    peaks.append({"template": str(path.relative_to(ROOT)), "best_old": best_old, "best_new": best_new})
result = {"templates": len(templates), "frames": len(frames), "threshold_losses": regressions,
          "threshold_gains": gains, "peaks": peaks,
          "limit": "Real Tencent frames only; no global-English war/shop/deck positive fixtures are available."}
OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps({"templates": len(templates), "frames": len(frames), "threshold_losses": len(regressions),
                  "threshold_gains": len(gains), "output": str(OUTPUT)}))
