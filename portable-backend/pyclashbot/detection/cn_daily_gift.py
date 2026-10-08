"""Recognize the observed daily gift screen before choosing cosmetics.

This is a narrow action resolver for the Chinese client at 419 x 633. It
requires the event title, all three exact choice labels in their own rows,
and the purple cosmetic-choice panel. Unknown or rearranged screens return
None so an arbitrary reward button can never become a cosmetic choice.
"""

from functools import cache

import cv2
import numpy as np

from pyclashbot.bot.coords import (
    CN_DAILY_GIFT_COSMETIC_CHOICE,
    CN_DAILY_GIFT_COSMETIC_LABEL_ROI,
    CN_DAILY_GIFT_COSMETIC_PANEL_ROI,
    CN_DAILY_GIFT_EMOTE_ICON_ROI,
    CN_DAILY_GIFT_EMOTE_TITLE_ROI,
    CN_DAILY_GIFT_LUCK_LABEL_ROI,
    CN_DAILY_GIFT_RICH_LABEL_ROI,
    CN_DAILY_GIFT_TITLE_ROI,
    CN_POST_WIN_REWARD_TAP,
)
from pyclashbot.detection.image_rec import find_image
from pyclashbot.utils.runtime_config import resource_path

DAILY_GIFT_COSMETIC_ACTION = "choose_daily_cosmetic"
DAILY_GIFT_EMOTE_REWARD_ACTION = "continue_daily_gift_reward"
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


@cache
def _reward_template(name):
    path = resource_path(f"pyclashbot/detection/reference_images/cn_daily_gift/{name}.png")
    return cv2.imread(str(path)) if path.is_file() else None


def daily_gift_reward_action(frame: np.ndarray | None) -> tuple[str, tuple[int, int]] | None:
    """Continue this recorded emote reveal only within the caller's daily context."""
    if not isinstance(frame, np.ndarray) or frame.shape != DAILY_GIFT_SHAPE or frame.dtype != np.uint8:
        return None
    for name, roi in (
        ("emote_reveal_title_20261006", CN_DAILY_GIFT_EMOTE_TITLE_ROI),
        ("emote_reveal_icon_20261006", CN_DAILY_GIFT_EMOTE_ICON_ROI),
    ):
        template = _reward_template(name)
        x1, y1, x2, y2 = roi
        patch = frame[y1:y2, x1:x2]
        if template is None or template.shape != patch.shape or template.dtype != np.uint8:
            return None
        reference_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        if float(np.std(reference_gray)) < 12:
            return None
        if float(cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED)[0, 0]) < 0.95:
            return None
        brightness = float(np.mean(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)))
        if brightness < float(np.mean(reference_gray)) * 0.95:
            return None
        if float(np.mean(np.abs(patch.astype(np.float32) - template.astype(np.float32)))) > 12:
            return None
    return DAILY_GIFT_EMOTE_REWARD_ACTION, CN_POST_WIN_REWARD_TAP
