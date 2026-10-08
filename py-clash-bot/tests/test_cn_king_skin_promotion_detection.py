"""This recorded skin promotion authorizes only its independently verified red X."""

from copy import deepcopy
from pathlib import Path

import cv2
import numpy as np
import pytest

from pyclashbot.bot.coords import CN_PAGE_KING_SKIN_PROMOTION_CLOSE, CN_PAGE_ROIS
from pyclashbot.detection import cn_page_navigation as page_module
from pyclashbot.detection.cn_page_navigation import NavigationStep, cn_king_skin_promotion_close, cn_navigation_step

FIXTURES = Path(__file__).with_name("fixtures")
POSITIVES = (
    "king_skin_promotion_20261006.png",
    "king_skin_promotion_before_relaunch_20261006.png",
    "king_skin_promotion_current_20261006.png",
)
CUES = ("king_skin_promotion_title", "king_skin_promotion_role", "king_skin_promotion_close")


def frame(name):
    source = cv2.imread(str(FIXTURES / name))
    assert source is not None, name
    return source


def promotion(name=POSITIVES[0]):
    return frame(f"cn_pages/{name}")


@pytest.mark.parametrize("name", POSITIVES)
def test_three_independent_real_captures_authorize_only_the_visible_red_x(name):
    source = promotion(name)
    step = cn_king_skin_promotion_close(source)
    assert step is not None and step.page == "king_skin_promotion" and step.route == "king_skin_promotion_close"
    assert step.target == CN_PAGE_KING_SKIN_PROMOTION_CLOSE and len(step.scores) == 3
    assert min(step.scores) >= 0.95
    assert cn_navigation_step(source) == step


@pytest.mark.parametrize("name", POSITIVES)
@pytest.mark.parametrize("factor", [0.0, 0.35, 0.8, 0.9, 0.94])
def test_dark_or_dimmed_promotion_never_authorizes_close(name, factor):
    assert cn_king_skin_promotion_close((promotion(name) * factor).astype(np.uint8)) is None


@pytest.mark.parametrize("roi", CUES)
def test_every_independent_promotion_region_is_required(roi):
    source = promotion()
    x1, y1, x2, y2 = CN_PAGE_ROIS[roi]
    source[y1:y2, x1:x2] = 0
    assert cn_king_skin_promotion_close(source) is None
    assert cn_navigation_step(source) is None


@pytest.mark.parametrize("roi", CUES)
def test_one_matching_promotion_cue_on_an_unknown_frame_is_insufficient(roi):
    reference = promotion()
    source = np.zeros_like(reference)
    x1, y1, x2, y2 = CN_PAGE_ROIS[roi]
    source[y1:y2, x1:x2] = reference[y1:y2, x1:x2]
    assert cn_king_skin_promotion_close(source) is None


def test_specific_detector_does_not_consult_the_general_navigation_scan(monkeypatch):
    monkeypatch.setattr(
        page_module, "cn_navigation_step", lambda _: pytest.fail("Match only this registered promotion")
    )
    step = cn_king_skin_promotion_close(promotion())
    assert step is not None
    assert step.target == CN_PAGE_KING_SKIN_PROMOTION_CLOSE


@pytest.mark.parametrize("target_cue", [0, 1])
def test_manifest_cannot_redirect_close_to_the_title_or_role_label(target_cue, monkeypatch):
    page = deepcopy(next(page for page in page_module.learned_pages() if page["name"] == "king_skin_promotion"))
    page["target_cue"] = target_cue
    monkeypatch.setattr(page_module, "learned_pages", lambda: (page,))
    assert cn_king_skin_promotion_close(promotion()) is None


def test_an_incomplete_two_cue_signature_cannot_authorize_close(monkeypatch):
    page = deepcopy(next(page for page in page_module.learned_pages() if page["name"] == "king_skin_promotion"))
    page["cues"] = [page["cues"][0], page["cues"][2]]
    page["target_cue"] = 1
    monkeypatch.setattr(page_module, "learned_pages", lambda: (page,))
    assert cn_king_skin_promotion_close(promotion()) is None


@pytest.mark.parametrize("malformation", ["reordered", "wrong_last_roi", "wrong_route"])
def test_reordered_or_redirected_manifest_never_reaches_the_matcher(malformation, monkeypatch):
    page = deepcopy(next(page for page in page_module.learned_pages() if page["name"] == "king_skin_promotion"))
    if malformation == "reordered":
        page["cues"][0], page["cues"][1] = page["cues"][1], page["cues"][0]
    elif malformation == "wrong_last_roi":
        page["cues"][2]["roi"] = "page_footer"
    else:
        page["route"] = "shop"
    monkeypatch.setattr(page_module, "learned_pages", lambda: (page,))
    monkeypatch.setattr(page_module, "_page_step", lambda *_: pytest.fail("Do not match a redirected signature"))
    assert cn_king_skin_promotion_close(promotion()) is None


def test_a_matched_target_outside_the_named_close_roi_is_rejected(monkeypatch):
    _, _, right, bottom = CN_PAGE_ROIS["king_skin_promotion_close"]
    redirected = NavigationStep("king_skin_promotion", "king_skin_promotion_close", (right, bottom), (1.0, 1.0, 1.0))
    monkeypatch.setattr(page_module, "_page_step", lambda *_: redirected)
    assert cn_king_skin_promotion_close(promotion()) is None


@pytest.mark.parametrize(
    "name",
    [
        "cn_pages/classic_glow_verified_lobby.png",
        "cn_pages/crl_support_shop_native.png",
        "cn_pages/custom_bundle_choices.png",
        "cn_shop_daily/live-gem-confirm.png",
        "cn_shop_daily/live-gold-confirm.png",
        "cn_shop_daily/live-gold-wide-confirm.png",
        "cn_shop_daily/live-free-open.png",
        "cn_shop_daily/live-free-reward-1.png",
        "cn_daily_gift/emote_reveal_20261006.png",
        "cn_daily_gift/loading_after_relaunch_20261006.png",
        "cn_daily_gift/black_daily_timeout_20261006.png",
        "cn_random_mastery/mastery_reward_coin.png",
        "cn_random_mastery/late_post_battle_reward.png",
        "cn_random_hand/live_hand_0.png",
        "cn_results/win_two_zero.png",
    ],
)
def test_real_payment_reward_lobby_and_other_promotion_frames_cannot_authorize_this_close(name):
    assert cn_king_skin_promotion_close(frame(name)) is None


@pytest.mark.parametrize("source", [None, np.zeros((632, 419, 3), np.uint8), np.zeros((633, 419, 3), float)])
def test_invalid_captures_are_rejected(source):
    assert cn_king_skin_promotion_close(source) is None
