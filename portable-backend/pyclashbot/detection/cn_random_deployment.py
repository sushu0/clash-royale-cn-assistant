"""Confirm a card cycle using independent elixir and stable hand evidence."""

from functools import lru_cache

import cv2
import numpy as np

from pyclashbot.bot.coords import CN_RANDOM_CONSUMED_SLOT_ROIS, CN_RANDOM_HAND_ROIS
from pyclashbot.bot.random_card_roles import canonical
from pyclashbot.detection.cn_random_hand import identify_random_hand
from pyclashbot.utils.runtime_config import resource_path


@lru_cache(maxsize=1)
def _consumed_template():
    path = resource_path("pyclashbot/detection/reference_images/cn_random_cards/consumed_slot.png")
    target = cv2.imread(str(path))
    if target is None:
        raise RuntimeError("Missing consumed-slot reference")
    return target


def slot_was_consumed(frame, slot):
    x1, y1, x2, y2 = CN_RANDOM_CONSUMED_SLOT_ROIS[slot]
    patch = frame[y1:y2, x1:x2]
    target = _consumed_template()
    return (
        patch.shape == target.shape
        and float(np.mean(np.abs(patch.astype(float) - target.astype(float)))) < 12
        and float(cv2.matchTemplate(patch, target, cv2.TM_CCOEFF_NORMED)[0, 0]) >= 0.95
    )


def deployment_evidence(
    before, after, slot, played_card, before_elixir, after_elixir, previous_after_card=None, selected_was_empty=False
):
    x1, y1, x2, y2 = CN_RANDOM_HAND_ROIS[slot]
    difference = float(np.mean(np.abs(before[y1:y2, x1:x2].astype(float) - after[y1:y2, x1:x2].astype(float))))
    after_card = identify_random_hand(after)[slot].get("card")
    confirmed, method = False, "awaiting_cycle"
    if after_elixir is not None and difference > 12:
        if after_elixir < before_elixir:
            confirmed, method = True, "elixir_drop_and_portrait"
        elif (
            not selected_was_empty
            and not slot_was_consumed(before, slot)
            and slot_was_consumed(after, slot)
            and after_elixir <= before_elixir + 1
        ):
            confirmed, method = True, "consumed_hand_slot"
        elif (
            after_card
            and after_card != canonical(played_card)
            and after_card == previous_after_card
            and after_elixir <= before_elixir + 1
        ):
            # A one-elixir card can regenerate before the screenshot arrives.
            # Require the replacement identity on two consecutive normal hand frames.
            confirmed, method = True, "stable_replacement_card"
    return {"confirmed": confirmed, "method": method, "after_card": after_card, "portrait_change": round(difference, 2)}
