"""Vectorized BGR matching preserves frozen decisions, margins, and abstention."""

import json
from pathlib import Path

import cv2
import pytest

from pyclashbot.detection.cn_random_hand import identify_random_hand

FIXTURES = Path(__file__).parent / "fixtures/cn_random_hand"
SAMPLES = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda s: s["file"])
def test_optimized_matcher_preserves_existing_card_and_confidence(sample):
    assert identify_random_hand(cv2.imread(str(FIXTURES / sample["file"]))) == sample["hand"]


def test_restricted_deck_never_selects_unlisted_card():
    hand = identify_random_hand(cv2.imread(str(FIXTURES / SAMPLES[0]["file"])), ["hog", "knight"])
    assert all(item.get("card") in (None, "hog", "knight") for item in hand)
    unknown = identify_random_hand(cv2.imread(str(FIXTURES / SAMPLES[0]["file"])), ["not_a_card"])
    assert all(not item["available"] and item["card"] is None for item in unknown)
