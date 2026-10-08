"""Battle availability requires bright button structure and its observed fill."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from pyclashbot.bot.cn_1v1_loop import ChineseVision
from pyclashbot.bot.coords import CN_LOBBY_START_BORDER_ROI, CN_LOBBY_START_FILL_ROIS

FIXTURES = Path(__file__).with_name("fixtures")
READY = (
    "cn_lobby_availability/ready_live.png",
    "cn_567/classic1v1_lobby.png",
    "cn_567/classic2v2_lobby.png",
    "cn_pages/classic_2v2_lobby.png",
    "cn_pages/classic_restored_lobby.png",
    "cn_pages/final_classic_lobby.png",
)
DISABLED = (
    "cn_lobby_availability/disabled_error_report.png",
    "cn_lobby_availability/disabled_before_match.png",
)


def frame(name):
    source = cv2.imread(str(FIXTURES / name))
    assert source is not None, name
    return source


@pytest.fixture(scope="module")
def vision():
    return ChineseVision()


@pytest.mark.parametrize("name", READY)
def test_real_yellow_buttons_are_available_without_changing_lobby_classification(name, vision):
    source = frame(name)
    assert vision.classify(source)[0] == "lobby"
    assert vision.lobby_start_state(source) == "ready"


@pytest.mark.parametrize("name", DISABLED)
def test_real_gray_completed_buttons_remain_lobbies_without_authorizing_battle(name, vision):
    source = frame(name)
    assert vision.classify(source)[0] == "lobby"
    assert vision.lobby_start_state(source) == "disabled"


@pytest.mark.parametrize("name", [READY[0], READY[-1], *DISABLED])
@pytest.mark.parametrize("factor", [0.0, 0.35, 0.8, 0.9, 0.94])
def test_dark_or_dimmed_lobby_buttons_do_not_authorize_ready_or_disabled(name, factor, vision):
    source = frame(name)
    assert vision.lobby_start_state((source * factor).astype(np.uint8)) == "unknown"


@pytest.mark.parametrize("name", [READY[0], DISABLED[0]])
def test_text_and_fill_without_the_independent_button_border_are_unknown(name, vision):
    source = frame(name)
    x1, y1, x2, y2 = CN_LOBBY_START_BORDER_ROI
    source[y1:y2, x1:x2] = 0
    assert vision.lobby_start_state(source) == "unknown"


@pytest.mark.parametrize("name", [READY[0], DISABLED[0]])
def test_button_border_and_label_without_confirmed_fill_are_unknown(name, vision):
    source = frame(name)
    for x1, y1, x2, y2 in CN_LOBBY_START_FILL_ROIS:
        source[y1:y2, x1:x2] = (100, 60, 100)
    assert vision.lobby_start_state(source) == "unknown"


@pytest.mark.parametrize("name", READY)
def test_desaturated_yellow_buttons_are_not_the_recorded_disabled_state(name, vision):
    source = frame(name)
    desaturated = cv2.cvtColor(cv2.cvtColor(source, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    assert vision.lobby_start_state(desaturated) == "unknown"


@pytest.mark.parametrize(
    "name",
    [
        "cn_pages/game_modes_blue_top.png",
        "cn_pages/game_modes_top.png",
        "cn_pages/settings.png",
        "cn_pages/friends_lobby_cues_only.png",
        "cn_random_mastery/mastery_locked.png",
        "cn_random_mastery/late_post_battle_reward.png",
        "cn_random_hand/live_hand_0.png",
        "cn_results/win_two_zero.png",
    ],
)
def test_foreign_navigation_reward_battle_and_result_pages_are_unknown(name, vision):
    assert vision.lobby_start_state(frame(name)) == "unknown"


@pytest.mark.parametrize("source", [None, np.zeros((632, 419, 3), np.uint8), np.zeros((633, 419, 3), float)])
def test_invalid_frames_are_unknown_without_classification(source, vision):
    assert vision.lobby_start_state(source) == "unknown"
