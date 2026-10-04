"""Loop integration uses fresh learned-page evidence and retains owner context."""

from functools import cache
from itertools import repeat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from pyclashbot.bot import cn_random_mastery_loop as random_module
from pyclashbot.bot import nav
from pyclashbot.bot.cn_1v1_loop import ChineseOneVOneLoop, ChineseVision, RecoveryExhausted
from pyclashbot.bot.cn_random_mastery_loop import RandomMasteryLoop
from pyclashbot.detection import cn_page_navigation as detector
from pyclashbot.detection.cn_page_navigation import NavigationStep
from pyclashbot.emulators.base import CLASH_ROYALE_PACKAGE

FIXTURES = Path(__file__).with_name("fixtures")
LOBBY = "cn_567/classic1v1_lobby.png"
DECK = "cn_random_mastery/deck.png"


@cache
def captured(name):
    frame = cv2.imread(str(FIXTURES / name))
    assert frame is not None, f"Missing captured integration fixture: {name}"
    return frame


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    value = SimpleNamespace(now=101.0)

    def sleep(seconds):
        value.now += seconds

    # The modules share stdlib time; advance real timeout loops without waiting.
    monkeypatch.setattr(random_module.time, "monotonic", lambda: value.now)
    monkeypatch.setattr(random_module.time, "sleep", sleep)
    return value


def random_runner(snapshots):
    runner = RandomMasteryLoop.__new__(RandomMasteryLoop)
    runner._frame = Mock(side_effect=snapshots)
    runner.device = SimpleNamespace(
        click=Mock(),
        adb=Mock(),
        foreground_package=Mock(return_value=CLASH_ROYALE_PACKAGE),
        screenshot=Mock(side_effect=AssertionError("Return helper must use the supplied observation")),
    )
    runner.vision = ChineseVision()
    runner.logger = Mock()
    runner._event = Mock()
    runner._save = Mock(return_value={"fixture": True})
    runner._tap = Mock()
    runner.state = "generating_deck"
    runner.pending_mastery = True
    runner.pending_claim_all = False
    runner.pending_battle = False
    runner.reward_receipts = [{"id": "saved-claim-receipt", "kind": "coins", "amount": 4000}]
    runner.reward_claim_id = "saved-claim-id"
    runner.completed, runner.generated, runner.closed_loops, runner.total_claimed = 19, 20, 18, 4
    return runner


def one_runner(state="lobby"):
    runner = ChineseOneVOneLoop.__new__(ChineseOneVOneLoop)
    runner.vision = Mock(wraps=ChineseVision())
    runner.device = SimpleNamespace(click=Mock(), adb=Mock(), screenshot=Mock())
    runner.logger = Mock()
    runner._trace = Mock()
    runner._save_evidence = Mock(return_value={"fixture": True})
    runner._tap = Mock()
    runner._recover = Mock()
    runner._play_card = Mock()
    runner._clock_stalled = Mock(return_value=False)
    runner._set_state = Mock()
    runner.state, runner.state_since = state, 100.0
    runner.last_unknown_evidence = 100.0
    runner.reward_pending, runner.reward_taps = False, 0
    runner.four_star_reward_seen = False
    runner.last_reward_tap_at, runner.last_four_star_tap_at = 100.0, 0.0
    runner.battle_confirmations, runner.result_confirmations, runner.lobby_confirmations = 0, 0, 0
    runner.completed = 99
    runner.strategy_name = "hog"
    # Page-return tests retain a previously verified Classic mode. Dedicated
    # mode-gate tests exercise the required first menu round trip.
    runner._classic_menu_verified = True
    return runner


def test_random_startup_unwinds_nested_pages_then_returns_the_fresh_lobby():
    names = ["cn_pages/tournament_help.png", "cn_pages/tournament_create.png", "cn_pages/tournaments.png"]
    pages = [captured(name) for name in names]
    lobby = captured(LOBBY)
    runner = random_runner([*pages, lobby])
    assert runner._startup_frame() is lobby
    assert runner._frame.call_count == 4
    assert runner.device.click.call_count == 3
    assert [call.kwargs["page"] for call in runner._event.call_args_list] == [
        "tournament_help",
        "tournament_create",
        "tournaments",
    ]
    assert [call.args[1] is page for call, page in zip(runner._save.call_args_list, pages, strict=True)] == [True] * 3
    runner._tap.assert_not_called()
    runner.device.screenshot.assert_not_called()
    assert runner.pending_mastery and runner.reward_receipts[0]["id"] == "saved-claim-receipt"


