"""Classic 1v1 selection verifies every source screen and its final lobby."""

from itertools import chain, repeat
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from pyclashbot.bot import nav
from pyclashbot.bot.cn_1v1_loop import ChineseVision
from pyclashbot.bot.coords import (
    CN_CLASSIC_MODE_SCROLL_TO_BOTTOM,
    CN_CLASSIC_MODE_SCROLL_TO_TOP,
    CN_CLASSIC_MODE_SELECTOR,
)
from pyclashbot.detection.cn_page_navigation import cn_classic_mode_point, cn_navigation_step

FIXTURES = Path(__file__).with_name("fixtures")


class Logger:
    def change_status(self, status):
        pass

    def log(self, message):
        pass


def frame(name):
    result = cv2.imread(str(FIXTURES / name))
    assert result is not None, name
    return result


def device_for(snapshots):
    snapshots = iter(snapshots)
    device = SimpleNamespace(clicks=[], swipes=[], observations=0)

    def screenshot():
        device.observations += 1
        return next(snapshots)

    device.screenshot = screenshot
    device.click = lambda *point: device.clicks.append(point)
    device.swipe = lambda *points: device.swipes.append(points)
    return device


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(nav.time, "sleep", lambda seconds: None)


def test_confirmed_classic_lobby_needs_no_input_or_mode_calibration():
    device = device_for([frame("cn_567/classic1v1_lobby.png")])
    assert nav.navigate_cn_classic_1v1(device, Logger(), ChineseVision())
    assert device.clicks == [] and device.swipes == []


def test_observed_final_classic_round_trip_is_a_lobby_without_another_return_input():
    source = frame("cn_pages/final_classic_lobby.png")
    vision = ChineseVision()
    assert vision.classify(source)[0] == "lobby" and vision.classic_selected(source)
    assert cn_navigation_step(source) is None
    device = device_for([source])
    assert nav.navigate_cn_classic_1v1(device, Logger(), vision)
    assert device.clicks == [] and device.swipes == []


def test_missing_classic_calibration_does_not_open_selector(monkeypatch):
    monkeypatch.setattr(nav, "classic_mode_calibrated", lambda: False)
    device = device_for([frame("cn_567/classic2v2_lobby.png")])
    assert not nav.navigate_cn_classic_1v1(device, Logger(), ChineseVision())
    assert device.clicks == [] and device.swipes == []


@pytest.mark.parametrize(
    "name",
    [
        "cn_random_hand/live_hand_0.png",
        "cn_results/win_two_zero.png",
        "cn_random_mastery/late_post_battle_reward.png",
        "cn_pages/collection_badges.png",
        "cn_pages/settings.png",
        "cn_pages/spectate.png",
    ],
)
def test_foreign_pages_do_not_authorize_mode_input(name, monkeypatch):
    monkeypatch.setattr(nav, "classic_mode_calibrated", lambda: True)
    device = device_for([frame(name)])
    assert not nav.navigate_cn_classic_1v1(device, Logger(), ChineseVision())
    assert device.clicks == [] and device.swipes == []


def test_missing_row_uses_only_verified_menu_swipes_with_bounded_input_budget(monkeypatch):
    monkeypatch.setattr(nav, "classic_mode_calibrated", lambda: True)
    monkeypatch.setattr(nav, "cn_classic_mode_point", lambda source: None)
    monkeypatch.setattr(nav, "cn_mode_menu_at_top", lambda source: True)
    wrong_lobby = frame("cn_567/classic2v2_lobby.png")
    menu = frame("cn_pages/game_modes_top.png")
    device = device_for(chain([wrong_lobby], repeat(menu)))
    assert not nav.navigate_cn_classic_1v1(device, Logger(), ChineseVision(), max_steps=4)
    assert device.clicks == [CN_CLASSIC_MODE_SELECTOR]
    assert device.swipes == [CN_CLASSIC_MODE_SCROLL_TO_BOTTOM] * 3
    assert device.observations <= 15


def test_unknown_transition_frames_receive_observation_only_after_input(monkeypatch):
    monkeypatch.setattr(nav, "classic_mode_calibrated", lambda: True)
    wrong_lobby = frame("cn_567/classic2v2_lobby.png")
    blank = np.zeros_like(wrong_lobby)
    device = device_for(chain([wrong_lobby], repeat(blank)))
    assert not nav.navigate_cn_classic_1v1(device, Logger(), ChineseVision())
    assert device.clicks == [CN_CLASSIC_MODE_SELECTOR] and device.swipes == []
    assert device.observations == 11


def test_actual_classic_row_is_located_and_only_two_v_two_visible_does_not_match():
    assert cn_classic_mode_point(frame("cn_pages/game_modes_classic_visible.png")) == (319, 449)
    assert cn_classic_mode_point(frame("cn_pages/game_modes_scrolled.png")) is None
    source = frame("cn_pages/game_modes_classic_visible.png")
    source[402:500] = 0
    assert cn_classic_mode_point(source) is None


def test_two_classic_cues_must_belong_to_the_same_menu_row():
    source = frame("cn_pages/game_modes_classic_visible.png")
    shield = source[420:478, 291:348].copy()
    source[420:478, 291:348] = 0
    source[525:583, 291:348] = shield
    assert cn_classic_mode_point(source) is None


