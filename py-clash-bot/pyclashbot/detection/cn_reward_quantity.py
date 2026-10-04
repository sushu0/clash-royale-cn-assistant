"""Conservative fallback for the known 1000-coin glyph, rejecting other amounts."""

from functools import lru_cache

import cv2
import numpy as np

from pyclashbot.bot.coords import CN_RANDOM_REWARD_QUANTITY_SEARCH_ROI
from pyclashbot.utils.runtime_config import resource_path

ROOT = resource_path("pyclashbot/detection/reference_images/cn_reward_quantity")


@lru_cache(maxsize=1)
def _templates():
    return {
        amount: cv2.imread(str(ROOT / f"{amount}.png"), cv2.IMREAD_GRAYSCALE) for amount in (1000, 2000, 3000, 4000)
    }


def coin_quantity_fallback(frame):
    if frame is None or frame.shape != (633, 419, 3):
        return None
    x1, y1, x2, y2 = CN_RANDOM_REWARD_QUANTITY_SEARCH_ROI
    region = frame[y1:y2, x1:x2]
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    white = cv2.inRange(hsv, np.array((0, 0, 245)), np.array((179, 85, 255)))
    scores = []
    for amount, template in _templates().items():
        if template is None:
            return None
        score = float(cv2.minMaxLoc(cv2.matchTemplate(white, template, cv2.TM_CCOEFF_NORMED))[1])
        scores.append((score, amount))
    scores.sort(reverse=True)
    best, amount = scores[0]
    return 1000 if amount == 1000 and best >= 0.82 and best - scores[1][0] >= 0.12 else None
