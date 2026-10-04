"""Single observed Android-game inspection step through the bot's ADB API."""
import argparse
import hashlib
import json
import logging
import time
from pathlib import Path

import cv2
import numpy as np

from pyclashbot.bot.cn_1v1_loop import ChineseVision, TimedAdbController, _LogAdapter
from pyclashbot.bot.nav import navigate_cn_classic_1v1, recover_cn_page_once
from pyclashbot.emulators.base import CLASH_ROYALE_PACKAGE

ROOT = Path(__file__).resolve().parent
ADB = r"D:\codex\CodexWork\tool_runtimes\android-platform-tools\platform-tools\adb.exe"
parser = argparse.ArgumentParser()
parser.add_argument("name")
parser.add_argument("--recover", action="store_true")
parser.add_argument("--back", action="store_true")
parser.add_argument("--classic", action="store_true")
parser.add_argument("--expect")
parser.add_argument("--tap", nargs=2, type=int)
parser.add_argument("--swipe", nargs=4, type=int)
parser.add_argument("--swipe-ms", type=int, default=420)
parser.add_argument("--delay", type=float, default=0.9)
args = parser.parse_args()
if not args.name.replace("_", "").replace("-", "").isalnum():
    raise ValueError("simple observation name required")
TimedAdbController.adb_path = ADB
logger = logging.getLogger("page-inspection")
device = TimedAdbController(_LogAdapter(logger), device_serial="127.0.0.1:21503")
if device.foreground_package() != CLASH_ROYALE_PACKAGE:
    raise RuntimeError("game is not foreground on the already attached Android device")
def settled_frame():
    current = device.screenshot()
    for _ in range(2):
        time.sleep(0.2)
        current = device.screenshot()
    return current


frame = settled_frame()
if frame is None or frame.shape != (633, 419, 3):
    raise RuntimeError("unexpected game resolution")
cv2.imwrite(str(ROOT / "pages" / f"{args.name}_before.png"), frame)
if args.expect:
    expected = cv2.imread(str(ROOT / "pages" / f"{args.expect}.png"))
    if expected is None or expected.shape != frame.shape:
        raise RuntimeError("missing expected observation")
    difference = float(np.mean(np.abs(expected.astype(np.float32) - frame.astype(np.float32))))
    if difference > 25:
        raise RuntimeError(f"screen changed since observation: difference={difference:.2f}")
if sum((args.recover, args.back, args.classic, args.tap is not None, args.swipe is not None)) > 1:
    raise ValueError("one action per invocation")
action = "observe"
if args.recover:
    action = recover_cn_page_once(device, _LogAdapter(logger), frame, allow_spectator_exit=True)
    if action is None:
        raise RuntimeError("unrecognized observed page; no input")
elif args.tap:
    OBSERVED_INSPECTION_POINT = tuple(args.tap)
    if not (0 <= OBSERVED_INSPECTION_POINT[0] < 419 and 0 <= OBSERVED_INSPECTION_POINT[1] < 633):
        raise ValueError("point outside game")
    device.click(*OBSERVED_INSPECTION_POINT)
    action = "observed_inspection_tap"
elif args.swipe:
    OBSERVED_INSPECTION_SWIPE = tuple(args.swipe)
    if not 50 <= args.swipe_ms <= 1000:
        raise ValueError("inspection swipe duration outside bounded range")
    device.adb("shell input swipe " + " ".join(map(str, OBSERVED_INSPECTION_SWIPE)) + f" {args.swipe_ms}", timeout=8)
    action = "observed_inspection_swipe"
elif args.back:
    device.adb("shell input keyevent 4", timeout=8)
    action = "observed_android_back"
elif args.classic:
    if not navigate_cn_classic_1v1(device, _LogAdapter(logger), ChineseVision(), verify_menu=True):
        raise RuntimeError("Classic 1v1 menu round trip could not be verified")
    action = "classic_mode_round_trip_verified"
time.sleep(args.delay)
after = settled_frame()
path = ROOT / "pages" / f"{args.name}.png"
cv2.imwrite(str(path), after)
kind, _ = ChineseVision().classify(after)
event = {"name": args.name, "action": action, "tap": args.tap, "swipe": args.swipe, "expected": args.expect, "after_kind": kind, "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
with (ROOT / "inspection-actions.jsonl").open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(event, ensure_ascii=False) + "\n")
print(json.dumps(event, ensure_ascii=False))
