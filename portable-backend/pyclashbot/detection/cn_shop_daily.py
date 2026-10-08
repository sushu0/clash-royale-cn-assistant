"""Conservative daily-shop observations from native 419 x 633 BGR frames.

No helper sends input. A remembered header is a caller-owned, short-lived
scroll anchor; it is never inferred from prices elsewhere in the shop. Both
payment icons and the live modal controls must be observed before confirming.
"""

from __future__ import annotations

from functools import cache

import cv2
import numpy as np

from pyclashbot.bot.coords import (
    CN_SHOP_DAILY_CANCEL,
    CN_SHOP_DAILY_CARD_HEIGHT,
    CN_SHOP_DAILY_COLUMN_BOUNDS,
    CN_SHOP_DAILY_CONFIRM,
    CN_SHOP_DAILY_CONTENT_ROI,
    CN_SHOP_DAILY_FIRST_BOTTOM_OFFSET,
    CN_SHOP_DAILY_FIXED_ROIS,
    CN_SHOP_DAILY_FREE_CANCEL,
    CN_SHOP_DAILY_FREE_CONFIRM,
    CN_SHOP_DAILY_FREE_GOLD_CANCEL,
    CN_SHOP_DAILY_FREE_GOLD_CONFIRM,
    CN_SHOP_DAILY_HEADER_ROI,
    CN_SHOP_DAILY_REWARD_CONTINUE,
    CN_SHOP_DAILY_ROW_GAP,
    CN_SHOP_GOLD_BALANCE_ROI,
)
from pyclashbot.utils.runtime_config import resource_path

TEMPLATE_ROOT = resource_path("pyclashbot/detection/reference_images/cn_shop_daily")
_SHAPE = (633, 419, 3)


def _valid_frame(frame):
    return isinstance(frame, np.ndarray) and frame.shape == _SHAPE and frame.dtype == np.uint8


@cache
def _template(name):
    path = TEMPLATE_ROOT / f"{name}.png"
    return cv2.imread(str(path)) if path.is_file() else None


def _matches(frame, name, roi, *, threshold=0.94, difference=18, limit=1):
    target = _template(name)
    if target is None:
        return []
    x1, y1, x2, y2 = roi
    patch = frame[max(y1, 0) : min(y2, _SHAPE[0]), max(x1, 0) : min(x2, _SHAPE[1])]
    height, width = target.shape[:2]
    if patch.shape[0] < height or patch.shape[1] < width:
        return []
    score_map = cv2.matchTemplate(patch, target, cv2.TM_CCOEFF_NORMED)
    reference_luma = float(np.mean(cv2.cvtColor(target, cv2.COLOR_BGR2GRAY)))
    result = []
    for _ in range(limit * 8):
        _, score, _, (x, y) = cv2.minMaxLoc(score_map)
        if score < threshold:
            break
        observed = patch[y : y + height, x : x + width]
        luma = float(np.mean(cv2.cvtColor(observed, cv2.COLOR_BGR2GRAY)))
        delta = float(np.mean(np.abs(observed.astype(float) - target.astype(float))))
        if luma >= reference_luma * 0.93 and delta <= difference:
            result.append((x1 + x, y1 + y, float(score), width, height))
            if len(result) >= limit:
                break
        score_map[max(0, y - 8) : y + 9, max(0, x - 8) : x + 9] = -1
    return result


def _point(match):
    x, y, _, width, height = match
    return x + width // 2, y + height // 2


def _shop_verified(frame):
    return bool(
        _matches(frame, "offers_tab", CN_SHOP_DAILY_FIXED_ROIS["offers_tab"])
        and _matches(frame, "shop_label", CN_SHOP_DAILY_FIXED_ROIS["shop_label"])
    )


def _bottoms(frame, column):
    x1, _ = CN_SHOP_DAILY_COLUMN_BOUNDS[column]
    _, y1, _, y2 = CN_SHOP_DAILY_CONTENT_ROI
    result = []
    for name in ("panel_blue_bottom", "panel_green_bottom", "panel_purchased_bottom"):
        if _template(name) is None:
            continue
        for match in _matches(frame, name, (x1 - 2, y1, x1 + 20, y2), threshold=0.92, limit=4):
            bottom = match[1] + match[4]
            if all(abs(bottom - existing) > 8 for existing in result):
                result.append(bottom)
    return sorted(result)


