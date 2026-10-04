"""Compare frozen and new hand recognition exactly, and persist replay fixtures."""
import importlib.util
import json
import statistics
import time
from pathlib import Path

import cv2

from pyclashbot.bot.cn_1v1_loop import ChineseVision
from pyclashbot.detection.cn_random_hand import identify_random_hand

ROOT = Path(r"D:\codex\CodexWork\clash")
old_path = ROOT / "work/backups/random-fluency-20261001/pyclashbot/detection/cn_random_hand.py"
spec = importlib.util.spec_from_file_location("frozen_random_hand", old_path)
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)
live = json.loads((ROOT / "outputs/random-mastery-live-status.json").read_text(encoding="utf-8"))
vision = ChineseVision()
frames = []
for p in Path(live["evidence_dir"]).glob("recent-*.png"):
    f = cv2.imread(str(p))
    if f is not None and vision.classify(f)[0] == "battle":
        frames.append(f)
frames = frames[:10]
assert len(frames)>=3
timings = {}
for label, fn in (("before", old.identify_random_hand), ("after", identify_random_hand)):
    values = []
    for f in frames*3:
        start = time.perf_counter()
        fn(f)
        values.append((time.perf_counter()-start)*1000)
    timings[label] = round(statistics.median(values), 3)
for f in frames:
    assert old.identify_random_hand(f) == identify_random_hand(f)
    for names in (("hog", "knight", "musketeer"), ("ice_golem", "battle_ram", "fireball"), ("not_a_card",)):
        assert old.identify_random_hand(f, names) == identify_random_hand(f, names)
fixtures = ROOT / "py-clash-bot/tests/fixtures/cn_random_hand"
fixtures.mkdir(exist_ok=True)
expected = []
for i, f in enumerate(frames[:3]):
    filename = f"live_hand_{i}.png"
    assert cv2.imwrite(str(fixtures/filename), f)
    expected.append({"file": filename, "hand": old.identify_random_hand(f)})
(fixtures / "expected.json").write_text(json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8")
report = {"result": "PASS", "frames_compared": len(frames), "restrictions_compared": 3,
          "median_ms": timings, "speedup": round(timings["before"]/timings["after"], 2)}
(ROOT / "outputs/RANDOM_HAND_PERFORMANCE.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
