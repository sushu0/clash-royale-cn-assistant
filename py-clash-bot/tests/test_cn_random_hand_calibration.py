"""Real held-out hand artwork and conservative negative controls."""

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from pyclashbot.bot import card_detection as cards
from pyclashbot.bot.random_card_roles import role_for
from pyclashbot.detection.cn_random_hand import CALIBRATION_ROOT, FINGERPRINTS, identify_random_hand

FIXTURES = Path(__file__).parent / "fixtures/cn_random_hand/calibration_20261003"
SAMPLES = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))


def _frame(sample):
    path = FIXTURES / sample["file"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == sample["sha256"]
    frame = np.zeros((633, 419, 3), dtype=np.uint8)
    x1, y1, x2, y2 = sample["source_roi"]
    frame[y1:y2, x1:x2] = cv2.imread(str(path))
    return frame


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda item: item["file"])
def test_current_artwork_on_independent_regular_overtime_and_user_frames(sample):
    hand = identify_random_hand(_frame(sample))
    assert [item["card"] for item in hand] == sample["expected_cards"]
    assert [item["variant"] for item in hand] == sample["expected_variants"]
    assert [item["cost"] for item in hand] == sample["expected_costs"]
    assert all(item["available"] and item["offset"] <= 1200 and item["margin"] >= 120 for item in hand)
    # This cost reaches the policy through its existing observed-cost argument.
    assert role_for(hand[3]["variant"], hand[3]["cost"]).cost == 4


def test_current_calibrations_are_hashed_real_portraits_with_source_and_cost_provenance():
    manifest = json.loads((CALIBRATION_ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["channel_order"] == "BGR"
    assert len(manifest["samples"]) == 6
    for sample in manifest["samples"]:
        path = CALIBRATION_ROOT / sample["file"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == sample["sha256"]
        assert len(sample["source_sha256"]) == 64 and sample["source_session"] == "20261003-182719"
        assert sample["source_roi"][3] - sample["source_roi"][1] == 66
        assert sample["source_roi"][2] - sample["source_roi"][0] == 54
        assert sample["observed_cost"] in (3, 4, 5)


def test_gray_unaffordable_current_cards_are_not_made_available():
    frame = cv2.cvtColor(cv2.cvtColor(_frame(SAMPLES[0]), cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    hand = identify_random_hand(frame)
    assert all(not item["available"] for item in hand)
    assert all(item["card"] is None for item in hand[1:])


def test_same_histograms_without_matching_portraits_remain_unknown():
    frame = _frame(SAMPLES[0])
    rng = np.random.default_rng(73)
    # Exact per-quadrant histogram preservation deliberately spoofs all three
    # new fingerprints. Independent spatial gates must still reject the cards.
    for left, top in cards.toplefts[1:]:
        for dy in (0, cards.HALF_HEIGHT):
            for dx in (0, cards.HALF_WIDTH):
                region = frame[top + dy : top + dy + cards.HALF_HEIGHT, left + dx : left + dx + cards.HALF_WIDTH]
                values = region.reshape(-1, 3).copy()
                rng.shuffle(values)
                region[:] = values.reshape(region.shape)
    hand = identify_random_hand(frame)
    assert all(item["card"] is None and not item["available"] for item in hand[1:])


@pytest.mark.parametrize(("name", "slot"), [("gob_curse", 2), ("rune_giant", 3)])
def test_old_confusing_fingerprints_keep_their_original_identity(name, slot):
    frame = _frame(SAMPLES[0])
    left, top = cards.toplefts[slot]
    rng = np.random.default_rng(12)
    for index, (dy, dx) in enumerate((dy, dx) for dy in (0, cards.HALF_HEIGHT) for dx in (0, cards.HALF_WIDTH)):
        counts = FINGERPRINTS[name][index].astype(int)
        pixels = np.repeat(cards.COLORS_ARRAY.astype(np.uint8), counts, axis=0)
        assert len(pixels) == cards.HALF_HEIGHT * cards.HALF_WIDTH
        rng.shuffle(pixels)
        frame[top + dy : top + dy + cards.HALF_HEIGHT, left + dx : left + dx + cards.HALF_WIDTH] = pixels.reshape(
            cards.HALF_HEIGHT, cards.HALF_WIDTH, 3
        )
    item = identify_random_hand(frame)[slot]
    assert item["card"] == name and item["variant"] == name and item["offset"] == 0


def test_supplement_does_not_bypass_restricted_deck():
    hand = identify_random_hand(_frame(SAMPLES[0]), ["earthquake"])
    assert all(item["card"] in (None, "earthquake") for item in hand)
    assert all(not item["available"] for item in hand[1:])