def _fingerprint(frame, bbox):
    x1, _, x2, y2 = bbox
    # Progress and price change after a purchase; portrait identity does not.
    top, bottom = y2 - 158, y2 - 64
    if top < CN_SHOP_DAILY_CONTENT_ROI[1] or bottom > CN_SHOP_DAILY_CONTENT_ROI[3]:
        return None
    portrait = frame[top:bottom, x1 + 22 : x2 - 21]
    gray = cv2.resize(cv2.cvtColor(portrait, cv2.COLOR_BGR2GRAY), (9, 8))
    bits = np.packbits(gray[:, 1:] > gray[:, :-1]).tobytes().hex()
    return bits


def _currency_icon(frame, roi, currency):
    """A colored icon silhouette absorbs subpixel glyph rendering changes.

    Price text is white and the panel is blue/green. Only a compact, calibrated
    yellow coin or green gem component on the price's right can count as money.
    """
    x1, y1, x2, y2 = roi
    patch = frame[y1:y2, x1:x2]
    if patch.size == 0:
        return None
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    limits = ((16, 110, 150), (38, 255, 255)) if currency == "gold" else ((40, 100, 130), (83, 255, 255))
    mask = cv2.inRange(hsv, np.array(limits[0]), np.array(limits[1]))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    candidates = []
    for index, (x, y, width, height, area) in enumerate(stats[1:count], 1):
        if not (10 <= width <= 22 and 12 <= height <= 27 and 95 <= area <= 380):
            continue
        if x < patch.shape[1] * 0.45 or y < 2 or y + height >= patch.shape[0] - 1:
            continue
        shape = (labels[y : y + height, x : x + width] == index).astype(np.uint8) * 255
        shape = cv2.morphologyEx(shape, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)) > 0
        target = _template("gold_icon" if currency == "gold" else "gem_icon")
        if target is None:
            continue
        reference_hsv = cv2.cvtColor(target, cv2.COLOR_BGR2HSV)
        reference = cv2.inRange(reference_hsv, np.array(limits[0]), np.array(limits[1]))
        locations = cv2.findNonZero(reference)
        if locations is None:
            continue
        tx, ty, tw, th = cv2.boundingRect(locations)
        reference = cv2.resize(
            reference[ty : ty + th, tx : tx + tw], (int(width), int(height)), interpolation=cv2.INTER_NEAREST
        )
        reference = cv2.morphologyEx(reference, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)) > 0
        iou = float(np.count_nonzero(shape & reference)) / max(1, np.count_nonzero(shape | reference))
        if iou >= 0.80:
            candidates.append((int(x1 + x), int(y1 + y), iou, int(width), int(height)))
    return candidates[0] if len(candidates) == 1 else None


def _item_currency(frame, x1, x2, bottom):
    roi = (x1 + 8, bottom - 44, x2 - 7, bottom - 8)
    found = []
    for currency, names in (
        ("free", ("free_label",)),
        ("gold", ("gold_icon", "gold_icon_wide", "gold_icon_small")),
        ("gems", ("gem_icon",)),
        ("purchased", ("purchased_label", "purchased_gold_label")),
    ):
        matches = []
        for name in names:
            if _template(name) is not None:
                matches.extend(_matches(frame, name, roi, threshold=0.90, difference=22))
        if not matches and currency in ("gold", "gems"):
            icon = _currency_icon(frame, roi, currency)
            if icon is not None:
                matches.append(icon)
        if currency == "purchased" and matches:
            check_roi = (x1 + 25, bottom - 70, x2 - 20, bottom - 20)
            if not any(
                _matches(frame, name, check_roi, threshold=0.91, difference=22)
                for name in (
                    "purchased_check",
                    "purchased_gold_check",
                    "purchased_check_inertia",
                    "purchased_gold_check_inertia",
                )
            ):
                matches = []
        if matches:
            found.append((currency, max(matches, key=lambda match: match[2])))
    if len(found) != 1:
        return "unknown", None, None
    currency, match = found[0]
    price = 0 if currency == "free" else None
    if currency in ("gold", "gems"):
        # Price crops include every digit. A partial match of 100 inside 1000
        # is rejected by the independent white-glyph segmentation below.
        price = _read_digits(frame[roi[1] : roi[3], roi[0] : match[0]], "price")
    return currency, price, _point(match)[1]