def test_random_manual_mastery_from_card_information_normalizes_its_actual_parent_chain():
    pages = [
        captured(f"cn_pages/{name}.png")
        for name in ("card_mastery_from_info", "mastery_to_card_info", "card_info_to_editor")
    ]
    deck = captured("cn_pages/card_editor_confirmed.png")
    expected_pages, expected_targets = [], []
    for page in pages:
        step = detector.cn_navigation_step(page)
        assert step is not None
        expected_pages.append(step.page)
        expected_targets.append(step.target)
    runner = random_runner([*pages, deck])
    runner.pending_mastery = False
    assert runner._startup_frame() is deck
    assert runner._frame.call_count == 4
    assert [call.kwargs["page"] for call in runner._event.call_args_list] == expected_pages
    assert [call.args for call in runner.device.click.call_args_list] == expected_targets
    assert runner.reward_claim_id == "saved-claim-id"
    assert runner.reward_receipts == [{"id": "saved-claim-receipt", "kind": "coins", "amount": 4000}]
    assert (runner.completed, runner.generated, runner.closed_loops, runner.total_claimed) == (19, 20, 18, 4)
    runner._tap.assert_not_called()


@pytest.mark.parametrize("flag", ["pending_mastery", "pending_claim_all"])
def test_random_owned_mastery_page_stays_with_its_checkpoint_workflow(flag):
    page = captured("cn_pages/card_mastery_from_info.png")
    assert random_module.random_ui_is(page, "mastery_detail")
    runner = random_runner([page])
    runner.pending_mastery = False
    setattr(runner, flag, True)
    assert runner._startup_frame() is page
    assert runner._frame.call_count == 1
    runner.device.click.assert_not_called()
    runner.device.adb.assert_not_called()
    runner._event.assert_not_called()
    assert getattr(runner, flag)


@pytest.mark.parametrize("name", [LOBBY, DECK, "cn_random_mastery/collection.png"])
def test_random_core_startup_page_remains_ready_without_manual_normalization(name):
    page = captured(name)
    runner = random_runner([page])
    runner.pending_mastery = False
    assert runner._startup_frame() is page
    assert runner._frame.call_count == 1
    runner.device.click.assert_not_called()
    runner.device.adb.assert_not_called()


def test_random_require_deck_confirms_editor_footer_before_accepting_weak_deck_match(monkeypatch):
    editor, deck = captured("cn_pages/card_info_to_editor.png"), captured("cn_pages/card_editor_confirmed.png")
    assert random_module.random_ui_is(editor, "deck")
    step = detector.cn_navigation_step(editor)
    assert step is not None and step.page == "card_editor" and step.target is not None
    runner = random_runner([editor, deck])
    tab_navigation = Mock()
    monkeypatch.setattr(random_module, "navigate_main_page", tab_navigation)
    assert runner._require("deck") is deck
    assert runner._frame.call_count == 2
    runner.device.click.assert_called_once_with(*step.target)
    tab_navigation.assert_not_called()
    runner.device.screenshot.assert_not_called()
    assert runner._save.call_args.args[1] is editor
    assert runner.pending_mastery and not runner.pending_claim_all and not runner.pending_battle


def test_random_navigate_cannot_treat_unconfirmed_editor_as_deck_tab_source(monkeypatch):
    editor, deck = captured("cn_pages/card_info_to_editor.png"), captured("cn_pages/card_editor_confirmed.png")
    assert random_module.random_ui_is(editor, "deck")
    step = detector.cn_navigation_step(editor)
    assert step is not None and step.page == "card_editor" and step.target is not None
    runner = random_runner([editor, deck, captured(LOBBY)])
    tab_observation_counts = []

    def navigate(*args):
        tab_observation_counts.append(runner._frame.call_count)
        assert args[2:] == (nav.PAGE_CN_CARD, nav.PAGE_CN_MAIN)

    monkeypatch.setattr(random_module, "navigate_main_page", navigate)
    runner._navigate(nav.PAGE_CN_CARD, nav.PAGE_CN_MAIN)
    assert tab_observation_counts == [2]
    assert runner._frame.call_count == 3
    runner.device.click.assert_called_once_with(*step.target)
    runner.device.screenshot.assert_not_called()
    runner._tap.assert_not_called()


def test_random_require_deck_recovers_known_page_before_fresh_lobby_to_deck_navigation(monkeypatch):
    nested, lobby, deck = captured("cn_pages/elite_info.png"), captured(LOBBY), captured(DECK)
    runner = random_runner([nested, lobby, deck])
    route = Mock()
    monkeypatch.setattr(random_module, "navigate_main_page", route)
    assert runner._require("deck") is deck
    assert runner._frame.call_count == 3
    runner.device.click.assert_called_once_with(358, 62)
    assert route.call_count == 1
    assert route.call_args.args[2:] == (nav.PAGE_CN_MAIN, nav.PAGE_CN_CARD)
    assert runner._save.call_args_list[0].args[1] is nested
    assert runner._save.call_args_list[1].args[1] is lobby
    assert (runner.completed, runner.generated, runner.closed_loops, runner.total_claimed) == (19, 20, 18, 4)


