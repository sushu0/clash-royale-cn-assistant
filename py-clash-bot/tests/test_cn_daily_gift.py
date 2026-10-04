"""Daily choice regressions use the actual 08:00 unknown-screen report."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from pyclashbot.bot.coords import (
    CN_DAILY_GIFT_COSMETIC_CHOICE,
    CN_DAILY_GIFT_COSMETIC_LABEL_ROI,
    CN_DAILY_GIFT_COSMETIC_PANEL_ROI,
    CN_DAILY_GIFT_LUCK_LABEL_ROI,
    CN_DAILY_GIFT_RICH_LABEL_ROI,
    CN_DAILY_GIFT_TITLE_ROI,
)
from pyclashbot.detection.cn_daily_gift import DAILY_GIFT_COSMETIC_ACTION, daily_gift_action

FIXTURE = Path(__file__).with_name("fixtures") / "cn_daily_gift" / "daily_gift_choice_20261004.png"
UNRELATED_FIXTURES = (
    "cn_random_mastery/deck.png",
    "cn_random_mastery/deck_menu.png",
    "cn_random_mastery/collection.png",
    "cn_random_mastery/mastery_reward_coin.png",
    "cn_random_mastery/late_post_battle_reward.png",
    "cn_rewards/purple_reveal.png",
    "cn_rewards/four_star_chest.png",
)


def _gift_frame():
    frame = cv2.imread(str(FIXTURE))
    assert frame is not None
    return frame


def test_observed_daily_choice_returns_authorized_cosmetic_action():
    assert daily_gift_action(_gift_frame()) == (DAILY_GIFT_COSMETIC_ACTION, CN_DAILY_GIFT_COSMETIC_CHOICE)


def test_following_day_counter_and_reward_artwork_can_change():
    frame = _gift_frame()
    frame[15:38, 150:275] = 0
    frame[395:448, 150:265] = 0
    assert daily_gift_action(frame) == (DAILY_GIFT_COSMETIC_ACTION, CN_DAILY_GIFT_COSMETIC_CHOICE)


@pytest.mark.parametrize(
    "roi",
    [
        CN_DAILY_GIFT_TITLE_ROI,
        CN_DAILY_GIFT_RICH_LABEL_ROI,
        CN_DAILY_GIFT_LUCK_LABEL_ROI,
        CN_DAILY_GIFT_COSMETIC_LABEL_ROI,
    ],
)
def test_missing_title_or_choice_label_cannot_trigger_a_click(roi):
    frame = _gift_frame()
    x1, y1, x2, y2 = roi
    frame[y1:y2, x1:x2] = 0
    assert daily_gift_action(frame) is None


def test_labels_in_different_rows_are_not_treated_as_the_known_choice():
    frame = _gift_frame()
    cosmetic = frame[450:472, 165:251].copy()
    luck = frame[317:337, 164:254].copy()
    x1, y1, x2, y2 = CN_DAILY_GIFT_COSMETIC_LABEL_ROI
    frame[y1:y2, x1:x2] = 0
    frame[450:470, 165:255] = luck
    frame[317:339, 164:250] = cosmetic
    assert daily_gift_action(frame) is None


def test_grayscale_template_match_requires_purple_choice_panel():
    frame = _gift_frame()
    x1, y1, x2, y2 = CN_DAILY_GIFT_COSMETIC_PANEL_ROI
    gray = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    frame[y1:y2, x1:x2] = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    assert daily_gift_action(frame) is None


def test_unrelated_pages_and_wrong_resolution_return_no_action():
    assert daily_gift_action(np.zeros((633, 419, 3), dtype=np.uint8)) is None
    assert daily_gift_action(np.zeros((632, 419, 3), dtype=np.uint8)) is None
    assert daily_gift_action(_gift_frame().astype(np.float32)) is None
    assert daily_gift_action(None) is None


def test_small_render_noise_preserves_observed_choice():
    frame = _gift_frame()
    noise = np.random.default_rng(20261004).normal(0, 3, frame.shape)
    noisy = np.clip(frame.astype(float) + noise, 0, 255).astype(np.uint8)
    assert daily_gift_action(noisy) == (DAILY_GIFT_COSMETIC_ACTION, CN_DAILY_GIFT_COSMETIC_CHOICE)


@pytest.mark.parametrize("name", UNRELATED_FIXTURES)
def test_existing_deck_and_reward_screens_do_not_choose_cosmetics(name):
    frame = cv2.imread(str(Path(__file__).with_name("fixtures") / name))
    assert frame is not None
    assert daily_gift_action(frame) is None
