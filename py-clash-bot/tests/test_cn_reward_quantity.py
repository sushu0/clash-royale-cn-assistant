"""Reject visually similar amounts rather than treating every coin page as 1000."""

from pathlib import Path

import cv2
import numpy as np

from pyclashbot.detection.cn_reward_quantity import coin_quantity_fallback

FIXTURES = Path(__file__).with_name("fixtures") / "cn_reward_quantity"


def test_actual_1000_glyph_is_recognized_despite_ocr_merging_prefix():
    assert coin_quantity_fallback(cv2.imread(str(FIXTURES / "1000.png"))) == 1000


def test_other_amounts_and_blank_pages_are_not_assumed_to_be_1000():
    for amount in (2000, 3000, 4000):
        assert coin_quantity_fallback(cv2.imread(str(FIXTURES / f"{amount}.png"))) is None
    assert coin_quantity_fallback(np.zeros((633, 419, 3), dtype=np.uint8)) is None
