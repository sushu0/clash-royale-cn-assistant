"""One manually observed Android action followed by a persisted screenshot."""
import argparse
import logging
import time
from pathlib import Path

import cv2

from pyclashbot.bot import coords
from pyclashbot.bot.cn_1v1_loop import TimedAdbController, _LogAdapter

ROOT = Path(r"D:\codex\CodexWork\clash")
parser = argparse.ArgumentParser()
parser.add_argument("name")
parser.add_argument("--point")
args = parser.parse_args()
TimedAdbController.adb_path = r"D:\codex\CodexWork\tool_runtimes\android-platform-tools\platform-tools\adb.exe"
device = TimedAdbController(_LogAdapter(logging.getLogger("probe")), device_serial="127.0.0.1:21503")
if args.point:
    device.click(*getattr(coords, args.point))
    time.sleep(1.6)
frame = device.screenshot()
target = ROOT / "work" / "random-mastery" / f"{args.name}.png"
assert cv2.imwrite(str(target), frame)
print(target)
