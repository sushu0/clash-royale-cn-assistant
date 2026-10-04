"""Return actions for observed Chinese-client pages at the fixed BGR resolution.

The saved manifest and small reference crops are the bot's persistent page
memory. Every action needs independent crops of the recorded size and detail,
with calibrated brightness and color. Specific dialogs precede broader page
families; frames without a calibrated signature receive no navigation input.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache

import cv2
import numpy as np

from pyclashbot.bot.coords import CN_PAGE_KEYEVENTS, CN_PAGE_RETURN_COORDS, CN_PAGE_ROIS
from pyclashbot.utils.runtime_config import resource_path

TEMPLATE_ROOT = resource_path("pyclashbot/detection/reference_images/cn_pages")


@dataclass(frozen=True)
class NavigationStep:
    page: str
    route: str
    target: tuple[int, int] | None
    scores: tuple[float, ...]
    idle_only: bool = False
    unowned_only: bool = False


@cache
def learned_pages() -> tuple[dict, ...]:
    path = TEMPLATE_ROOT / "manifest.json"
    if not path.is_file():
        return ()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("resolution") != [419, 633]:
        raise ValueError("Observed navigation pages require the calibrated 419x633 resolution")
    pages = manifest.get("pages", [])
    for page in pages:
        if len(page["cues"]) < 2 or page["route"] not in CN_PAGE_RETURN_COORDS.keys() | CN_PAGE_KEYEVENTS.keys():
            raise ValueError("Every learned page needs two cues and a named return route")
        if "target_cue" in page and not 0 <= page["target_cue"] < len(page["cues"]):
            raise ValueError("The return control must be one of the matched cues")
        if page["route"] in {*CN_PAGE_KEYEVENTS, "spectate_confirm"} and not page.get("idle_only"):
            raise ValueError("Spectator exit routes require an idle checkpoint guard")
        if page["route"] == "deck_confirm_cancel" and not page.get("unowned_only"):
            raise ValueError("Deck confirmation cancellation requires an unowned context")
        cue_regions = set()
        for cue in page["cues"]:
            if cue["roi"] not in CN_PAGE_ROIS or cue.get("search_roi", cue["roi"]) not in CN_PAGE_ROIS:
                raise ValueError(f"Unknown navigation crop: {cue['roi']}")
            cue_regions.add(CN_PAGE_ROIS[cue["roi"]])
        if len(cue_regions) < 2:
            raise ValueError("Navigation requires independent screen regions")
    return tuple(pages)


@cache
def _template(name: str) -> np.ndarray | None:
    # Manifest template names are filenames, never caller-provided paths.
    if not name.replace("_", "").replace("-", "").isalnum():
        raise ValueError("Invalid navigation template name")
    return cv2.imread(str(TEMPLATE_ROOT / f"{name}.png"))


def _match_cue(frame: np.ndarray, cue: dict) -> tuple[float, tuple[int, int]] | None:
    target = _template(cue["template"])
    if target is None:
        return None
    tx1, ty1, tx2, ty2 = CN_PAGE_ROIS[cue["roi"]]
    if target.shape != (ty2 - ty1, tx2 - tx1, 3) or target.dtype != np.uint8:
        return None
    x1, y1, x2, y2 = CN_PAGE_ROIS[cue.get("search_roi", cue["roi"])]
    region = frame[y1:y2, x1:x2]
    if region.shape[0] < target.shape[0] or region.shape[1] < target.shape[1]:
        return None
    if float(np.std(cv2.cvtColor(target, cv2.COLOR_BGR2GRAY))) < cue.get("minimum_std", 8):
        return None
    edge_match = cue.get("match") in ("edges", "glyph_outline")
    if edge_match:
        if cue.get("match") == "glyph_outline":
            # A dark glyph outline is stable while the level fill cycles through
            # green, pink and yellow. This option is restricted to tiny labels.
            reference = (np.max(target, axis=2) < 55).astype(np.uint8) * 255
            search = (np.max(region, axis=2) < 55).astype(np.uint8) * 255
        else:
            reference = cv2.Canny(cv2.cvtColor(target, cv2.COLOR_BGR2GRAY), 40, 100)
            search = cv2.Canny(cv2.cvtColor(region, cv2.COLOR_BGR2GRAY), 40, 100)
        if np.count_nonzero(reference) < 12 or float(np.std(reference)) < 8:
            return None
        scores = cv2.matchTemplate(search, reference, cv2.TM_CCOEFF_NORMED)
    else:
        scores = cv2.matchTemplate(region, target, cv2.TM_CCOEFF_NORMED)
    _, score, _, (x, y) = cv2.minMaxLoc(scores)
    patch = region[y : y + target.shape[0], x : x + target.shape[1]]
    if edge_match:
        # Only a changing-color label can opt into shape matching. Its separate
        # close-button cue still enforces the normal brightness/color checks.
        return (
            (float(score), (x1 + x + target.shape[1] // 2, y1 + y + target.shape[0] // 2))
            if score >= cue.get("min_score", 0.95)
            else None
        )
    # Correlation alone accepts darkened backgrounds behind modal dialogs.
    target_luma = float(np.mean(cv2.cvtColor(target, cv2.COLOR_BGR2GRAY)))
    patch_luma = float(np.mean(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)))
    if patch_luma < target_luma * cue.get("min_brightness_ratio", 0.95):
        return None
    difference = float(np.mean(np.abs(patch.astype(np.float32) - target.astype(np.float32))))
    if difference > cue.get("max_difference", 16):
        return None
    if score < cue.get("min_score", 0.95):
        return None
    center = (x1 + x + target.shape[1] // 2, y1 + y + target.shape[0] // 2)
    return float(score), center


def _page_step(frame, page):
    if page["route"] in ("exit_game_cancel", "deck_confirm_cancel") and "target_cue" in page:
        # These routes authorize Cancel only. A reordered manifest must never
        # turn the matched confirmation button into the action target.
        if page["cues"][page["target_cue"]]["roi"] != "game_exit_cancel":
            return None
    matches = tuple(_match_cue(frame, cue) for cue in page["cues"])
    if not all(match is not None for match in matches):
        return None
    route = page["route"]
    verified = tuple(match for match in matches if match is not None)
    target = CN_PAGE_RETURN_COORDS.get(route)
    if "target_cue" in page:
        target = verified[page["target_cue"]][1]
    return NavigationStep(
        page["name"],
        route,
        target,
        tuple(match[0] for match in verified),
        page.get("idle_only", False),
        page.get("unowned_only", False),
    )


def _valid_frame(frame):
    return isinstance(frame, np.ndarray) and frame.shape == (633, 419, 3) and frame.dtype == np.uint8


def cn_navigation_step(frame: np.ndarray | None) -> NavigationStep | None:
    """Recognize a recorded page and return one verified escape tap, or None."""
    if not _valid_frame(frame):
        return None
    for page in learned_pages():
        step = _page_step(frame, page)
        if step is not None:
            return step
    return None


def cn_game_exit_cancel(frame: np.ndarray | None) -> NavigationStep | None:
    """Only the exact game-exit question authorizes Cancel, including in battle."""
    if not _valid_frame(frame):
        return None
    for page in learned_pages():
        if page["route"] == "exit_game_cancel":
            step = _page_step(frame, page)
            if step is not None:
                return step
    return None


def recognize_cn_page(frame: np.ndarray | None) -> str | None:
    step = cn_navigation_step(frame)
    return step.page if step is not None else None


@cache
def _classic_mode_config() -> dict | None:
    path = TEMPLATE_ROOT / "classic_mode.json"
    if not path.is_file():
        return None
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("resolution") != [419, 633]:
        return None
    for key in ("label", "shield", "top_marker"):
        cue = config.get(key, {})
        if cue.get("roi") not in CN_PAGE_ROIS or cue.get("search_roi") not in CN_PAGE_ROIS:
            return None
    return config


def classic_mode_calibrated() -> bool:
    config = _classic_mode_config()
    if config is None:
        return False
    for key in ("label", "shield", "top_marker"):
        cue = config[key]
        template = _template(cue["template"])
        x1, y1, x2, y2 = CN_PAGE_ROIS[cue["roi"]]
        if template is None or template.shape != (y2 - y1, x2 - x1, 3):
            return False
    return True


def cn_classic_mode_point(frame: np.ndarray | None) -> tuple[int, int] | None:
    """Locate the recorded Classic 1v1 label and its shield on the same row."""
    if not isinstance(frame, np.ndarray):
        return None
    config = _classic_mode_config()
    if config is None or recognize_cn_page(frame) != "game_modes":
        return None
    label, shield = (_match_cue(frame, config[key]) for key in ("label", "shield"))
    if label is None or shield is None:
        return None
    if abs(label[1][1] - shield[1][1]) > 50 or shield[1][0] - label[1][0] < 100:
        return None
    return shield[1]


def cn_mode_menu_at_top(frame: np.ndarray | None) -> bool:
    if not isinstance(frame, np.ndarray):
        return False
    config = _classic_mode_config()
    return bool(
        config is not None
        and recognize_cn_page(frame) == "game_modes"
        and _match_cue(frame, config["top_marker"]) is not None
    )
