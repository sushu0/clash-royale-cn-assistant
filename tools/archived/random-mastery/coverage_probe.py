"""Read-only observation of two consecutive mastery list viewports."""
import json
import logging
import time
from pathlib import Path

import cv2
import numpy as np

from pyclashbot.bot.cn_1v1_loop import TimedAdbController, _LogAdapter
from pyclashbot.detection.cn_random_ui import mastery_card_points, random_ui_is

ROOT = Path(r"D:\codex\CodexWork\clash")
TimedAdbController.adb_path = r"D:\codex\CodexWork\tool_runtimes\android-platform-tools\platform-tools\adb.exe"
device = TimedAdbController(_LogAdapter(logging.getLogger("coverage")), device_serial="127.0.0.1:21503")
previous = None
deadline = time.monotonic() + 45
while time.monotonic() < deadline:
    frame = device.screenshot()
    if random_ui_is(frame, "mastery_list"):
        if previous is None:
            previous = frame
        elif float(np.mean(np.abs(previous[125:462].astype(float) - frame[125:462].astype(float)))) > 15:
            cv2.imwrite(str(ROOT / "work/random-mastery/coverage-before.png"), previous)
            cv2.imwrite(str(ROOT / "work/random-mastery/coverage-after.png"), frame)
            points = mastery_card_points(previous)
            matches = []
            for x, y in points:
                crop = previous[y-24:y+24, x-20:x+20]
                region = frame[125:462, x-23:x+23]
                scores = cv2.matchTemplate(region, crop, cv2.TM_CCOEFF_NORMED)
                _, score, _, (dx, dy) = cv2.minMaxLoc(scores)
                if score > 0.9:
                    matches.append({"x": x, "before_y": y, "after_y": dy + 149, "score": round(score, 4)})
            report = {"overlapping_cards": matches, "overlap_confirmed": bool(matches)}
            (ROOT / "work/random-mastery/coverage.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report))
            break
    time.sleep(0.3)
else:
    print("No pair of consecutive list viewports observed within 45 seconds")
