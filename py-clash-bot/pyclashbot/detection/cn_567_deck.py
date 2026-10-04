"""Read the verified 567 deck by card identity, independent of slot order.

References are actual, reviewed 419x633 CN deck previews. This checks eight
card identities, not the current battle's evolution readiness or card levels.
No input/device I/O is performed here.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from pyclashbot.bot.coords import CN_567_DECK_ROIS
from pyclashbot.utils.runtime_config import resource_path

_FOLDER = resource_path("pyclashbot/detection/reference_images/cn_567")
EXPECTED_CARDS = frozenset(
    {
        "pekka",
        "goblin_giant",
        "goblin_machine",
        "baby_dragon",
        "mega_minion",
        "bomber",
        "zap",
        "arrows",
    }
)
MIN_SCORE = 0.90
MIN_IDENTITY_MARGIN = 0.08


@lru_cache(maxsize=1)
def _references() -> tuple[dict, ...]:
    """Load only provenance-checked references; a bad bank must fail closed."""
    try:
        manifest = json.loads((_FOLDER / "deck_manifest.json").read_text(encoding="utf-8"))
        if manifest.get("schema_version") != 1:
            return ()
        loaded = []
        for source in manifest["references"]:
            filename = source["file"]
            if Path(filename).name != filename:
                return ()
            path = _FOLDER / filename
            if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
                return ()
            frame = cv2.imread(str(path))
            if frame is None or frame.shape != (633, 419, 3):
                return ()
            cards = source["cards"]
            if (
                len(cards) != 8
                or {item["slot"] for item in cards} != set(range(8))
                or {item["card"] for item in cards} != EXPECTED_CARDS
            ):
                return ()
            for item in cards:
                card, variant = item["card"], item["variant"]
                # Explicitly reviewed variants only; never alias Goblinstein.
                if variant != card and (card, variant) != ("bomber", "evo_bomber"):
                    return ()
                x1, y1, x2, y2 = CN_567_DECK_ROIS[item["slot"]]
                loaded.append({"card": card, "variant": variant, "image": frame[y1:y2, x1:x2].copy()})
        return tuple(loaded)
    except (OSError, ValueError, KeyError, TypeError, cv2.error):
        return ()


def read_567_deck(frame: np.ndarray) -> dict:
    """Return validity and each slot's base card, matched art variant and score.

    Every live slot competes against every reviewed card crop. Variants are
    collapsed for the identity margin, while their winning label is retained.
    An unknown, ambiguous, missing or duplicate card rejects the entire deck.
    """
    if not isinstance(frame, np.ndarray) or frame.shape != (633, 419, 3) or frame.dtype != np.uint8:
        return {"valid": False, "matches": [], "reason": "invalid_frame"}
    references = _references()
    if not references:
        return {"valid": False, "matches": [], "reason": "reference_data_invalid"}
    matches = []
    for slot, (x1, y1, x2, y2) in enumerate(CN_567_DECK_ROIS):
        crop = frame[y1:y2, x1:x2]
        best_by_card = {}
        for reference in references:
            score = float(cv2.matchTemplate(crop, reference["image"], cv2.TM_CCOEFF_NORMED)[0, 0])
            if not np.isfinite(score):
                score = -1.0
            card = reference["card"]
            if card not in best_by_card or score > best_by_card[card]["score"]:
                best_by_card[card] = {"card": card, "variant": reference["variant"], "score": score}
        ranked = sorted(best_by_card.values(), key=lambda item: item["score"], reverse=True)
        best = ranked[0]
        margin = best["score"] - ranked[1]["score"]
        reliable = best["score"] >= MIN_SCORE and margin >= MIN_IDENTITY_MARGIN
        matches.append(
            {
                "slot": slot,
                "card": best["card"] if reliable else None,
                "variant": best["variant"] if reliable else None,
                "matched_variant": best["variant"] if reliable else None,
                "score": round(best["score"], 6),
                "margin": round(margin, 6),
                "candidate_card": best["card"],
            }
        )
    if any(item["card"] is None for item in matches):
        return {"valid": False, "matches": matches, "reason": "unrecognized_or_ambiguous_slots"}
    if {item["card"] for item in matches} != EXPECTED_CARDS:
        return {"valid": False, "matches": matches, "reason": "duplicate_or_missing_cards"}
    return {"valid": True, "matches": matches, "reason": "verified_unique_eight_cards"}
