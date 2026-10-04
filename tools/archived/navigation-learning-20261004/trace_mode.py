"""Trace the existing guarded mode selector against the attached game."""
import json
import logging
from pathlib import Path

import cv2

from pyclashbot.bot.cn_1v1_loop import ChineseVision, TimedAdbController, _LogAdapter
from pyclashbot.bot.nav import navigate_cn_classic_1v1
from pyclashbot.detection.cn_page_navigation import cn_classic_mode_point, cn_mode_menu_at_top, cn_navigation_step

ROOT = Path(__file__).resolve().parent / "mode-trace"
ROOT.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mode-trace")
TimedAdbController.adb_path = r"D:\codex\CodexWork\tool_runtimes\android-platform-tools\platform-tools\adb.exe"
device = TimedAdbController(_LogAdapter(logger), device_serial="127.0.0.1:21503")
vision = ChineseVision()


class ObservedDevice:
    def __init__(self):
        self.index = 0
        self.events = []

    def screenshot(self):
        frame = device.screenshot()
        kind = vision.classify(frame)[0]
        step = cn_navigation_step(frame)
        path = ROOT / f"{self.index:03d}-{kind}.png"
        cv2.imwrite(str(path), frame)
        entry = {"frame": self.index, "kind": kind, "classic": vision.classic_selected(frame), "page": step.page if step else None, "point": cn_classic_mode_point(frame), "top": cn_mode_menu_at_top(frame)}
        self.events.append(entry)
        print(json.dumps(entry), flush=True)
        self.index += 1
        return frame

    def click(self, *point):
        self.events.append({"click": list(point)})
        print("click", point, flush=True)
        device.click(*point)

    def swipe(self, *points):
        self.events.append({"swipe": list(points)})
        print("swipe", points, flush=True)
        device.swipe(*points)


observed = ObservedDevice()
ok = navigate_cn_classic_1v1(observed, _LogAdapter(logger), vision, verify_menu=True)
(ROOT / "trace.json").write_text(json.dumps({"ok": ok, "events": observed.events}, indent=2), encoding="utf-8")
print("verified", ok)
