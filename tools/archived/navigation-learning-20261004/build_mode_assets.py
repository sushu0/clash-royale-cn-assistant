"""Calibrate the observed Classic 1v1 caption and shield without selecting it."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import cv2

from pyclashbot.bot.coords import CN_PAGE_ROIS

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1] / "py-clash-bot"
TARGET = REPO / "pyclashbot/detection/reference_images/cn_pages"
FIXTURES = REPO / "tests/fixtures/cn_pages"


def main():
    definition = {
        "label": ("game_modes_classic_visible", "classic_label", "classic_label_search"),
        "shield": ("game_modes_classic_visible", "classic_shield", "classic_shield_search"),
        "top_marker": ("game_modes_top", "mode_top_marker", "mode_top_marker_search"),
    }
    manifest = {"schema": 1, "resolution": [419, 633], "observed_date": "2026-10-04"}
    for name, (source, roi, search_roi) in definition.items():
        path = ROOT / "pages" / f"{source}.png"
        frame = cv2.imread(str(path))
        if frame is None or frame.shape != (633, 419, 3):
            raise ValueError(f"Invalid mode source: {source}")
        x1, y1, x2, y2 = CN_PAGE_ROIS[roi]
        template = f"classic_mode_{name}"
        if not cv2.imwrite(str(TARGET / f"{template}.png"), frame[y1:y2, x1:x2]):
            raise OSError(f"Cannot save {template}")
        manifest[name] = {"roi": roi, "search_roi": search_roi, "template": template}
        manifest[f"{name}_source_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        shutil.copy2(path, FIXTURES / path.name)
    for source in ("classic_2v2_lobby", "game_modes_scrolled"):
        shutil.copy2(ROOT / "pages" / f"{source}.png", FIXTURES / f"{source}.png")
    (TARGET / "classic_mode.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"config": str(TARGET / "classic_mode.json"), "cues": 3}))


if __name__ == "__main__":
    main()
