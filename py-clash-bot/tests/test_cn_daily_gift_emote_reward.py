"""The recorded emote reveal requires both cues and never accepts loading frames."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from pyclashbot.bot.coords import (
    CN_DAILY_GIFT_EMOTE_ICON_ROI,
    CN_DAILY_GIFT_EMOTE_TITLE_ROI,
    CN_POST_WIN_REWARD_TAP,
)
from pyclashbot.detection.cn_daily_gift import (
    DAILY_GIFT_EMOTE_REWARD_ACTION,
    daily_gift_action,
    daily_gift_reward_action,
)

FIXTURES = Path(__file__).with_name("fixtures")


def frame(name):
    source = cv2.imread(str(FIXTURES / name))
    assert source is not None, name
    return source


def reveal():
    return frame("cn_daily_gift/emote_reveal_20261006.png")


def test_real_emote_reveal_returns_only_the_existing_reward_continuation():
    source = reveal()
    assert daily_gift_reward_action(source) == (DAILY_GIFT_EMOTE_REWARD_ACTION, CN_POST_WIN_REWARD_TAP)
    assert daily_gift_action(source) is None


@pytest.mark.parametrize("roi", [CN_DAILY_GIFT_EMOTE_TITLE_ROI, CN_DAILY_GIFT_EMOTE_ICON_ROI])
def test_either_missing_independent_reveal_cue_rejects_the_action(roi):
    source = reveal()
    x1, y1, x2, y2 = roi
    source[y1:y2, x1:x2] = 0
    assert daily_gift_reward_action(source) is None


@pytest.mark.parametrize("roi", [CN_DAILY_GIFT_EMOTE_TITLE_ROI, CN_DAILY_GIFT_EMOTE_ICON_ROI])
def test_one_real_cue_on_an_otherwise_unknown_frame_is_insufficient(roi):
    reference = reveal()
    source = np.zeros_like(reference)
    x1, y1, x2, y2 = roi
    source[y1:y2, x1:x2] = reference[y1:y2, x1:x2]
    assert daily_gift_reward_action(source) is None


@pytest.mark.parametrize("factor", [0.0, 0.35, 0.8, 0.9, 0.94])
def test_dimmed_emote_background_cannot_authorize_continuation(factor):
    assert daily_gift_reward_action((reveal() * factor).astype(np.uint8)) is None


def test_small_normal_render_noise_preserves_the_recorded_reveal():
    source = reveal()
    noise = np.random.default_rng(20261006).normal(0, 3, source.shape)
    noisy = np.clip(source.astype(float) + noise, 0, 255).astype(np.uint8)
    assert daily_gift_reward_action(noisy) == (DAILY_GIFT_EMOTE_REWARD_ACTION, CN_POST_WIN_REWARD_TAP)


@pytest.mark.parametrize(
    "name",
    [
        "cn_daily_gift/loading_after_relaunch_20261006.png",
        "cn_daily_gift/black_daily_timeout_20261006.png",
        "cn_daily_gift/daily_gift_choice_20261004.png",
        "cn_pages/purple_cards_news.png",
        "cn_pages/daily_gift_info.png",
        "cn_pages/classic_glow_verified_lobby.png",
        "cn_rewards/purple_reveal.png",
        "cn_rewards/four_star_chest.png",
        "cn_random_mastery/mastery_reward_coin.png",
        "cn_random_hand/live_hand_0.png",
        "cn_results/win_two_zero.png",
        "cn_shop_daily/live-gem-confirm.png",
        "cn_shop_daily/live-gold-confirm.png",
    ],
)
def test_loading_choice_paid_modal_and_other_rewards_have_no_emote_action(name):
    assert daily_gift_reward_action(frame(name)) is None


@pytest.mark.parametrize("source", [None, np.zeros((632, 419, 3), np.uint8), np.zeros((633, 419, 3), float)])
def test_invalid_captures_have_no_emote_action(source):
    assert daily_gift_reward_action(source) is None
