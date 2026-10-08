"""The real legendary reveal retains independent paired title/unlocked cues."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from pyclashbot.bot.coords import CN_POST_WIN_REWARD_TAP, CN_PUZZLE_REWARD_SEARCH_ROIS
from pyclashbot.detection import cn_puzzle_reward as module
from pyclashbot.detection.cn_puzzle_reward import puzzle_reward_action

FIXTURES = Path(__file__).with_name("fixtures")
POSITIVE = (
    "puzzle_reveal_legendary_20261007.png",
    "puzzle_reveal_legendary_before_relaunch_20261007.png",
    "puzzle_reveal_legendary_current_20261007.png",
)


def frame(name):
    source = cv2.imread(str(FIXTURES / name))
    assert source is not None, name
    return source


@pytest.mark.parametrize("name", POSITIVE)
def test_two_real_legendary_frames_authorize_only_existing_continuation(name):
    assert puzzle_reward_action(frame(f"cn_puzzle_reward/{name}")) == ("continue_puzzle_reward", CN_POST_WIN_REWARD_TAP)


@pytest.mark.parametrize("name", POSITIVE)
@pytest.mark.parametrize("factor", [0.0, 0.35, 0.8, 0.9, 0.94])
def test_dimmed_legendary_reveal_has_no_action(name, factor):
    assert puzzle_reward_action((frame(f"cn_puzzle_reward/{name}") * factor).astype(np.uint8)) is None


@pytest.mark.parametrize("cue", ["reveal_title", "reveal_unlocked"])
def test_either_missing_independent_legendary_cue_rejects_the_action(cue):
    source = frame(f"cn_puzzle_reward/{POSITIVE[0]}")
    x1, y1, x2, y2 = CN_PUZZLE_REWARD_SEARCH_ROIS[cue]
    source[y1:y2, x1:x2] = 0
    assert puzzle_reward_action(source) is None


@pytest.mark.parametrize(
    "available",
    [
        {"reveal_title_20261007", "reveal_unlocked_legendary_20261007"},
        {"reveal_title_legendary_20261007", "reveal_unlocked_20261007"},
    ],
)
def test_cross_variant_cues_cannot_be_combined(available, monkeypatch):
    monkeypatch.setattr(module, "_matches", lambda _frame, _cue, name: name in available)
    assert puzzle_reward_action(frame(f"cn_puzzle_reward/{POSITIVE[0]}")) is None


@pytest.mark.parametrize(
    "name",
    [
        "cn_puzzle_reward/puzzle_open_20261007.png",
        "cn_puzzle_reward/puzzle_open_phase2_20261007.png",
        "cn_puzzle_reward/puzzle_open_small_caption_20261007.png",
    ],
)
def test_recorded_entry_phases_keep_the_open_action(name):
    assert puzzle_reward_action(frame(name)) == ("open_puzzle_reward", CN_POST_WIN_REWARD_TAP)


@pytest.mark.parametrize(
    "name",
    [
        "cn_daily_gift/loading_after_relaunch_20261006.png",
        "cn_daily_gift/black_daily_timeout_20261006.png",
        "cn_daily_gift/emote_reveal_20261006.png",
        "cn_shop_daily/live-gem-confirm.png",
        "cn_shop_daily/live-gold-confirm.png",
        "cn_shop_daily/live-free-open.png",
        "cn_pages/global_challenge_promotion_20261007.png",
        "cn_random_hand/live_hand_0.png",
    ],
)
def test_real_payment_loading_other_reward_and_promotion_frames_remain_rejected(name):
    assert puzzle_reward_action(frame(name)) is None