def test_random_navigate_waits_for_fresh_source_after_nested_pages_before_switching_tab(monkeypatch):
    pages = [captured("cn_pages/leaderboard_players.png"), captured("cn_pages/battle_log.png")]
    lobby, deck = captured(LOBBY), captured(DECK)
    runner = random_runner([*pages, lobby, deck])
    observations_at_tab_navigation = []

    def navigate(*args):
        observations_at_tab_navigation.append(runner._frame.call_count)
        assert args[2:] == (nav.PAGE_CN_MAIN, nav.PAGE_CN_CARD)

    monkeypatch.setattr(random_module, "navigate_main_page", navigate)
    runner._navigate(nav.PAGE_CN_MAIN, nav.PAGE_CN_CARD)
    assert observations_at_tab_navigation == [3]
    assert runner._frame.call_count == 4 and runner.device.click.call_count == 2
    assert [call.args[1] is page for call, page in zip(runner._save.call_args_list, pages, strict=True)] == [True] * 2
    runner._tap.assert_not_called()


@pytest.mark.parametrize("flag", ["pending_battle", "pending_claim_all"])
@pytest.mark.parametrize("page", ["tournaments", "spectate", "spectate_exit_confirm"])
def test_random_known_page_return_retains_pending_battle_and_claim_receipts(flag, page):
    source = captured(f"cn_pages/{page}.png")
    runner = random_runner([])
    setattr(runner, flag, True)
    assert not runner._return_known_page(source, expected="deck")
    runner.device.click.assert_not_called()
    runner.device.adb.assert_not_called()
    runner._event.assert_not_called()
    assert getattr(runner, flag)
    assert runner.reward_claim_id == "saved-claim-id"
    assert runner.reward_receipts == [{"id": "saved-claim-receipt", "kind": "coins", "amount": 4000}]


@pytest.mark.parametrize("name", ["random_deck_confirmation", "delete_deck_confirmation"])
@pytest.mark.parametrize("state", ["generating_deck", "starting"])
def test_random_confirmation_cancel_is_allowed_only_outside_owned_generation(name, state):
    page = captured(f"cn_pages/{name}.png")
    step = detector.cn_navigation_step(page)
    assert step is not None and step.unowned_only and step.target is not None
    runner = random_runner([])
    runner.state = state
    returned = runner._return_known_page(page, expected="startup")
    if state == "generating_deck":
        assert not returned
        runner.device.click.assert_not_called()
    else:
        assert returned
        runner.device.click.assert_called_once_with(*step.target)
    runner.device.adb.assert_not_called()
    runner._tap.assert_not_called()
    assert runner.reward_claim_id == "saved-claim-id"
    assert (runner.completed, runner.generated, runner.closed_loops, runner.total_claimed) == (19, 20, 18, 4)


@pytest.mark.parametrize("flag", ["pending_battle", "pending_claim_all"])
@pytest.mark.parametrize("name", ["random_deck_confirmation", "delete_deck_confirmation"])
def test_random_pending_work_blocks_unowned_cancel_even_outside_generation(flag, name):
    runner = random_runner([])
    runner.state = "starting"
    setattr(runner, flag, True)
    assert not runner._return_known_page(captured(f"cn_pages/{name}.png"), expected="startup")
    runner.device.click.assert_not_called()
    runner.device.adb.assert_not_called()
    runner._event.assert_not_called()
    assert getattr(runner, flag) and runner.reward_receipts[0]["id"] == "saved-claim-receipt"


def test_random_pending_claim_cannot_navigate_during_require(monkeypatch):
    runner = random_runner(repeat(captured("cn_pages/tournaments.png")))
    runner.pending_claim_all = True
    route = Mock()
    monkeypatch.setattr(random_module, "navigate_main_page", route)
    with pytest.raises(RecoveryExhausted, match="未确认 deck"):
        runner._require("deck")
    route.assert_not_called()
    runner.device.click.assert_not_called()
    runner.device.adb.assert_not_called()
    assert runner.pending_claim_all and runner.reward_claim_id == "saved-claim-id"


@pytest.mark.parametrize("page", ["spectate", "spectate_exit_confirm"])
@pytest.mark.parametrize("state", ["matching", "battle"])
def test_random_spectator_exit_is_forbidden_while_loop_state_is_matching_or_battle(page, state):
    runner = random_runner([])
    runner.state = state
    # An inconsistent checkpoint must fail closed even before pending is set.
    assert not runner.pending_battle
    assert not runner._return_known_page(captured(f"cn_pages/{page}.png"), expected="startup")
    runner.device.click.assert_not_called()
    runner.device.adb.assert_not_called()


