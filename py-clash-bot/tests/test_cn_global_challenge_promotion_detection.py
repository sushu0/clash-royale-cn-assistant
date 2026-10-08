"""The recorded global challenge page authorizes only the visible red X."""

from copy import deepcopy
from pathlib import Path

import cv2
import numpy as np
import pytest

from pyclashbot.bot.coords import CN_PAGE_GLOBAL_CHALLENGE_PROMOTION_CLOSE, CN_PAGE_ROIS
from pyclashbot.detection import cn_page_navigation as module
from pyclashbot.detection.cn_page_navigation import cn_global_challenge_promotion_close

FIXTURES = Path(__file__).with_name("fixtures")
CUES = (
    "global_challenge_promotion_title",
    "global_challenge_promotion_subtitle",
    "global_challenge_promotion_close",
)


def frame(name="cn_pages/global_challenge_promotion_20261007.png"):
    source = cv2.imread(str(FIXTURES / name))
    assert source is not None, name
    return source


def test_real_advertisement_has_three_independent_cues_and_only_the_red_close_target():
    step = cn_global_challenge_promotion_close(frame())
    assert step is not None and step.page == "global_challenge_promotion"
    assert step.route == "global_challenge_promotion_close" and len(step.scores) == 3
    assert step.target == CN_PAGE_GLOBAL_CHALLENGE_PROMOTION_CLOSE


@pytest.mark.parametrize("factor", [0.0, 0.35, 0.8, 0.9, 0.94])
def test_dimmed_advertisement_cannot_authorize_close(factor):
    assert cn_global_challenge_promotion_close((frame() * factor).astype(np.uint8)) is None


@pytest.mark.parametrize("roi", CUES)
def test_each_independent_advertisement_cue_is_required(roi):
    source = frame()
    x1, y1, x2, y2 = CN_PAGE_ROIS[roi]
    source[y1:y2, x1:x2] = 0
    assert cn_global_challenge_promotion_close(source) is None


@pytest.mark.parametrize("target", [0, 1])
def test_reordered_or_redirected_manifest_cannot_target_other_controls(target, monkeypatch):
    page = deepcopy(next(p for p in module.learned_pages() if p["name"] == "global_challenge_promotion"))
    page["target_cue"] = target
    monkeypatch.setattr(module, "learned_pages", lambda: (page,))
    assert cn_global_challenge_promotion_close(frame()) is None


def test_unregistered_roi_order_never_reaches_the_matcher(monkeypatch):
    page = deepcopy(next(p for p in module.learned_pages() if p["name"] == "global_challenge_promotion"))
    page["cues"][0], page["cues"][1] = page["cues"][1], page["cues"][0]
    monkeypatch.setattr(module, "learned_pages", lambda: (page,))
    monkeypatch.setattr(module, "_page_step", lambda *_: pytest.fail("Do not evaluate a redirected signature"))
    assert cn_global_challenge_promotion_close(frame()) is None


@pytest.mark.parametrize(
    "name",
    [
        "cn_puzzle_reward/puzzle_open_20261007.png",
        "cn_puzzle_reward/puzzle_reveal_20261007.png",
        "cn_pages/king_skin_promotion_20261006.png",
        "cn_pages/classic_glow_verified_lobby.png",
        "cn_shop_daily/live-gem-confirm.png",
        "cn_shop_daily/live-gold-confirm.png",
        "cn_shop_daily/live-free-open.png",
        "cn_daily_gift/emote_reveal_20261006.png",
        "cn_daily_gift/loading_after_relaunch_20261006.png",
        "cn_daily_gift/black_daily_timeout_20261006.png",
        "cn_random_hand/live_hand_0.png",
        "cn_results/win_two_zero.png",
    ],
)
def test_payment_other_promotion_reward_battle_and_unknown_frames_have_no_advertisement_action(name):
    assert cn_global_challenge_promotion_close(frame(name)) is None


@pytest.mark.parametrize("source", [None, np.zeros((632, 419, 3), np.uint8), np.zeros((633, 419, 3), float)])
def test_invalid_capture_is_rejected(source):
    assert cn_global_challenge_promotion_close(source) is None
