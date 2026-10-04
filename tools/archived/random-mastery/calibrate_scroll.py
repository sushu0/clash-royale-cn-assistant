"""Observe verified list overlap with the runner stopped."""
import json
import logging
import time
from pathlib import Path

import cv2

from pyclashbot.bot.cn_1v1_loop import TimedAdbController, _LogAdapter
from pyclashbot.bot.coords import CN_RANDOM_LOCKED_DETAIL_CLOSE, CN_RANDOM_MASTERY, CN_RANDOM_MASTERY_SCROLL_END, CN_RANDOM_MASTERY_SCROLL_MS, CN_RANDOM_MASTERY_SCROLL_START, CN_RANDOM_MODAL_CLOSE
from pyclashbot.detection.cn_random_ui import mastery_card_points, random_ui_is

ROOT = Path(r"D:\codex\CodexWork\clash")
TimedAdbController.adb_path = r"D:\codex\CodexWork\tool_runtimes\android-platform-tools\platform-tools\adb.exe"
device = TimedAdbController(_LogAdapter(logging.getLogger("scroll")), device_serial="127.0.0.1:21503")
assert random_ui_is(device.screenshot(), "mastery_locked")
device.click(*CN_RANDOM_LOCKED_DETAIL_CLOSE)
time.sleep(0.8)
assert random_ui_is(device.screenshot(), "mastery_list")
device.click(*CN_RANDOM_MODAL_CLOSE)
time.sleep(0.8)
assert random_ui_is(device.screenshot(), "deck")
device.click(*CN_RANDOM_MASTERY)
time.sleep(0.8)
before = device.screenshot()
assert random_ui_is(before, "mastery_list")
sx, sy = CN_RANDOM_MASTERY_SCROLL_START
ex, ey = CN_RANDOM_MASTERY_SCROLL_END
device.adb(f"shell input swipe {sx} {sy} {ex} {ey} {CN_RANDOM_MASTERY_SCROLL_MS}")
time.sleep(1)
after = device.screenshot()
assert random_ui_is(after, "mastery_list")
matches = []
for x, y in mastery_card_points(before):
    crop = before[y-24:y+24, x-20:x+20]
    region = after[125:462, x-23:x+23]
    _, score, _, (dx, dy) = cv2.minMaxLoc(cv2.matchTemplate(region, crop, cv2.TM_CCOEFF_NORMED))
    if score >= 0.90:
        matches.append({"x": x, "before_y": y, "after_y": dy + 149, "score": round(score, 4)})
cv2.imwrite(str(ROOT / "work/random-mastery/coverage-before.png"), before)
cv2.imwrite(str(ROOT / "work/random-mastery/coverage-after.png"), after)
report = {"overlap_confirmed": len(matches) >= 4, "matches": matches}
(ROOT / "work/random-mastery/coverage.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report))