def test_random_idle_spectator_unwinds_keyback_confirmation_and_tv_with_fresh_frames():
    pages = [captured(f"cn_pages/{name}.png") for name in ("spectate", "spectate_exit_confirm", "royale_tv")]
    lobby = captured(LOBBY)
    runner = random_runner([*pages, lobby])
    assert runner._startup_frame() is lobby
    assert runner._frame.call_count == 4
    runner.device.adb.assert_called_once_with("shell input keyevent 4")
    assert runner.device.click.call_count == 2
    assert runner.device.click.call_args_list[0].args == (276, 392)
    assert [call.kwargs["page"] for call in runner._event.call_args_list] == [
        "spectate",
        "spectate_exit_confirm",
        "royale_tv",
    ]
    runner.device.screenshot.assert_not_called()


@pytest.mark.parametrize("entry", ["startup", "require", "navigate"])
def test_random_navigation_retry_budget_never_issues_more_than_twelve_inputs(entry, monkeypatch):
    source = np.full((633, 419, 3), (30, 50, 70), np.uint8)
    runner = random_runner(repeat(source))
    runner.vision = SimpleNamespace(classify=lambda _: ("navigation", None), reward_continuation=lambda _: False)
    step = NavigationStep("tournaments", "tournaments_back", (35, 55), (1.0, 1.0))
    recognized = Mock(return_value=step)
    monkeypatch.setattr(detector, "cn_navigation_step", recognized)
    monkeypatch.setattr(nav, "cn_navigation_step", recognized)
    monkeypatch.setattr(random_module, "cn_navigation_step", recognized)
    monkeypatch.setattr(random_module, "random_ui_is", lambda *_: False)
    with pytest.raises(RecoveryExhausted):
        if entry == "startup":
            runner._startup_frame()
        elif entry == "require":
            runner._require("deck")
        else:
            runner._navigate(nav.PAGE_CN_MAIN, nav.PAGE_CN_CARD)
    assert runner.device.click.call_count == 12
    runner.device.adb.assert_not_called()
    assert len([call for call in runner._event.call_args_list if call.args[0] == "known_page_return"]) == 12
    assert runner._frame.call_count > 12


@pytest.mark.parametrize("name", ["burger_menu", "settings", "more_settings_top", "inbox"])
def test_chinese_vision_marks_saved_overlay_as_navigation_before_any_lobby_match(name):
    kind, match = ChineseVision().classify(captured(f"cn_pages/{name}.png"))
    assert kind == "navigation" and match is None


def test_chinese_burger_overlay_closes_then_fresh_classic_lobby_starts_match():
    runner = one_runner()
    burger, lobby = captured("cn_pages/burger_menu.png"), captured(LOBBY)
    runner._step(burger)
    assert runner.state == "lobby"
    runner._tap.assert_not_called()
    runner.device.click.assert_called_once()
    assert runner._save_evidence.call_args.args[1] is burger
    runner._step(lobby)
    runner._tap.assert_called_once()
    runner._set_state.assert_called_once_with("match")
    assert runner.vision.classify.call_args.args[0] is lobby


@pytest.mark.parametrize("state", ["battle", "match", "result"])
@pytest.mark.parametrize("page", ["spectate", "spectate_exit_confirm", "burger_menu"])
def test_chinese_navigation_cannot_exit_spectator_or_click_overlay_during_active_match_context(state, page):
    runner = one_runner(state)
    runner._step(captured(f"cn_pages/{page}.png"))
    runner.device.adb.assert_not_called()
    runner.device.click.assert_not_called()
    runner._tap.assert_not_called()
    runner._set_state.assert_not_called()


def test_chinese_existing_reward_context_cannot_be_replaced_by_navigation():
    runner = one_runner()
    runner.reward_pending, runner.reward_taps = True, 7
    runner._step(captured("cn_pages/tournaments.png"))
    runner.device.click.assert_not_called()
    runner.device.adb.assert_not_called()
    runner._tap.assert_not_called()
    assert runner.reward_pending and runner.reward_taps == 7


def test_chinese_navigation_retry_budget_is_twelve_and_resets_at_verified_lobby():
    runner = one_runner()
    source = captured("cn_pages/tournaments.png")
    for _ in range(12):
        runner._step(source)
    with pytest.raises(RecoveryExhausted, match="连续12次"):
        runner._step(source)
    assert runner.device.click.call_count == 12
    runner._tap.assert_not_called()
    runner._step(captured(LOBBY))
    assert runner._page_return_attempts == 0
    assert runner.device.click.call_count == 12
    runner._tap.assert_called_once()
