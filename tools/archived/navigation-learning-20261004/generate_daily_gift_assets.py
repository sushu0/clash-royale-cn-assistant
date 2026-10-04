"""Build narrowly cropped templates from the preserved 08:00 report evidence."""

# ruff: noqa: INP001 - standalone evidence preparation script, not a package.

import hashlib
import json
import shutil
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "outputs/error-reports/20261004-080006-841991-13d659b07abe29404c728160/game.png"
ASSETS = ROOT / "py-clash-bot/pyclashbot/detection/reference_images/cn_daily_gift"
FIXTURES = ROOT / "py-clash-bot/tests/fixtures/cn_daily_gift"
CROPS = {
    "title": (116, 45, 301, 69),
    "rich": (166, 184, 250, 204),
    "luck": (164, 317, 254, 337),
    "cosmetic": (165, 450, 251, 472),
}


def main() -> None:
    frame = cv2.imread(str(SOURCE))
    assert frame is not None and frame.shape == (633, 419, 3)
    manifest = {
        "schema": "cn-daily-gift-templates/v1",
        "source": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "source_created_at": "2026-10-04T08:00:06+08:00",
        "choice": "我想变好看",
        "choice_coordinate": [210, 434],
        "cue_text": {
            "title": "福袋天降 好事成三",
            "rich": "我想变富有",
            "luck": "我想碰碰运气",
            "cosmetic": "我想变好看",
        },
        "assets": [],
    }
    for name, (x1, y1, x2, y2) in CROPS.items():
        target = ASSETS / name / "20261004.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        assert cv2.imwrite(str(target), frame[y1:y2, x1:x2])
        manifest["assets"].append(
            {
                "path": str(target.relative_to(ASSETS)).replace("\\", "/"),
                "crop_ltrb": [x1, y1, x2, y2],
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            }
        )
    (ASSETS / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    FIXTURES.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE, FIXTURES / "daily_gift_choice_20261004.png")
    print(json.dumps({"templates": len(CROPS), "fixture": str(FIXTURES)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
