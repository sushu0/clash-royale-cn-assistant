"""Calibrated Chinese random-deck and mastery UI, for BGR 419x633 frames."""

from functools import cache

import cv2
import numpy as np

from pyclashbot.bot.coords import (
    CN_RANDOM_CARD_AVAILABLE_ROIS,
    CN_RANDOM_CLAIM_ALL_BUTTON_ROI,
    CN_RANDOM_DECK_ROIS,
    CN_RANDOM_MASTERY_CLAIM_ROI,
    CN_RANDOM_MASTERY_COLUMNS,
    CN_RANDOM_MASTERY_FOOTER_ROI,
    CN_RANDOM_MASTERY_LIST_ROI,
    CN_RANDOM_UI_ROIS,
)
from pyclashbot.utils.runtime_config import resource_path

TEMPLATE_ROOT = resource_path("pyclashbot/detection/reference_images/cn_random_mastery")


@cache
def _template(name):
    result = cv2.imread(str(TEMPLATE_ROOT / f"{name}.png"))
    if result is None:
        raise RuntimeError(f"Missing calibrated random/mastery template: {name}")
    return result


def random_ui_is(frame, name):
    if frame is None or frame.shape != (633, 419, 3):
        return False
    x1, y1, x2, y2 = CN_RANDOM_UI_ROIS[name]
    patch = frame[y1:y2, x1:x2]
    variants = (name, "collection_tab_20261005") if name == "collection" else (name,)
    for variant in variants:
        target = _template(variant)
        if (
            patch.shape != target.shape
            or float(np.mean(np.abs(patch.astype(float) - target.astype(float)))) >= 22
            or float(cv2.matchTemplate(patch, target, cv2.TM_CCOEFF_NORMED)[0, 0]) < 0.93
        ):
            continue
        if name == "collection":
            brightness = float(np.mean(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)))
            reference_brightness = float(np.mean(cv2.cvtColor(target, cv2.COLOR_BGR2GRAY)))
            if brightness < reference_brightness * 0.95:
                continue
        return True
    return False


def deck_portraits(frame):
    return [cv2.resize(frame[y1:y2, x1:x2], (24, 24)) for x1, y1, x2, y2 in CN_RANDOM_DECK_ROIS]


def changed_deck_slots(before, after):
    return sum(
        float(np.mean(np.abs(a.astype(float) - b.astype(float)))) > 15 for a, b in zip(before, after, strict=True)
    )


def available_random_slots(frame):
    result = []
    palettes = np.array(((255, 43, 227), (227, 43, 255)))
    for slot, (x1, y1, x2, y2) in enumerate(CN_RANDOM_CARD_AVAILABLE_ROIS):
        pixels = frame[y1:y2, x1:x2].astype(int)
        distances = np.min(np.max(np.abs(pixels[:, :, None, :] - palettes), axis=3), axis=2)
        if np.count_nonzero(distances <= 35) >= 26:
            result.append(slot)
    return result


def mastery_card_points(frame):
    """Recover full visible card rows from several border shapes, including heroes."""
    x1, y1, x2, y2 = CN_RANDOM_MASTERY_LIST_ROI
    edges = cv2.Canny(frame[y1:y2, x1:x2], 30, 90)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    centers = []
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        if 48 <= width <= 66 and 65 <= height <= 86:
            center = y + y1 + height // 2
            if 155 <= center <= 429:
                centers.append(center)
    rows = []
    for center in sorted(centers):
        if not rows or center - rows[-1][-1] > 16:
            rows.append([center])
        else:
            rows[-1].append(center)
    result = []
    for row in rows:
        y = int(np.median(row))
        for x in CN_RANDOM_MASTERY_COLUMNS:
            # The last row can contain only one card. Never click its blank cells.
            portrait = frame[y - 22 : y + 22, x - 20 : x + 20]
            gray = cv2.cvtColor(portrait, cv2.COLOR_BGR2GRAY)
            if float(np.std(gray)) >= 18 and float(np.mean(cv2.Canny(gray, 30, 90) > 0)) >= 0.025:
                result.append((x, y))
    return result


def mastery_claim_points(frame):
    """Green completed-task controls inside an already verified mastery detail."""
    if not (random_ui_is(frame, "mastery_detail") or random_ui_is(frame, "mastery_locked")):
        return []
    x1, y1, x2, y2 = CN_RANDOM_MASTERY_CLAIM_ROI
    hsv = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array((35, 140, 150)), np.array((78, 255, 255)))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    points = []
    for x, y, width, height, area in stats[1:count]:
        if width >= 60 and height >= 20 and area >= 700:
            points.append((int(x + x1 + width // 2), int(y + y1 + height // 2)))
    return sorted(points, key=lambda point: point[1])


def mastery_footer_state(frame, text=""):
    """Only the bottom Claim all control decides whether rewards are available."""
    if not random_ui_is(frame, "mastery_list"):
        return "unknown"
    x1, y1, x2, y2 = CN_RANDOM_CLAIM_ALL_BUTTON_ROI
    button = frame[y1:y2, x1:x2]
    target = _template("mastery_claim_all")
    # A captured label and button must agree; yellow color alone is insufficient.
    if (
        button.shape == target.shape
        and float(np.mean(np.abs(button.astype(float) - target.astype(float)))) < 22
        and float(cv2.matchTemplate(button, target, cv2.TM_CCOEFF_NORMED)[0, 0]) >= 0.93
    ):
        return "claim_all"
    x1, y1, x2, y2 = CN_RANDOM_MASTERY_FOOTER_ROI
    patch = frame[y1:y2, x1:x2]
    target = _template("mastery_no_rewards")
    if (
        float(np.mean(np.abs(patch.astype(float) - target.astype(float)))) < 18
        and float(cv2.matchTemplate(patch, target, cv2.TM_CCOEFF_NORMED)[0, 0]) >= 0.92
    ):
        return "none"
    return mastery_footer_text_state(text)


def mastery_footer_text_state(text):
    normalized = "".join(text.split())
    if "领取全部" in normalized:
        return "claim_all"
    if "完成卡牌大师任务" in normalized and "解锁更多奖励" in normalized:
        return "none"
    return "unknown"