def analyze_shop_frame(frame, daily_anchor_y=None):
    """Observe visible daily cells; slot assignment requires a daily title.

    Header-hidden cells can be used to track a previously seen portrait, but
    have no authorized slot unless the caller supplies its verified anchor.
    """
    result = {
        "valid": _valid_frame(frame),
        "shop_verified": False,
        "daily_header": None,
        "daily_anchor_y": None,
        "visible_items": [],
        "daily_end": False,
    }
    if not result["valid"] or not _shop_verified(frame):
        return result
    result["shop_verified"] = True
    headers = _matches(frame, "daily_title", CN_SHOP_DAILY_HEADER_ROI)
    if headers:
        result["daily_header"] = _point(headers[0])
        daily_anchor_y = result["daily_header"][1]
    if daily_anchor_y is not None and not -400 <= daily_anchor_y <= 550:
        return result
    result["daily_anchor_y"] = daily_anchor_y
    first_bottom = daily_anchor_y + CN_SHOP_DAILY_FIRST_BOTTOM_OFFSET if daily_anchor_y is not None else None
    pitch = CN_SHOP_DAILY_CARD_HEIGHT + CN_SHOP_DAILY_ROW_GAP
    for column, (x1, x2) in enumerate(CN_SHOP_DAILY_COLUMN_BOUNDS):
        for bottom in _bottoms(frame, column):
            row = None
            if first_bottom is not None:
                row = round((bottom - first_bottom) / pitch)
                if row not in (0, 1) or abs(bottom - (first_bottom + row * pitch)) > 9:
                    continue
            currency, price, price_y = _item_currency(frame, x1, x2, bottom)
            bbox = (x1, bottom - CN_SHOP_DAILY_CARD_HEIGHT, x2, bottom)
            result["visible_items"].append(
                {
                    "slot": row * 3 + column if row is not None else None,
                    "column": column,
                    "row": row,
                    "currency": currency,
                    "price": price,
                    "center": ((x1 + x2) // 2, bottom - 30),
                    "price_y": price_y or bottom - 28,
                    "bbox": bbox,
                    "item_id": _fingerprint(frame, bbox),
                }
            )
    result["visible_items"].sort(key=lambda item: (item["price_y"], item["column"]))
    second_row = [item for item in result["visible_items"] if item["row"] == 1]
    result["daily_end"] = len(second_row) == 3 and all(item["bbox"][3] <= 572 for item in second_row)
    return result


def _white_glyphs(patch):
    if patch.size == 0:
        return []
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 2] >= 220) & (hsv[:, :, 1] < 75)).astype(np.uint8) * 255
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    result = []
    for index, (x, y, width, height, area) in enumerate(stats[1:count], 1):
        if area < 20 or height < 8 or width < 3:
            continue
        if x == 0 and y == 0 and (width >= patch.shape[1] - 1 or height >= patch.shape[0] - 1):
            continue
        glyph = ((labels[y : y + height, x : x + width] == index) * 255).astype(np.uint8)
        result.append((int(x), glyph))
    return sorted(result, key=lambda item: item[0])


def _read_digits(patch, style):
    glyphs = _white_glyphs(patch)
    if not 1 <= len(glyphs) <= 7:
        return None
    digits = []
    for x, glyph in glyphs:
        if x == 0 or x + glyph.shape[1] >= patch.shape[1]:
            return None
        observed = cv2.resize(glyph, (16, 24), interpolation=cv2.INTER_NEAREST) > 0
        choices = []
        for digit in range(10):
            target = _template(f"digit_{style}_{digit}")
            if target is None:
                continue
            reference = (
                cv2.resize(cv2.cvtColor(target, cv2.COLOR_BGR2GRAY), (16, 24), interpolation=cv2.INTER_NEAREST) > 0
            )
            score = float(np.count_nonzero(observed & reference)) / max(1, np.count_nonzero(observed | reference))
            choices.append((score, digit))
        choices.sort(reverse=True)
        if not choices or choices[0][0] < 0.74 or (len(choices) > 1 and choices[0][0] - choices[1][0] < 0.07):
            return None
        digits.append(str(choices[0][1]))
    return int("".join(digits))


def read_gold_balance(frame):
    if not _valid_frame(frame) or not _shop_verified(frame):
        return None
    x1, y1, x2, y2 = CN_SHOP_GOLD_BALANCE_ROI
    return _read_digits(frame[y1:y2, x1:x2], "balance")


