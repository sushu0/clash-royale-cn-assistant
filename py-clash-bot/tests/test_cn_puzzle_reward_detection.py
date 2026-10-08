"""Recorded entry phases and unlocked puzzle cues reject unrelated reward pages."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from pyclashbot.bot.coords import CN_POST_WIN_REWARD_TAP, CN_PUZZLE_REWARD_SEARCH_ROIS
from pyclashbot.detection.cn_puzzle_reward import puzzle_reward_action

FIXTURES = Path(__file__).with_name("fixtures")
POSITIVES = (
    ("puzzle_open_20261007.png", "open_puzzle_reward"),
    ("puzzle_open_phase2_20261007.png", "open_puzzle_reward"),
    ("puzzle_open_small_caption_20261007.png", "open_puzzle_reward"),
    ("puzzle_reveal_20261007.png", "continue_puzzle_reward"),
)


def frame(name):
    source = cv2.imread(str(FIXTURES / name))
    assert source is not None, name
    return source


@pytest.mark.parametrize(("name", "action"), POSITIVES)
def test_both_real_entry_phases_and_the_recovery_reveal_are_detected(name, action):
    assert puzzle_reward_action(frame(f"cn_puzzle_reward/{name}")) == (action, CN_POST_WIN_REWARD_TAP)


@pytest.mark.parametrize(("name", "action"), POSITIVES)
@pytest.mark.parametrize("factor", [0.0, 0.35, 0.8, 0.9, 0.94])
def test_dimmed_reward_under_an_unknown_overlay_has_no_action(name, action, factor):
    del action
    assert puzzle_reward_action((frame(f"cn_puzzle_reward/{name}") * factor).astype(np.uint8)) is None


@pytest.mark.parametrize(
    ("name", "cue"),
    [
        ("puzzle_open_20261007.png", "entry_question"),
        ("puzzle_open_20261007.png", "entry_open_label"),
        ("puzzle_open_phase2_20261007.png", "entry_question"),
        ("puzzle_open_phase2_20261007.png", "entry_open_label"),
        ("puzzle_open_small_caption_20261007.png", "entry_question"),
        ("puzzle_open_small_caption_20261007.png", "entry_open_label"),
        ("puzzle_reveal_20261007.png", "reveal_title"),
        ("puzzle_reveal_20261007.png", "reveal_unlocked"),
    ],
)
def test_each_independent_cue_is_required(name, cue):
    source = frame(f"cn_puzzle_reward/{name}")
    x1, y1, x2, y2 = CN_PUZZLE_REWARD_SEARCH_ROIS[cue]
    source[y1:y2, x1:x2] = 0
    assert puzzle_reward_action(source) is None


def test_reveal_does_not_bind_the_changing_fragment_art_or_counter():
    source = frame("cn_puzzle_reward/puzzle_reveal_20261007.png")
    source[250:380, 145:280] = 0
    source[420:455, 160:287] = 0
    assert puzzle_reward_action(source) == ("continue_puzzle_reward", CN_POST_WIN_REWARD_TAP)


@pytest.mark.parametrize("name", ["puzzle_open_20261007.png", "puzzle_reveal_20261007.png"])
def test_cues_moved_outside_the_bounded_search_regions_are_rejected(name):
    source = frame(f"cn_puzzle_reward/{name}")
    shifted = cv2.warpAffine(source, np.array([[1, 0, 0], [0, 1, 35]], np.float32), (419, 633))
    assert puzzle_reward_action(shifted) is None


@pytest.mark.parametrize(
    "name",
    [
        "cn_daily_gift/loading_after_relaunch_20261006.png",
        "cn_daily_gift/black_daily_timeout_20261006.png",
        "cn_daily_gift/emote_reveal_20261006.png",
        "cn_daily_gift/daily_gift_choice_20261004.png",
        "cn_pages/classic_glow_verified_lobby.png",
        "cn_pages/king_skin_promotion_20261006.png",
        "cn_shop_daily/live-gem-confirm.png",
        "cn_shop_daily/live-gold-confirm.png",
        "cn_shop_daily/live-gold-wide-confirm.png",
        "cn_shop_daily/live-free-open.png",
        "cn_shop_daily/live-free-reward-1.png",
        "cn_rewards/four_star_chest.png",
        "cn_rewards/four_star_card.png",
        "cn_random_mastery/mastery_reward_coin.png",
        "cn_random_hand/live_hand_0.png",
        "cn_results/win_two_zero.png",
    ],
)
def test_payment_loading_other_rewards_and_other_pages_have_no_puzzle_action(name):
    assert puzzle_reward_action(frame(name)) is None


@pytest.mark.parametrize("source", [None, np.zeros((632, 419, 3), np.uint8), np.zeros((633, 419, 3), float)])
def test_invalid_frames_are_rejected(source):
    assert puzzle_reward_action(source) is None


def test_independent_actual_entry_series_has_recognizable_frames_beyond_the_calibration_source():
    sources = sorted((FIXTURES / "cn_puzzle_reward/entry_series_20261007").glob("*.png"))
    assert len(sources) == 12
    recognized = [puzzle_reward_action(cv2.imread(str(path))) for path in sources]
    assert recognized[0] == ("open_puzzle_reward", CN_POST_WIN_REWARD_TAP)
    assert sum(action is not None for action in recognized[1:]) >= 1
