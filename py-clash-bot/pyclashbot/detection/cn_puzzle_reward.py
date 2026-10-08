"""Recorded puzzle reward entry/reveal cues; caller owns the post-battle context."""

from functools import cache

import cv2
import numpy as np

from pyclashbot.bot.coords import CN_POST_WIN_REWARD_TAP, CN_PUZZLE_REWARD_ROIS, CN_PUZZLE_REWARD_SEARCH_ROIS
from pyclashbot.utils.runtime_config import resource_path

TEMPLATE_ROOT = resource_path("pyclashbot/detection/reference_images/cn_puzzle_reward")
ENTRY_SCALE_FACTORS = {
    "entry_question": tuple(value / 200 for value in range(188, 205)),
    "entry_open_label": tuple(value / 200 for value in range(160, 204)),
}


@cache
def _template(name):
    path = TEMPLATE_ROOT / f"{name}.png"
    return cv2.imread(str(path)) if path.is_file() else None


def _matches(frame, cue, name):
    target = _template(name)
    x1, y1, x2, y2 = CN_PUZZLE_REWARD_ROIS[cue]
    if target is None or target.shape != (y2 - y1, x2 - x1, 3) or target.dtype != np.uint8:
        return False
    if float(np.std(cv2.cvtColor(target, cv2.COLOR_BGR2GRAY))) < 8:
        return False
    x1, y1, x2, y2 = CN_PUZZLE_REWARD_SEARCH_ROIS[cue]
    region = frame[y1:y2, x1:x2]
    for scale in ENTRY_SCALE_FACTORS.get(cue, (1.0,)):
        scaled = (
            target if scale == 1.0 else cv2.resize(target, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
        )
        if scaled.shape[0] > region.shape[0] or scaled.shape[1] > region.shape[1]:
            continue
        _, score, _, (x, y) = cv2.minMaxLoc(cv2.matchTemplate(region, scaled, cv2.TM_CCOEFF_NORMED))
        if score < 0.95:
            continue
        patch = region[y : y + scaled.shape[0], x : x + scaled.shape[1]]
        reference_gray = cv2.cvtColor(scaled, cv2.COLOR_BGR2GRAY)
        if float(np.mean(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY))) < float(np.mean(reference_gray)) * 0.95:
            continue
        if float(np.mean(np.abs(patch.astype(np.float32) - scaled.astype(np.float32)))) <= 16:
            return True
    return False


def puzzle_reward_action(frame: np.ndarray | None) -> tuple[str, tuple[int, int]] | None:
    """Resolve two recorded cues, never authorize an action from blue sky alone."""
    if not isinstance(frame, np.ndarray) or frame.shape != (633, 419, 3) or frame.dtype != np.uint8:
        return None
    if any(
        _matches(frame, "entry_open_label", name)
        for name in ("entry_open_label_20261007", "entry_open_label_20261007_phase2")
    ) and any(
        _matches(frame, "entry_question", name)
        for name in ("entry_question_20261007_phase1", "entry_question_20261007_phase2")
    ):
        return "open_puzzle_reward", CN_POST_WIN_REWARD_TAP
    if any(
        _matches(frame, "reveal_title", title) and _matches(frame, "reveal_unlocked", unlocked)
        for title, unlocked in (
            ("reveal_title_20261007", "reveal_unlocked_20261007"),
            ("reveal_title_legendary_20261007", "reveal_unlocked_legendary_20261007"),
        )
    ):
        return "continue_puzzle_reward", CN_POST_WIN_REWARD_TAP
    return None
