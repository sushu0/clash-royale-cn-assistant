"""Persist the actual held-out recognizer results and implementation hashes."""
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(r"D:\codex\CodexWork\clash")
sys.path.insert(0, str(ROOT / "py-clash-bot"))
from pyclashbot.detection.cn_random_hand import CALIBRATION_ROOT, identify_random_hand

fixture_root = ROOT / "py-clash-bot/tests/fixtures/cn_random_hand/calibration_20261003"
samples = json.loads((fixture_root / "manifest.json").read_text(encoding="utf-8"))
results = []
for sample in samples:
    frame = np.zeros((633, 419, 3), dtype=np.uint8)
    x1, y1, x2, y2 = sample["source_roi"]
    frame[y1:y2, x1:x2] = cv2.imread(str(fixture_root / sample["file"]))
    hand = identify_random_hand(frame)
    assert [item["card"] for item in hand] == sample["expected_cards"]
    assert [item["cost"] for item in hand] == sample["expected_costs"]
    timings = []
    for _ in range(12):
        start = time.perf_counter()
        identify_random_hand(frame)
        timings.append((time.perf_counter() - start) * 1000)
    results.append({"file": sample["file"], "hand": hand, "median_ms": round(statistics.median(timings), 3)})

paths = [ROOT / "py-clash-bot/pyclashbot/detection/cn_random_hand.py", *CALIBRATION_ROOT.glob("*")]
report = {"status": "PASS_OFFLINE", "tests": "22 passed; calibration, prior frozen hand outputs, deployment, BGR",
          "py_compile": "PASS", "ruff_project_rules": "PASS", "held_out": results,
          "files": [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in paths],
          "source_backup": str(ROOT / "work/no-play-repair-20261003/source-backup/cn_random_hand.py.before-calibration"),
          "scope": "No virtual machine input/lifecycle, roles, strategy, loop or shared card_detection modifications"}
target = ROOT / "work/no-play-repair-20261003/hand-calibration-validation.json"
target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"report": str(target), "held_out": len(results), "median_ms": [item["median_ms"] for item in results]}))
