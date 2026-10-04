"""Single-frame random-deck identity with margins, canonical variants and affordability."""

import hashlib
import json
from functools import lru_cache

import cv2
import numpy as np

from pyclashbot.bot import card_detection as cards
from pyclashbot.bot.random_card_roles import canonical, role_for
from pyclashbot.detection.cn_random_ui import available_random_slots
from pyclashbot.utils.runtime_config import resource_path


def fingerprints():
    result = {name: np.asarray(value) for name, value in cards.card_color_data.items()}
    for name, (_, value) in cards._HOG_HAND_FINGERPRINTS.items():
        result[name] = np.asarray(value)
    return result


FINGERPRINTS = fingerprints()
VARIANTS = tuple(FINGERPRINTS)
CANONICAL_NAMES = tuple(canonical(name) for name in VARIANTS)
FINGERPRINT_MATRIX = np.stack([FINGERPRINTS[name] for name in VARIANTS])
CALIBRATION_ROOT = resource_path("pyclashbot/detection/reference_images/cn_random_cards/hand_calibration_20261003")


@lru_cache(maxsize=1)
def _calibrated_samples():
    """Load narrow, observed artwork variants without replacing upstream fingerprints."""
    manifest = json.loads((CALIBRATION_ROOT / "manifest.json").read_text(encoding="utf-8"))
    samples = []
    for item in manifest["samples"]:
        path = CALIBRATION_ROOT / item["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise RuntimeError(f"Hand calibration checksum mismatch: {path.name}")
        image = cv2.imread(str(path))
        if image is None or image.shape != (cards.TOTAL_HEIGHT, cards.TOTAL_WIDTH, 3):
            raise RuntimeError(f"Invalid calibrated hand portrait: {path.name}")
        variant = item["variant"]
        cost = item["observed_cost"]
        if role_for(variant, cost) is None or not isinstance(cost, int) or not 1 <= cost <= 10:
            raise RuntimeError(f"Invalid calibrated card role or cost: {path.name}")
        values = np.array(
            [
                list(cards.get_corner_pixels((dx, dx + cards.HALF_WIDTH), (dy, dy + cards.HALF_HEIGHT), image).values())
                for dy in (0, cards.HALF_HEIGHT)
                for dx in (0, cards.HALF_WIDTH)
            ]
        )
        blurred = cv2.GaussianBlur(image, (3, 3), 0)
        samples.append((canonical(variant), variant, cost, values, blurred, cv2.cvtColor(blurred, cv2.COLOR_BGR2GRAY)))
    return tuple(samples)


def _add_calibrated_candidates(frame, topleft, values, ranked, allowed):
    """Recover rejected artwork only when its spatial portrait and fingerprint agree.

    Histogram distance alone confused the current bandit with gob_curse and the
    current goblin hut with rune_giant. Require independent color and grayscale
    spatial matching too. A small blur absorbs observed confetti and rescaling.
    """
    left, top = topleft
    portrait = frame[top : top + cards.TOTAL_HEIGHT, left : left + cards.TOTAL_WIDTH]
    blurred = cv2.GaussianBlur(portrait, (3, 3), 0)
    gray = cv2.cvtColor(blurred, cv2.COLOR_BGR2GRAY)
    for name, variant, cost, fingerprint, color_template, gray_template in _calibrated_samples():
        if allowed and name not in allowed:
            continue
        offset = int(np.abs(fingerprint - values).sum())
        if offset > 1200 or (name in ranked and offset >= ranked[name][0]):
            continue
        color_score = float(cv2.matchTemplate(blurred, color_template, cv2.TM_CCOEFF_NORMED)[0, 0])
        gray_score = float(cv2.matchTemplate(gray, gray_template, cv2.TM_CCOEFF_NORMED)[0, 0])
        difference = float(np.mean(cv2.absdiff(blurred, color_template)))
        if min(color_score, gray_score) >= 0.96 and difference <= 12:
            ranked[name] = (offset, variant, cost)


def identify_random_hand(frame, deck_names=None):
    available = set(available_random_slots(frame))
    allowed = set(deck_names or [])
    result = []
    for slot, (left, top) in enumerate(cards.toplefts):
        corners = [
            cards.get_corner_pixels(
                (left + dx, left + dx + cards.HALF_WIDTH), (top + dy, top + dy + cards.HALF_HEIGHT), frame
            )
            for dy in (0, cards.HALF_HEIGHT)
            for dx in (0, cards.HALF_WIDTH)
        ]
        values = np.array([list(value.values()) for value in corners])
        ranked = {}
        offsets = np.abs(FINGERPRINT_MATRIX - values).sum(axis=(1, 2))
        for index, variant in enumerate(VARIANTS):
            name = CANONICAL_NAMES[index]
            if allowed and name not in allowed:
                continue
            offset = int(offsets[index])
            if name not in ranked or offset < ranked[name][0]:
                ranked[name] = (offset, variant, None)
        best = sorted(ranked, key=lambda name: ranked[name][0])
        if not best:
            result.append({"slot": slot, "card": None, "available": False})
            continue
        name = best[0]
        offset, variant, observed_cost = ranked[name]
        margin = ranked[best[1]][0] - offset if len(best) > 1 else 9999
        reliable = offset <= 1200 and margin >= 120
        if not reliable and slot in available:
            _add_calibrated_candidates(frame, (left, top), values, ranked, allowed)
            best = sorted(ranked, key=lambda candidate: ranked[candidate][0])
            name = best[0]
            offset, variant, observed_cost = ranked[name]
            margin = ranked[best[1]][0] - offset if len(best) > 1 else 9999
            reliable = offset <= 1200 and margin >= 120
        role = role_for(variant, observed_cost)
        result.append(
            {
                "slot": slot,
                "card": name if reliable and role else None,
                "variant": variant if reliable else None,
                "candidate": name,
                "available": slot in available and reliable and role is not None,
                "offset": offset,
                "margin": margin,
                "cost": role.cost if reliable and role else None,
            }
        )
    return result
