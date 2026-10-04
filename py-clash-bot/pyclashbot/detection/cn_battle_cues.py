"""Small, conservative cues from the 419x633 Tencent battle screen (BGR).

These are observations, not unit recognition. Call only after confirming a
battle screen, and confirm pressure over two frames before spending on defense.
Occluded level tags and enemies on the far side of the river are deliberately
missed. Arena/UI changes require fresh screenshot calibration.
"""

from functools import lru_cache

import cv2
import numpy as np

from pyclashbot.bot.coords import (
    CN_567_ALLY_ROI,
    CN_HOG_DEFENSE_ROI,
    CN_HOG_ELITE_ABILITY_ROI,
    CN_HOG_ELIXIR_X_COORDS,
    CN_HOG_ELIXIR_Y,
    CN_HOG_ENEMY_TOWER_FILL_ROIS,
    CN_HOG_ENEMY_TOWER_HEALTH_ROIS,
    CN_HOG_FAR_WARNING_ROI,
    CN_HOG_FRIENDLY_TOWER_BOXES,
    CN_HOG_OWN_TOWER_FILL_ROIS,
)
from pyclashbot.detection.cn_threats import read_cn_threats
from pyclashbot.utils.runtime_config import resource_path

# The upstream elixir sample is [240, 137, 244]; Tencent BGR frames also
# show [244, 137, 240]. Keep both palettes and the upstream tolerance.
_ELIXIR_PALETTES = np.array(((240, 137, 244), (244, 137, 240)))
_EMPTY_ELIXIR_BGR = np.array((117, 49, 4))
# Observed fill-boundary pixels and full-bar glint in Tencent screenshots.
# Separate, narrow tolerances preserve the ordinary palette's existing limits.
_ELIXIR_TRANSITION_PALETTES = np.array(((197, 111, 91), (211, 120, 102)))
_ELIXIR_HIGHLIGHT_BGR = np.array((255, 195, 255))


@lru_cache(maxsize=1)
def _level_glyph_templates() -> tuple[np.ndarray, ...]:
    """Load observed level-label crops once; these do not identify troops.

    Crops: 005724/observe-01-005901 (13), observe-04-010752 (14/15),
    and observe-05-010919 (shield 15), under work/hog-validation/20260926-.
    """
    folder = resource_path("pyclashbot/detection/reference_images/cn_enemy_tags")
    templates = []
    for path in sorted(folder.glob("*.png")):
        template = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if template is not None:
            templates.append(cv2.resize(template, (12, 12)))
    return tuple(templates)


@lru_cache(maxsize=1)
def _gold_level_templates() -> tuple[tuple[np.ndarray, np.ndarray], ...]:
    # Separate subdirectory: do not change the old repaired-label or early-air
    # glyph banks. These crops are hostile red plaques with golden numerals,
    # not friendly blue plaques or the gold backgrounds of tower level badges.
    folder = resource_path("pyclashbot/detection/reference_images/cn_enemy_tags/gold")
    loaded = []
    for path in sorted(folder.glob("*.png")):
        color = cv2.imread(str(path))
        if color is not None:
            loaded.append((color, cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)))
    return tuple(loaded)


