"""Read-only prototype for Tencent princess-tower health-bar fill.

It estimates a visible fraction, not numeric HP or card damage. It never
interacts with the emulator and is not imported by the running bot.
"""

from __future__ import annotations

import cv2
import numpy as np


BAR_ROIS = {"left": (100, 94, 151, 98), "right": (288, 94, 339, 98)}


def read_fill(frame: np.ndarray, tower_presence: dict[str, bool | None]) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    if not isinstance(frame, np.ndarray) or frame.shape != (633, 419, 3):
        return {side: None for side in BAR_ROIS}
    for side, (x1, y1, x2, y2) in BAR_ROIS.items():
        if tower_presence.get(side) is not True:
            result[side] = None
            continue
        hue, saturation, value = cv2.split(cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2HSV))
        trough = (hue >= 162) & (saturation >= 95) & (value >= 50)
        fill = trough & (saturation >= 100) & (value >= 135)
        widths = trough.sum(axis=1)
        if np.count_nonzero(widths >= 34) < 3:
            result[side] = None
            continue
        rows = fill.sum(axis=1) / np.maximum(widths, 1)
        if float(np.max(rows) - np.min(rows)) > 0.075:
            result[side] = None  # a tower-hit flash made only some rows dark
            continue
        fraction = float(np.median(rows))
        result[side] = round(fraction, 3) if 0 < fraction <= 1 else None
    return result
