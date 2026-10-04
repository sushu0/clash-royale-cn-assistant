from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(r"D:\codex\CodexWork\clash")
sys.path.insert(0, str(ROOT / "py-clash-bot"))
from pyclashbot.bot.cn_1v1_loop import ChineseVision, SEARCH_REGIONS, THRESHOLDS
from pyclashbot.bot.coords import CN_BATTLE_CLOCK_ROI, CN_HOG_ELIXIR_X_COORDS, CN_HOG_ELIXIR_Y
from pyclashbot.detection.cn_battle_cues import _read_elixir
from pyclashbot.detection.cn_random_hand import identify_random_hand
from pyclashbot.detection.cn_random_ui import available_random_slots

OUT = ROOT / "work" / "no-play-20261003" / "vision-audit"
OUT.mkdir(parents=True, exist_ok=True)
vision = ChineseVision()

def audit(path, frame, label):
    scores = {}
    for name, template in vision.templates.items():
        x1, y1, x2, y2 = SEARCH_REGIONS[name]
        region = frame[y1:y2, x1:x2]
        if region.shape[0] < template.shape[0] or region.shape[1] < template.shape[1]:
            continue
        score_map = cv2.matchTemplate(cv2.cvtColor(region, cv2.COLOR_BGR2GRAY), cv2.cvtColor(template, cv2.COLOR_BGR2GRAY), cv2.TM_CCOEFF_NORMED)
        _, score, _, (x, y) = cv2.minMaxLoc(score_map)
        scores[name] = {"score": round(score, 5), "threshold": THRESHOLDS[name], "position": [x+x1, y+y1]}
    x1, y1, x2, y2 = CN_BATTLE_CLOCK_ROI
    clock_path = OUT / f"{label}-clock.png"
    cv2.imwrite(str(clock_path), cv2.resize(frame[y1:y2, x1:x2], None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST))
    return {"path": str(path), "label": label, "shape": list(frame.shape), "classify": vision.classify(frame)[0], "elixir": _read_elixir(frame), "elixir_pixels": frame[CN_HOG_ELIXIR_Y, CN_HOG_ELIXIR_X_COORDS].tolist(), "available_slots": available_random_slots(frame), "hand": identify_random_hand(frame), "scores": scores, "clock_path": str(clock_path)}

results=[]
session = ROOT / "work" / "random-mastery" / "20261003-182719"
for path in sorted(session.glob("recent-*.png"), key=lambda p:p.stat().st_mtime):
    frame = cv2.imread(str(path))
    if frame is None or frame.shape != (633,419,3):
        continue
    # Save input snapshots to prevent recent-ring overwrite changing audit evidence.
    copy = OUT / path.name
    cv2.imwrite(str(copy), frame)
    result = audit(copy, frame, path.stem)
    result["source_mtime"] = path.stat().st_mtime
    results.append(result)

user=Path(r"C:\Users\22639\AppData\Local\Temp\codex-clipboard-e2acf214-8afb-4b5d-bdb0-bc6fbd6e9987.png")
frame=cv2.imread(str(user))
if frame is not None:
    cropped=cv2.resize(frame[52:844,15:539],(419,633),interpolation=cv2.INTER_AREA)
    crop_path=OUT/"user-game-crop.png"
    cv2.imwrite(str(crop_path),cropped)
    results.append(audit(crop_path,cropped,"user"))

report=OUT/"audit.json"
report.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"report":str(report), "frames":len(results),"summary":[{"label":r["label"],"mtime":r.get("source_mtime"),"kind":r["classify"],"elixir":r["elixir"],"slots":r["available_slots"],"hand":[[h["candidate"],h["card"],h["offset"],h["margin"],h["available"]] for h in r["hand"]],"hud":r["scores"].get("battle_hud")} for r in results]},ensure_ascii=False))
