"""Calibrate the game's local deck-link action without reading prior clipboard data."""
import argparse
import logging
from pathlib import Path

import cv2

from pyclashbot.bot.cn_random_mastery_loop import RandomMasteryLoop
from pyclashbot.bot.coords import CN_RANDOM_DECK_OPTIONS, CN_RANDOM_DECK_LINK
from pyclashbot.bot.nav import PAGE_CN_MAIN, PAGE_CN_CARD

ROOT = Path(r"D:\codex\CodexWork\clash")
parser = argparse.ArgumentParser()
parser.add_argument("action", choices=("recover", "menu", "link"))
args = parser.parse_args()
logging.basicConfig(level=logging.INFO)
runner = RandomMasteryLoop(r"D:\codex\CodexWork\tool_runtimes\android-platform-tools\platform-tools\adb.exe",
                          "127.0.0.1:21503", logging.getLogger("deck-link"))
if args.action == "recover":
    runner._return_from_result()
    runner._navigate(PAGE_CN_MAIN, PAGE_CN_CARD)
elif args.action == "menu":
    runner._require("deck")
    runner._tap(CN_RANDOM_DECK_OPTIONS)
else:
    runner._require("deck_menu")
    runner._tap(CN_RANDOM_DECK_LINK)
path = ROOT / "work/random-strategy" / f"link-{args.action}.png"
cv2.imwrite(str(path), runner.device.screenshot())
print(path)
