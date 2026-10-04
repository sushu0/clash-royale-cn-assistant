"""Build bounded page fingerprints from locally inspected game screenshots."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import cv2
import numpy as np

from pyclashbot.bot.coords import CN_PAGE_ROIS

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1] / "py-clash-bot"
TARGET = REPO / "pyclashbot/detection/reference_images/cn_pages"
FIXTURES = REPO / "tests/fixtures/cn_pages"


def main():
    TARGET.mkdir(parents=True, exist_ok=True)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    pages = []
    definitions = json.loads((ROOT / "page-definitions.json").read_text(encoding="utf-8"))
    for entry in definitions:
        path = ROOT / "pages" / f"{entry['source']}.png"
        frame = cv2.imread(str(path))
        if frame is None or frame.shape != (633, 419, 3):
            raise ValueError(f"Invalid capture: {path}")
        cues = []
        for roi_definition in entry["rois"]:
            roi_key = roi_definition if isinstance(roi_definition, str) else roi_definition["roi"]
            x1, y1, x2, y2 = CN_PAGE_ROIS[roi_key]
            name = f"{entry['name']}_{roi_key}"
            if not cv2.imwrite(str(TARGET / f"{name}.png"), frame[y1:y2, x1:x2]):
                raise OSError(f"Cannot save crop {name}")
            cue = {"roi": roi_key, "template": name}
            if isinstance(roi_definition, dict):
                cue.update(roi_definition)
            cues.append(cue)
        page = {
            "name": entry["name"], "route": entry["route"], "cues": cues,
            "source": path.name, "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        if "target_cue" in entry:
            page["target_cue"] = entry["target_cue"]
        if entry.get("idle_only"):
            page["idle_only"] = True
        if entry.get("unowned_only"):
            page["unowned_only"] = True
        pages.append(page)
        if entry.get("fixture_cues_only"):
            # Keep account QR codes and invitation bodies in the private task
            # captures. Offline fixtures only need the already inspected cues.
            fixture = np.zeros_like(frame)
            for cue in cues:
                x1, y1, x2, y2 = CN_PAGE_ROIS[cue["roi"]]
                fixture[y1:y2, x1:x2] = frame[y1:y2, x1:x2]
            page["fixture_source"] = f"{entry['source']}_cues_only.png"
            cv2.imwrite(str(FIXTURES / page["fixture_source"]), fixture)
        else:
            shutil.copy2(path, FIXTURES / path.name)
        if entry.get("variants"):
            page["variants"] = []
            for variant in entry["variants"]:
                variant_path = ROOT / "pages" / f"{variant}.png"
                if entry.get("fixture_cues_only"):
                    observed = cv2.imread(str(variant_path))
                    if observed is None or observed.shape != (633, 419, 3):
                        raise ValueError(f"Invalid variant: {variant_path}")
                    fixture = np.zeros_like(observed)
                    for cue in cues:
                        x1, y1, x2, y2 = CN_PAGE_ROIS[cue["roi"]]
                        fixture[y1:y2, x1:x2] = observed[y1:y2, x1:x2]
                    fixture_name = f"{variant}_cues_only.png"
                    cv2.imwrite(str(FIXTURES / fixture_name), fixture)
                else:
                    fixture_name = variant_path.name
                    shutil.copy2(variant_path, FIXTURES / fixture_name)
                page["variants"].append(fixture_name)
    (TARGET / "manifest.json").write_text(json.dumps({
        "schema": 1, "resolution": [419, 633], "observed_date": "2026-10-04", "pages": pages,
    }, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pages": len(pages), "templates": sum(len(page['cues']) for page in pages)}))


if __name__ == "__main__":
    main()
