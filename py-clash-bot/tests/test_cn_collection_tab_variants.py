"""The current Collection tab preserves verified Deck and lobby return paths."""

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from pyclashbot.bot import cn_random_mastery_loop as loop_module
from pyclashbot.bot.cn_1v1_loop import ChineseVision
from pyclashbot.bot.cn_random_mastery_loop import RandomMasteryLoop
from pyclashbot.bot.coords import CN_PAGE_ROIS, CN_RANDOM_DECK_TAB
from pyclashbot.detection.cn_page_navigation import cn_navigation_step
from pyclashbot.detection.cn_random_ui import random_ui_is
from pyclashbot.emulators.base import CLASH_ROYALE_PACKAGE

FIXTURES = Path(__file__).with_name("fixtures")


def frame(name):
    source = cv2.imread(str(FIXTURES / name))
    assert source is not None, name
    return source


@pytest.mark.parametrize("name", ["collection", "collection_tab_20261005"])
def test_original_and_current_collection_tabs_are_recognized(name):
    source = frame(f"cn_random_mastery/{name}.png")
    assert random_ui_is(source, "collection")
    assert not random_ui_is(source, "deck")


@pytest.mark.parametrize("name", ["collection", "collection_tab_20261005"])
@pytest.mark.parametrize("factor", [0.0, 0.35, 0.8, 0.9, 0.94])
def test_both_collection_tabs_dimmed_by_an_overlay_are_rejected(name, factor):
    source = frame(f"cn_random_mastery/{name}.png")
    assert not random_ui_is((source * factor).astype(np.uint8), "collection")


def test_current_collection_has_three_verified_cues_and_a_fresh_battle_return_control():
    source = frame("cn_random_mastery/collection_tab_20261005.png")
    step = cn_navigation_step(source)
    assert step is not None and step.page == "collection_cards_current" and step.route == "collection"
    assert step.target == (246, 603) and len(step.scores) == 3


@pytest.mark.parametrize("factor", [0.0, 0.35, 0.8, 0.9, 0.94])
def test_current_collection_dimmed_under_an_overlay_authorizes_no_return(factor):
    source = frame("cn_random_mastery/collection_tab_20261005.png")
    assert cn_navigation_step((source * factor).astype(np.uint8)) is None


@pytest.mark.parametrize("roi", ["collection_header", "collection_nav_selected", "collection_nav_battle"])
def test_current_collection_requires_each_independent_navigation_region(roi):
    source = frame("cn_random_mastery/collection_tab_20261005.png")
    x1, y1, x2, y2 = CN_PAGE_ROIS[roi]
    source[y1:y2, x1:x2] = 0
    assert cn_navigation_step(source) is None


def runner_for(source, monkeypatch):
    monkeypatch.setattr(loop_module.time, "sleep", lambda seconds: None)
    deck = frame("cn_random_mastery/deck.png")
    runner = RandomMasteryLoop.__new__(RandomMasteryLoop)
    runner._frame = Mock(side_effect=[source, deck])
    runner.logger = logging.getLogger("collection-tab-variant")
    runner.vision = ChineseVision()
    runner.device = SimpleNamespace(
        click=Mock(), screenshot=lambda: deck, foreground_package=lambda: CLASH_ROYALE_PACKAGE
    )
    runner.state = "generating_deck"
    runner.pending_mastery, runner.pending_claim_all, runner.pending_battle = False, False, False
    runner._event, runner._save, runner._tap = Mock(), Mock(return_value={"fixture": True}), Mock()
    return runner, deck


def test_actual_mismatch_returns_through_existing_named_collection_to_deck_route(monkeypatch):
    source = frame("cn_random_mastery/collection_tab_20261005.png")
    runner, deck = runner_for(source, monkeypatch)
    assert runner._require("deck") is deck
    runner.device.click.assert_called_once_with(*CN_RANDOM_DECK_TAB)
    assert runner._event.call_args.args[0] == "collection_return_to_deck"
    runner._tap.assert_not_called()


def test_current_collection_startup_can_use_the_verified_return_to_classic_lobby(monkeypatch):
    source = frame("cn_random_mastery/collection_tab_20261005.png")
    runner, _ = runner_for(source, monkeypatch)
    assert runner._startup_frame() is source
    assert runner._return_known_page(source, expected="classic_lobby")
    runner.device.click.assert_called_once_with(246, 603)
    assert runner._event.call_args.args[0] == "known_page_return"
    runner._tap.assert_not_called()


@pytest.mark.parametrize(
    "name",
    [
        "cn_random_mastery/deck.png",
        "cn_random_mastery/mastery_list.png",
        "cn_random_mastery/mastery_detail.png",
        "cn_random_mastery/late_post_battle_reward.png",
        "cn_pages/game_modes_blue_top.png",
        "cn_pages/settings.png",
        "cn_567/classic1v1_lobby.png",
        "cn_random_hand/live_hand_0.png",
        "cn_results/win_two_zero.png",
    ],
)
def test_foreign_pages_cannot_become_the_collection_tab(name):
    assert not random_ui_is(frame(name), "collection")
