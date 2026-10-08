"""A menu-verified Classic icon tolerates external glow without mode guessing."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from pyclashbot.bot.cn_1v1_loop import ChineseVision
from pyclashbot.bot.coords import CN_CLASSIC_MODE_CORE_ROIS

FIXTURES = Path(__file__).with_name("fixtures")
CLASSIC = (
    "cn_567/classic1v1_lobby.png",
    "cn_pages/classic_restored_lobby.png",
    "cn_pages/final_classic_lobby.png",
    "cn_pages/classic_glow_verified_lobby.png",
)


def frame(name):
    source = cv2.imread(str(FIXTURES / name))
    assert source is not None, name
    return source


@pytest.fixture(scope="module")
def vision():
    return ChineseVision()


@pytest.mark.parametrize("name", CLASSIC)
def test_legacy_and_actual_menu_verified_classic_icons_remain_confirmed(name, vision):
    assert vision.classic_selected(frame(name))


@pytest.mark.parametrize("name", CLASSIC)
@pytest.mark.parametrize("factor", [0.0, 0.35, 0.8, 0.9, 0.94])
def test_classic_icon_dimmed_under_a_modal_is_not_confirmed(name, factor, vision):
    source = frame(name)
    assert not vision.classic_selected((source * factor).astype(np.uint8))


@pytest.mark.parametrize("name", [CLASSIC[0], CLASSIC[-1]])
@pytest.mark.parametrize("missing_core", [0, 1])
def test_each_nonoverlapping_icon_core_is_required(name, missing_core, vision):
    source = frame(name)
    x1, y1, x2, y2 = CN_CLASSIC_MODE_CORE_ROIS[missing_core]
    source[y1:y2, x1:x2] = 0
    assert not vision.classic_selected(source)


@pytest.mark.parametrize("wrong_core", [0, 1])
def test_a_single_classic_core_cannot_authorize_a_two_v_two_icon(wrong_core, vision):
    source = frame(CLASSIC[-1])
    foreign = frame("cn_567/classic2v2_lobby.png")
    x1, y1, x2, y2 = CN_CLASSIC_MODE_CORE_ROIS[wrong_core]
    source[y1:y2, x1:x2] = foreign[y1:y2, x1:x2]
    assert not vision.classic_selected(source)


@pytest.mark.parametrize(
    "name",
    [
        "cn_567/classic2v2_lobby.png",
        "cn_pages/classic_2v2_lobby.png",
        "cn_pages/game_modes_top.png",
        "cn_pages/game_modes_blue_top.png",
        "cn_pages/game_modes_classic_visible.png",
        "cn_pages/collection_tab_20261005.png",
        "cn_pages/settings.png",
        "cn_pages/friends_lobby_cues_only.png",
        "cn_random_hand/live_hand_0.png",
        "cn_results/win_two_zero.png",
    ],
)
def test_other_modes_and_foreign_pages_are_not_classic_lobbies(name, vision):
    assert not vision.classic_selected(frame(name))


@pytest.mark.parametrize("source", [None, np.zeros((632, 419, 3), np.uint8), np.zeros((633, 419, 3), float)])
def test_invalid_captures_cannot_authorize_classic(source, vision):
    assert not vision.classic_selected(source)