def test_restore_waits_for_old_menu_old_wrong_lobby_and_unknown_frames_without_more_input():
    wrong = frame("cn_pages/classic_2v2_lobby.png")
    menu_top = frame("cn_pages/game_modes_top.png")
    classic_row = frame("cn_pages/game_modes_classic_visible.png")
    correct = frame("cn_pages/classic_restored_lobby.png")
    device = device_for(
        [wrong, *([menu_top] * 3), classic_row, classic_row, menu_top, wrong, np.zeros_like(wrong), *([correct] * 3)]
    )
    assert nav.navigate_cn_classic_1v1(device, Logger(), ChineseVision(), verify_menu=True)
    assert device.clicks == [CN_CLASSIC_MODE_SELECTOR, (319, 449)]
    assert device.swipes == [CN_CLASSIC_MODE_SCROLL_TO_BOTTOM]
    assert device.observations == 12


def test_forced_roundtrip_opens_an_already_classic_lobby_and_confirms_destination():
    correct = frame("cn_pages/classic_restored_lobby.png")
    row = frame("cn_pages/game_modes_classic_visible.png")
    device = device_for([correct, *([row] * 3), *([correct] * 3)])
    assert nav.navigate_cn_classic_1v1(device, Logger(), ChineseVision(), verify_menu=True)
    assert device.clicks == [CN_CLASSIC_MODE_SELECTOR, (319, 449)] and device.swipes == []


def test_stale_classic_base_frame_cannot_pass_the_forced_menu_roundtrip():
    correct = frame("cn_pages/classic_restored_lobby.png")
    device = device_for(repeat(correct))
    assert not nav.navigate_cn_classic_1v1(device, Logger(), ChineseVision(), verify_menu=True)
    assert device.clicks == [CN_CLASSIC_MODE_SELECTOR] and device.swipes == []
    assert device.observations == 11


def test_destination_timeout_never_reopens_the_selector_or_repeats_the_row_tap():
    wrong = frame("cn_pages/classic_2v2_lobby.png")
    row = frame("cn_pages/game_modes_classic_visible.png")
    device = device_for(chain([wrong, *([row] * 3)], repeat(wrong)))
    assert not nav.navigate_cn_classic_1v1(device, Logger(), ChineseVision(), verify_menu=True)
    assert device.clicks == [CN_CLASSIC_MODE_SELECTOR, (319, 449)] and device.swipes == []
    assert device.observations == 14


def test_real_fast_scroll_trace_reverses_at_stalled_bottom_to_recover_the_clipped_row():
    top = frame("cn_pages/mode_trace_top.png")
    clipped = frame("cn_pages/mode_trace_clipped.png")
    bottom = frame("cn_pages/mode_trace_bottom.png")
    bottom_again = frame("cn_pages/mode_trace_bottom_again.png")
    visible = frame("cn_pages/game_modes_classic_visible.png")
    correct = frame("cn_pages/classic_restored_lobby.png")
    assert cn_classic_mode_point(clipped) is None and cn_classic_mode_point(bottom) is None
    device = device_for([top, clipped, bottom, bottom_again, bottom_again, visible, *([correct] * 3)])
    assert nav.navigate_cn_classic_1v1(device, Logger(), ChineseVision(), verify_menu=True)
    assert device.swipes == [CN_CLASSIC_MODE_SCROLL_TO_BOTTOM] * 4 + [CN_CLASSIC_MODE_SCROLL_TO_TOP]
    assert device.clicks == [(319, 449)]


def test_starting_at_stalled_bottom_does_not_reset_the_entire_drawer():
    bottom = frame("cn_pages/mode_trace_bottom.png")
    visible = frame("cn_pages/game_modes_classic_visible.png")
    correct = frame("cn_pages/classic_restored_lobby.png")
    device = device_for([bottom, bottom, bottom, visible, *([correct] * 3)])
    assert nav.navigate_cn_classic_1v1(device, Logger(), ChineseVision(), verify_menu=True)
    assert device.swipes == [CN_CLASSIC_MODE_SCROLL_TO_BOTTOM] * 2 + [CN_CLASSIC_MODE_SCROLL_TO_TOP]
    assert device.clicks == [(319, 449)]


@pytest.mark.parametrize("max_steps", [0, -1, True, 2.5])
def test_invalid_input_budget_never_observes_or_taps(max_steps):
    device = device_for([])
    assert not nav.navigate_cn_classic_1v1(device, Logger(), ChineseVision(), max_steps=max_steps)
    assert device.observations == 0 and device.clicks == [] and device.swipes == []


@pytest.mark.parametrize("source", [None, np.zeros((632, 419, 3), np.uint8), np.zeros((633, 419, 3), float)])
def test_invalid_frame_is_rejected_before_classification(source):
    device = device_for([source])
    vision = SimpleNamespace(classify=lambda frame: pytest.fail("Cannot classify an invalid capture"))
    assert not nav.navigate_cn_classic_1v1(device, Logger(), vision)
    assert device.clicks == [] and device.swipes == []
