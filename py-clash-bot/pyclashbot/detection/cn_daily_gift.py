"""Recognize the observed daily gift screen before choosing cosmetics.

This is a narrow action resolver for the Chinese client at 419 x 633. It
requires the event title, all three exact choice labels in their own rows,
and the purple cosmetic-choice panel. Unknown or rearranged screens return
None so an arbitrary reward button can never become a cosmetic choice.
"""

import cv2
import numpy as np

from pyclashbot.bot.coords import (
    CN_DAILY_GIFT_COSMETIC_CHOICE,
    CN_DAILY_GIFT_COSMETIC_LABEL_ROI,
    CN_DAILY_GIFT_COSMETIC_PANEL_ROI,
    CN_DAILY_GIFT_LUCK_LABEL_ROI,
    CN_DAILY_GIFT_RICH_LABEL_ROI,
    CN_DAILY_GIFT_TITLE_ROI,
)
from pyclashbot.detection.image_rec import find_image

DAILY_GIFT_COSMETIC_ACTION = "choose_daily_cosmetic"
DAILY_GIFT_SHAPE = (633, 419, 3)
_CHOICE_CUES = (
    ("title", CN_DAILY_GIFT_TITLE_ROI),
    ("rich", CN_DAILY_GIFT_RICH_LABEL_ROI),
    ("luck", CN_DAILY_GIFT_LUCK_LABEL_ROI),
    ("cosmetic", CN_DAILY_GIFT_COSMETIC_LABEL_ROI),
)


def daily_gift_action(frame: np.ndarray | None) -> tuple[str, tuple[int, int]] | None:
    """Return the authorized choice only for the verified daily gift screen.

    The caller must take a current screenshot immediately before calling and
    should observe the resulting screen after the click. Day counters and
    reward artwork are intentionally excluded from the text templates because
    they can change on following days.
    """
    if not isinstance(frame, np.ndarray) or frame.shape != DAILY_GIFT_SHAPE or frame.dtype != np.uint8:
        return None
    x1, y1, x2, y2 = CN_DAILY_GIFT_COSMETIC_PANEL_ROI
    hsv = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    purple = (hsv[:, :, 0] >= 110) & (hsv[:, :, 0] <= 165) & (hsv[:, :, 1] >= 65) & (hsv[:, :, 2] >= 110)
    if float(np.mean(purple)) < 0.38:
        return None
    for cue, roi in _CHOICE_CUES:
        if find_image(frame, f"cn_daily_gift/{cue}", tolerance=0.88, subcrop=roi) is None:
            return None
    return DAILY_GIFT_COSMETIC_ACTION, CN_DAILY_GIFT_COSMETIC_CHOICE