def confirmation(frame):
    """Recognize calibrated free gifts and card payments independently."""
    if not _valid_frame(frame):
        return None
    free_gold_cues = (
        "free_gold_popup_title",
        "free_gold_popup_close",
        "free_gold_popup_corner",
        "free_gold_popup_bag",
        "free_gold_popup_button_border",
        "free_gold_popup_payment",
    )
    if all(_matches(frame, name, CN_SHOP_DAILY_FIXED_ROIS[name]) for name in free_gold_cues):
        # The amount above the gold bag is the gift quantity, never a price.
        # Only this variant's explicit FREE label authorizes a zero-cost tap.
        return {
            "currency": "free",
            "price": 0,
            "confirm": CN_SHOP_DAILY_FREE_GOLD_CONFIRM,
            "cancel": CN_SHOP_DAILY_FREE_GOLD_CANCEL,
        }
    free_cues = (
        "free_popup_title",
        "free_popup_close",
        "free_popup_corner",
        "free_popup_button_border",
        "free_popup_payment",
    )
    if all(_matches(frame, name, CN_SHOP_DAILY_FIXED_ROIS[name]) for name in free_cues):
        return {
            "currency": "free",
            "price": 0,
            "confirm": CN_SHOP_DAILY_FREE_CONFIRM,
            "cancel": CN_SHOP_DAILY_FREE_CANCEL,
        }
    if not all(
        _matches(frame, name, CN_SHOP_DAILY_FIXED_ROIS[name])
        for name in (
            "popup_close",
            "popup_corner",
            "popup_card_label",
            "popup_button_border",
        )
    ):
        return None
    matches = []
    for currency, names in (
        ("gold", ("popup_gold_icon", "popup_gold_icon_wide")),
        ("gems", ("popup_gem_icon",)),
        ("free", ("popup_free_label",)),
    ):
        found = []
        for name in names:
            if _template(name) is not None:
                found.extend(_matches(frame, name, CN_SHOP_DAILY_FIXED_ROIS["popup_payment"], threshold=0.90))
        if found:
            matches.append((currency, max(found, key=lambda match: match[2])))
    if len(matches) != 1:
        return None
    currency, match = matches[0]
    x1, y1, _, y2 = CN_SHOP_DAILY_FIXED_ROIS["popup_price"]
    price = 0 if currency == "free" else _read_digits(frame[y1:y2, x1 : match[0]], "price")
    if price is None:
        return None
    return {"currency": currency, "price": price, "confirm": CN_SHOP_DAILY_CONFIRM, "cancel": CN_SHOP_DAILY_CANCEL}


def insufficient_gold(frame):
    if not _valid_frame(frame) or _template("insufficient_gold") is None:
        return False
    return bool(_matches(frame, "insufficient_gold", CN_SHOP_DAILY_FIXED_ROIS["insufficient_gold"]))


def reward_state(frame):
    """Unknown reward animations cannot authorize generic continuation taps."""
    if not _valid_frame(frame):
        return None
    purchased_cues = (
        "popup_close",
        "popup_corner",
        "popup_card_label",
        "popup_purchased_label",
        "popup_purchased_check",
    )
    if all(_matches(frame, name, CN_SHOP_DAILY_FIXED_ROIS[name]) for name in purchased_cues):
        return {"kind": "purchased_card", "continue": CN_SHOP_DAILY_CANCEL}
    chest_cues = ("reward_chest_background", "reward_chest_core", "reward_chest_footer")
    if all(_matches(frame, name, CN_SHOP_DAILY_FIXED_ROIS[name], threshold=0.92, difference=22) for name in chest_cues):
        return {"kind": "chest", "continue": CN_SHOP_DAILY_REWARD_CONTINUE}
    complete_cues = (
        "reward_complete_background",
        "reward_complete_core",
        "reward_complete_label",
        "reward_complete_footer",
    )
    if all(
        _matches(frame, name, CN_SHOP_DAILY_FIXED_ROIS[name], threshold=0.92, difference=22) for name in complete_cues
    ):
        return {"kind": "complete", "continue": CN_SHOP_DAILY_REWARD_CONTINUE}
    for kind in ("chest", "cards", "complete"):
        if _template(f"reward_{kind}_title") is None:
            continue
        title = _matches(frame, f"reward_{kind}_title", CN_SHOP_DAILY_FIXED_ROIS["reward_title"])
        floor = _matches(frame, f"reward_{kind}_floor", CN_SHOP_DAILY_FIXED_ROIS["reward_floor"])
        if title and floor:
            return {"kind": kind, "continue": CN_SHOP_DAILY_REWARD_CONTINUE}
    return None