def _gold_level_plaques(
    frame: np.ndarray, hsv: np.ndarray, roi: tuple[int, int, int, int] = CN_HOG_DEFENSE_ROI
) -> list[tuple[int, int]]:
    """Recognize the observed red-background, gold-numeral hostile style.

    A level number alone never establishes a side. Require a real plaque shape,
    matching BGR colors, gold digit pixels and red background pixels together.
    This intentionally leaves unfamiliar or heavily obscured styles unknown.
    """
    x1, y1, x2, y2 = roi
    region = frame[y1:y2, x1:x2]
    region_gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    centers = []
    for color, gray in _gold_level_templates():
        height, width = color.shape[:2]
        scores = np.minimum(
            cv2.matchTemplate(region, color, cv2.TM_CCOEFF_NORMED),
            cv2.matchTemplate(region_gray, gray, cv2.TM_CCOEFF_NORMED),
        )
        for _ in range(20):
            _, similarity, _, (rx, ry) = cv2.minMaxLoc(scores)
            if similarity < 0.90:
                break
            scores[max(0, ry - 5) : ry + 6, max(0, rx - 5) : rx + 6] = -1
            x, y = rx + x1, ry + y1
            patch = hsv[y : y + height, x : x + width]
            gold = (patch[:, :, 0] >= 10) & (patch[:, :, 0] <= 40) & (patch[:, :, 1] >= 100) & (patch[:, :, 2] >= 140)
            red = ((patch[:, :, 0] <= 9) | (patch[:, :, 0] >= 166)) & (patch[:, :, 1] >= 120) & (patch[:, :, 2] >= 60)
            if float(np.mean(gold)) < 0.20 or float(np.mean(red)) < 0.15:
                continue
            center = (int(x + width // 2), int(y + height // 2))
            if not any(abs(center[0] - a) <= 7 and abs(center[1] - b) <= 7 for a, b in centers):
                centers.append(center)
    return centers


def _local_level_plaques(
    mask: np.ndarray, hsv: np.ndarray, frame: np.ndarray, roi: tuple[int, int, int, int] = CN_HOG_DEFENSE_ROI
) -> list[tuple[int, int]]:
    """Recover square plaques merged with other tags/bars, with glyph checks.

    A red sprite highlight can have a white center too: require four red box
    edges AND a close match to a real numeral plaque. This conservative fallback
    intentionally leaves unfamiliar or heavily obscured text undetected.
    """
    templates = _level_glyph_templates()
    if not templates:
        return []
    binary = (mask > 0).astype(np.float32)
    white = ((hsv[:, :, 1] <= 90) & (hsv[:, :, 2] >= 190)).astype(np.float32)
    white_integral = cv2.integral(white)
    x1, y1, x2, y2 = roi
    found: list[tuple[int, int]] = []
    for width, height in ((9, 10), (10, 10), (9, 9), (10, 11), (11, 11)):
        ring = np.zeros((height, width), dtype=np.float32)
        ring[0, :] = ring[-1, :] = 1
        ring[:, 0] = ring[:, -1] = 1
        scores = cv2.matchTemplate(binary, ring, cv2.TM_CCORR)
        white_count = (
            white_integral[height:, width:]
            - white_integral[:-height, width:]
            - white_integral[height:, :-width]
            + white_integral[:-height, :-width]
        )
        # Exclude solid red placement overlays before entering Python loops.
        area = width * height
        ys, xs = np.where((scores >= 22) & (white_count >= 0.20 * area) & (white_count <= 0.65 * area))
        for y, x in zip(ys, xs):
            if not (x1 <= x <= x2 - width and y1 <= y <= y2 - height):
                continue
            patch = binary[y : y + height, x : x + width]
            if patch[0].sum() < 6 or patch[-1].sum() < 6 or patch[:, 0].sum() < 6 or patch[:, -1].sum() < 4:
                continue
            white_fraction = float(np.mean(white[y : y + height, x : x + width]))
            if not 0.20 <= white_fraction <= 0.65 or not 0.20 <= float(patch.mean()) <= 0.85:
                continue
            glyph = cv2.cvtColor(cv2.resize(frame[y : y + height, x : x + width], (12, 12)), cv2.COLOR_BGR2GRAY)
            similarity = max(float(cv2.matchTemplate(glyph, t, cv2.TM_CCOEFF_NORMED)[0, 0]) for t in templates)
            if similarity < 0.88:
                continue
            center = (int(x + width // 2), int(y + height // 2))
            if not any(abs(center[0] - a) <= 7 and abs(center[1] - b) <= 7 for a, b in found):
                found.append(center)
    return found


def _read_elixir(frame: np.ndarray) -> int | None:
    pixels = frame[CN_HOG_ELIXIR_Y, CN_HOG_ELIXIR_X_COORDS].astype(int)
    filled = np.min(np.max(np.abs(pixels[:, None, :] - _ELIXIR_PALETTES), axis=2), axis=1) <= 65
    filled |= np.max(np.abs(pixels - _ELIXIR_HIGHLIGHT_BGR), axis=1) <= 25
    empty = np.max(np.abs(pixels - _EMPTY_ELIXIR_BGR), axis=1) <= 65
    # Read only the continuous filled prefix. Isolated magenta pixels after a
    # gap indicate an unsuitable/obscured frame, not extra elixir.
    count = 0
    for present in filled:
        if not present:
            break
        count += 1
    if np.any(filled[count:]):
        return None
    if not np.all(filled | empty):
        # A single observed transition color immediately after the filled
        # prefix is an incomplete segment. Return the prefix's lower bound;
        # never round it up, accept a later filled island, or forgive unrelated
        # invalid pixels. Multiple damaged/obscured segments remain unknown.
        transition = np.min(np.max(np.abs(pixels[count] - _ELIXIR_TRANSITION_PALETTES), axis=1)) <= 25
        if not transition or not np.all(empty[count + 1 :]):
            return None
    # Samples lie near each segment's right edge: partial segments never round
    # up. A card must additionally pass the caller's availability check.
    return count


def _enemy_tag_mask(
    frame: np.ndarray, roi: tuple[int, int, int, int] = CN_HOG_DEFENSE_ROI
) -> tuple[np.ndarray, np.ndarray]:
    """Return a red mask and HSV frame for audit/debug as well as detection."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    hue, saturation, value = cv2.split(hsv)
    red = (((hue <= 9) | (hue >= 166)) & (saturation >= 125) & (value >= 75)).astype(np.uint8) * 255
    x1, y1, x2, y2 = roi
    red[:y1] = 0
    red[y2:] = 0
    red[:, :x1] = 0
    red[:, x2:] = 0
    return red, hsv


def _read_enemy_pressure(
    frame: np.ndarray, roi: tuple[int, int, int, int] = CN_HOG_DEFENSE_ROI
) -> list[tuple[int, int]]:
    mask, hsv = _enemy_tag_mask(frame, roi)
    # White digits can split a tiny red level label. Vertical closing repairs
    # that split; also retain raw labels so nearby troops merging during the
    # closing operation do not erase all observations.
    repaired = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 1), dtype=np.uint8))
    centers: list[tuple[int, int]] = []
    for candidate_mask in (mask, repaired):
        _, _, stats, _ = cv2.connectedComponentsWithStats(candidate_mask)
        for x, y, width, height, area in stats[1:]:
            # Most plaques are ~9x10px. Tiny 7-8px versions are allowed only
            # near the bridge: relaxing that height around our towers also
            # matches pink tower trim. Some plaques touch their thin health
            # bar, making the whole red component much wider than the plaque.
            standalone = 7 <= width <= 13 and 9 <= height <= 13
            small_bridge = 7 <= width <= 13 and 7 <= height <= 8 and y <= 300
            attached_bar = 14 <= width <= 44 and 9 <= height <= 13
            if not (standalone or small_bridge or attached_bar):
                continue
            label_width = min(11, width) if attached_bar else width
            if attached_bar:
                # Real dark health troughs include HSV (164,118,93), outside
                # the red plaque palette. With that palette alone a trough
                # becomes a one-pixel bottom edge and incorrectly fails here.
                bar_hsv = hsv[y : y + height, x + 11 : x + width]
                trough = (bar_hsv[:, :, 0] >= 162) & (bar_hsv[:, :, 1] >= 95) & (bar_hsv[:, :, 2] >= 50)
                extension = (candidate_mask[y : y + height, x + 11 : x + width] > 0) | trough
                row_counts = np.count_nonzero(extension, axis=1)
                strong_rows = row_counts >= max(2, (width - 11) * 0.55)
                if not 2 <= int(np.count_nonzero(strong_rows)) <= 7:
                    continue
            label_mask = candidate_mask[y : y + height, x : x + label_width]
            density = float(np.mean(label_mask > 0))
            if not 0.20 <= density <= 0.85:
                continue
            patch = hsv[y : y + height, x : x + label_width]
            white = (patch[:, :, 1] <= 90) & (patch[:, :, 2] >= 190)
            white_fraction = float(np.mean(white))
            if not 0.18 <= white_fraction <= 0.65:
                continue
            if candidate_mask is repaired and label_width <= 8:
                # Closing can join the gold/red trim and white highlights of
                # our tower art into an 8x9 "label". Reject narrow repaired
                # components with almost no numeral evidence; raw plaques and
                # the stricter local-glyph recovery retain their own gates.
                glyph = cv2.cvtColor(
                    cv2.resize(frame[y : y + height, x : x + label_width], (12, 12)),
                    cv2.COLOR_BGR2GRAY,
                )
                similarity = max(
                    (
                        float(cv2.matchTemplate(glyph, template, cv2.TM_CCOEFF_NORMED)[0, 0])
                        for template in _level_glyph_templates()
                    ),
                    default=0.0,
                )
                if similarity < 0.20:
                    continue
            marker = (int(x + label_width // 2), int(y + height // 2))
            if any(abs(marker[0] - cx) <= 7 and abs(marker[1] - cy) <= 7 for cx, cy in centers):
                continue
            centers.append(marker)
    for marker in _local_level_plaques(mask, hsv, frame, roi):
        if not any(abs(marker[0] - x) <= 7 and abs(marker[1] - y) <= 7 for x, y in centers):
            centers.append(marker)
    for marker in _gold_level_plaques(frame, hsv, roi):
        if not any(abs(marker[0] - x) <= 7 and abs(marker[1] - y) <= 7 for x, y in centers):
            centers.append(marker)
    # Level plaques sit above the sprite. This is only an approximate unit
    # center, suitable for lane pressure and broad spell areas, not targeting
    # a particular moving enemy. Do not infer true troop counts from overlaps.
    y_limit = roi[3] - 1
    return sorted((x, min(y + 16, y_limit)) for x, y in centers)


def _read_elite_ability_ready(frame: np.ndarray) -> bool:
    """Recognize the observed bright snowflake button and purple cost badge.

    A gray/dark snowflake is not ready. Do not infer a cooldown duration or an
    ability effect from this observation. All three color regions must agree;
    the fixed ROI was checked against ready, gray and absent real frames.
    """
    x1, y1, x2, y2 = CN_HOG_ELITE_ABILITY_ROI
    patch = frame[y1:y2, x1:x2]
    hue, saturation, value = cv2.split(cv2.cvtColor(patch, cv2.COLOR_BGR2HSV))
    purple_cost = (
        (hue[:25, :25] >= 130) & (hue[:25, :25] <= 175) & (saturation[:25, :25] >= 110) & (value[:25, :25] >= 125)
    )
    body_hue = hue[9:53, 6:56]
    body_saturation = saturation[9:53, 6:56]
    body_value = value[9:53, 6:56]
    snowflake = (body_saturation <= 95) & (body_value >= 205)
    bright_blue = (body_hue >= 85) & (body_hue <= 115) & (body_saturation >= 80) & (body_value >= 150)
    return bool(
        np.count_nonzero(purple_cost) >= 70
        and np.count_nonzero(snowflake) >= 300
        and np.count_nonzero(bright_blue) >= 500
    )


def _read_enemy_towers(frame: np.ndarray) -> dict[str, bool | None]:
    """Observe tower health-bar presence, leaving animation/occlusion unknown.

    The dark purple trough remains visible when only a tiny pink fill is left.
    Require multiple horizontal rows, so white HP digits alone cannot establish
    a tower. Absence is accepted only with a mostly clear arena background.
    """
    towers: dict[str, bool | None] = {}
    for side, (x1, y1, x2, y2) in CN_HOG_ENEMY_TOWER_HEALTH_ROIS.items():
        patch = frame[y1:y2, x1:x2]
        hue, saturation, value = cv2.split(cv2.cvtColor(patch, cv2.COLOR_BGR2HSV))
        # The pink fill and dark-purple trough share this hue interval. In
        # particular, exclude orange/red deployment overlays (hue ~0-10).
        bar = ((hue >= 162) & (saturation >= 95) & (value >= 50)).astype(np.uint8)
        # A real bar is ~40px wide; tolerate partial obscuration down to 24px,
        # but demand a contiguous run rather than unrelated pink speckles.
        long_rows = 0
        for row in bar:
            runs = np.diff(np.concatenate(([0], row, [0])).astype(int))
            lengths = np.flatnonzero(runs == -1) - np.flatnonzero(runs == 1)
            if lengths.size and int(np.max(lengths)) >= 24:
                long_rows += 1
        if long_rows >= 3:
            towers[side] = True
            continue
        background = (hue >= 10) & (hue <= 50) & (saturation < 120) & (value >= 150)
        if int(np.count_nonzero(bar)) <= 2 and float(np.mean(background)) >= 0.85:
            towers[side] = False
        else:
            # Crowns, explosions, dark overlays and low/unfamiliar bar colors
            # must never become positive evidence of a destroyed tower.
            towers[side] = None
    return towers


def _read_enemy_tower_fill(frame: np.ndarray, towers: dict[str, bool | None]) -> dict[str, float | None]:
    """Estimate a *visible* bar fraction; do not interpret it as exact HP.

    The full bar and the 437-HP frame were independently checked against real
    screenshots. Occluded or unfamiliar troughs stay unknown, not zero HP.
    """
    values: dict[str, float | None] = {}
    for side, (x1, y1, x2, y2) in CN_HOG_ENEMY_TOWER_FILL_ROIS.items():
        if towers.get(side) is not True:
            values[side] = None
            continue
        hue, saturation, value = cv2.split(cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2HSV))
        trough = (hue >= 162) & (saturation >= 95) & (value >= 50)
        fill = trough & (saturation >= 100) & (value >= 135)
        widths = trough.sum(axis=1)
        if np.count_nonzero(widths >= 34) < 3:
            values[side] = None
            continue
        rows = fill.sum(axis=1) / np.maximum(widths, 1)
        # The hit flash can darken two of the four rows while the numeric HP
        # and true bar are unchanged. A median would halve the apparent HP.
        if float(np.max(rows) - np.min(rows)) > 0.075:
            values[side] = None
            continue
        fraction = float(np.median(rows))
        values[side] = round(fraction, 3) if 0 < fraction <= 1 else None
    return values


def _read_own_tower_fill(frame: np.ndarray) -> dict[str, float | None]:
    """Read stable blue bar rows across the observed three-pixel skin offset."""
    values: dict[str, float | None] = {}
    for side, (x1, y1, x2, y2) in CN_HOG_OWN_TOWER_FILL_ROIS.items():
        # The standard skin puts the two filled rows at 394-395. Other real
        # skins move them up as far as 386-388. Prefer the dark trough row immediately
        # above the filled pair; one observed skin has no readable trough, so
        # admit it only when three adjacent filled rows agree instead.
        hue, saturation, value = cv2.split(cv2.cvtColor(frame[y1 - 12 : y2, x1:x2], cv2.COLOR_BGR2HSV))
        trough = (hue >= 85) & (hue <= 125) & (saturation >= 70) & (value >= 40)
        fill = trough & (saturation >= 80) & (value >= 125)
        widths = trough.sum(axis=1)
        rows = fill.sum(axis=1) / np.maximum(widths, 1)
        values[side] = None
        for first in range(1, len(rows) - 1):
            if (
                widths[first - 1] >= 34
                and rows[first - 1] <= 0.05
                and widths[first] >= 34
                and widths[first + 1] >= 34
                and rows[first] > 0
                and rows[first + 1] > 0
                and abs(float(rows[first] - rows[first + 1])) <= 0.075
            ):
                fraction = float(np.median(rows[first : first + 2]))
                values[side] = round(fraction, 3) if fraction <= 1 else None
                break
        if values[side] is None:
            for first in range(1, len(rows) - 2):
                window = rows[first : first + 3]
                if (
                    widths[first - 1] < 34
                    and np.all(widths[first : first + 3] >= 34)
                    and np.all(window > 0)
                    and float(np.max(window) - np.min(window)) <= 0.075
                ):
                    values[side] = round(float(np.median(window)), 3)
                    break
    return values


def _read_dark_ground_candidates(frame: np.ndarray, markers: list[tuple[int, int]]) -> list[dict]:
    """Measure a dark sprite body below real red plaques; movement is checked later.

    This is not a unit identity. The frozen Royal Recruit and armored-unit
    frames can both pass, while a stationary siege object can also look dark.
    Requiring a downward track in the policy prevents that static false cue.
    """
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    found: list[dict] = []
    for x, y in sorted(set(markers)):
        if not (30 <= x <= 389 and 190 <= y <= 310):
            continue
        if any(abs(x - item["x"]) <= 7 and abs(y - item["y"]) <= 7 for item in found):
            continue
        patch = hsv[y - 10 : y + 30, x - 20 : x + 20]
        dark = (patch[:, :, 2] < 90) & (patch[:, :, 1] < 150)
        pixels = int(np.count_nonzero(dark))
        if pixels >= 330:
            found.append({"x": x, "y": y, "dark_pixels": pixels})
    return found


def _read_allied_labels(frame: np.ndarray) -> list[tuple[int, int]]:
    """Blue square level plaques with white/gold digits, excluding tower art.

    This is only a live allied anchor, not identity or health. The policy also
    requires association with a confirmed deployment and a continuous track.
    """
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    hue, sat, value = cv2.split(hsv)
    blue = ((hue >= 96) & (hue <= 120) & (sat >= 120) & (value >= 100)).astype(np.uint8)
    x1, y1, x2, y2 = CN_567_ALLY_ROI
    blue[:y1] = blue[y2:] = 0
    blue[:, :x1] = blue[:, x2:] = 0
    for a, b, c, d in CN_HOG_FRIENDLY_TOWER_BOXES.values():
        blue[b - 12 : d + 5, a - 12 : c + 12] = 0
    count, _, stats, _ = cv2.connectedComponentsWithStats(blue, connectivity=8)
    points = []
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        if not (7 <= w <= 22 and 7 <= h <= 16 and area >= 24):
            continue
        patch = hsv[y : y + h, x : x + w]
        digit = (patch[:, :, 1] <= 85) & (patch[:, :, 2] >= 190)
        digit |= (patch[:, :, 0] >= 15) & (patch[:, :, 0] <= 38) & (patch[:, :, 2] >= 190)
        if np.count_nonzero(digit) >= 8:
            points.append((int(x + w // 2), int(y + h // 2 + 16)))
    # A friendly plaque often touches its health bar or a blue troop sprite.
    # Match the calibrated plaque itself instead of requiring an isolated blob.
    template = _allied_level_template()
    if template is not None:
        roi = frame[y1:y2, x1:x2]
        scores = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
        for _ in range(20):
            _, score, _, (rx, ry) = cv2.minMaxLoc(scores)
            if score < 0.90:
                break
            scores[max(0, ry - 5) : ry + 6, max(0, rx - 5) : rx + 6] = -1
            x, y = rx + x1, ry + y1
            if any(
                a - 12 <= x <= c + 12 and b - 12 <= y <= d + 5 for a, b, c, d in CN_HOG_FRIENDLY_TOWER_BOXES.values()
            ):
                continue
            point = (x + template.shape[1] // 2, y + template.shape[0] // 2 + 16)
            if not any(abs(point[0] - a) <= 7 and abs(point[1] - b) <= 7 for a, b in points):
                points.append(point)
    return points


@lru_cache(maxsize=1)
def _allied_level_template():
    return cv2.imread(str(resource_path("pyclashbot/detection/reference_images/cn_567/ally_level11.png")))


def read_cn_battle_cues(frame: np.ndarray, *, include_567: bool = False) -> dict:
    """Return conservative elixir and visible enemy pressure on our half.

    Unknown elixir is ``None``. No recognized plaque means ``enemies=[]``;
    it does not prove that the lane is safe. A separate bounded visual-template
    helper supplies a few high-confidence threat classes; everything else stays
    unknown. There is no OCR, learned model, emulator interaction or network API.
    ``enemy_towers`` reports health-bar presence; an absent unobscured bar is
    ``False``, and uncertainty is ``None``. Confirm destruction over three
    frames before switching attack lanes.
    """
    if not isinstance(frame, np.ndarray) or frame.dtype != np.uint8 or frame.shape != (633, 419, 3):
        return {
            "elixir": None,
            "enemies": [],
            "far_warnings": [],
            "enemy_towers": {"left": None, "right": None},
            "enemy_tower_fill": {"left": None, "right": None},
            "own_tower_fill": {"left": None, "right": None},
            "elite_ability_ready": False,
            "threats": [],
            "dark_ground_candidates": [],
        }
    enemies = _read_enemy_pressure(frame)
    far_warnings = _read_enemy_pressure(frame, CN_HOG_FAR_WARNING_ROI)
    dark_ground_candidates = _read_dark_ground_candidates(frame, enemies + far_warnings)
    threats = read_cn_threats(frame, enemies, include_early_air=True, include_567=include_567)
    for threat in threats:
        if threat.get("origin") in {"early_air", "567_role"}:
            point = (threat["x"], threat["y"])
            if not any(abs(point[0] - x) <= 7 and abs(point[1] - y) <= 7 for x, y in enemies):
                enemies.append(point)
    enemies.sort()
    towers = _read_enemy_towers(frame)
    result = {
        "elixir": _read_elixir(frame),
        "enemies": enemies,
        "far_warnings": far_warnings,
        "enemy_towers": towers,
        "enemy_tower_fill": _read_enemy_tower_fill(frame, towers),
        "own_tower_fill": _read_own_tower_fill(frame),
        "elite_ability_ready": _read_elite_ability_ready(frame),
        "threats": threats,
        "dark_ground_candidates": dark_ground_candidates,
    }
    if include_567:
        result["allies"] = _read_allied_labels(frame)
    return result
