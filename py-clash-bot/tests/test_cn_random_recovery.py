"""Offline regressions for remembered tabs and delayed post-battle rewards."""

import logging
from itertools import chain, repeat
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from pyclashbot.bot import cn_random_mastery_loop as loop_module
from pyclashbot.bot.cn_1v1_loop import ChineseVision, RecoveryExhausted
from pyclashbot.bot.cn_random_mastery_loop import RandomMasteryLoop
from pyclashbot.bot.coords import (
    CARD_PAGE_ICON_FROM_CLASH_MAIN,
    CN_POST_WIN_REWARD_TAP,
    CN_RANDOM_DECK_TAB,
    CN_RANDOM_MASTERY,
)
from pyclashbot.bot.nav import PAGE_CN_CARD, PAGE_CN_MAIN
from pyclashbot.bot.state_detect import check_if_on_cn_random_collection
from pyclashbot.detection.cn_random_ui import random_ui_is
from pyclashbot.emulators.base import CLASH_ROYALE_PACKAGE

FIXTURES = Path(__file__).with_name("fixtures") / "cn_random_mastery"


def frame(name):
    source = cv2.imread(str(FIXTURES / f"{name}.png"))
    assert source is not None, f"Missing regression fixture: {name}"
    return source


@pytest.fixture
def clock(monkeypatch):
    """Advance only on waits so timeout and stability checks stay deterministic."""
    value = SimpleNamespace(now=0.0)

    def sleep(seconds):
        value.now += seconds

    monkeypatch.setattr(loop_module.time, "monotonic", lambda: value.now)
    monkeypatch.setattr(loop_module.time, "sleep", sleep)
    return value


def runner_for(snapshots):
    runner = RandomMasteryLoop.__new__(RandomMasteryLoop)
    frames = iter(snapshots)
    runner._frame = lambda: next(frames)
    runner.logger = logging.getLogger("cn-recovery-regression")
    runner.device = SimpleNamespace(foreground_package=lambda: CLASH_ROYALE_PACKAGE)
    runner.vision = ChineseVision()
    runner.state = "mastery"
    runner.pending_mastery = True
    runner.pending_claim_all = False
    runner.pending_battle = False
    runner.completed = 17
    runner.generated = 18
    runner.closed_loops = 16
    runner.total_claimed = 4
    runner.events = []
    runner.taps = []
    runner._event = lambda event, **values: runner.events.append((event, values))
    runner._save = lambda *args: {"fixture": True}
    runner._tap = lambda point, *args: runner.taps.append(point)
    return runner


def test_real_collection_failure_frame_is_recognized():
    source = frame("collection")
    assert random_ui_is(source, "collection")
    assert not random_ui_is(source, "deck")
    assert check_if_on_cn_random_collection(SimpleNamespace(screenshot=lambda: source))
    assert not random_ui_is((source * 0.35).astype(np.uint8), "collection")
    assert not random_ui_is(np.zeros_like(source), "collection")
    assert not random_ui_is(source[:600], "collection")


@pytest.mark.parametrize(
    "name",
    [
        "deck",
        "previous_deck",
        "deck_menu",
        "deck_confirm",
        "mastery_list",
        "mastery_detail",
        "mastery_locked",
        "mastery_claim_all",
        "mastery_reward_coin",
        "mastery_reward_continue",
        "late_post_battle_reward",
    ],
)
def test_other_real_pages_are_not_collection(name):
    assert not random_ui_is(frame(name), "collection")


def test_real_late_reward_has_verified_reward_and_continuation_evidence():
    source = frame("late_post_battle_reward")
    vision = ChineseVision()
    assert vision.classify(source)[0] == "reward"
    assert vision.reward_continuation(source)
    assert not random_ui_is(source, "deck")
    assert not random_ui_is(source, "mastery_list")


@pytest.mark.parametrize("expected", ["deck", "mastery_list"])
@pytest.mark.parametrize("continuation_only", [False, True])
def test_require_recovers_late_reward_and_reenters_interrupted_page(expected, continuation_only, clock):
    deck = frame("deck")
    destination = deck if expected == "deck" else frame("mastery_list")
    snapshots = [frame("late_post_battle_reward"), deck]
    if expected == "mastery_list":
        snapshots.append(destination)
    runner = runner_for(snapshots)
    if continuation_only:
        runner.vision.classify = lambda _: ("unknown", None)
    returns, routes = [], []

    def return_from_result():
        assert runner._page_recovery_active
        runner.state = "returning"
        returns.append("reward-cleared")

    runner._return_from_result = return_from_result
    runner._navigate = lambda start, end: routes.append((start, end))
    assert runner._require(expected) is destination
    assert returns == ["reward-cleared"]
    assert routes == [(PAGE_CN_MAIN, PAGE_CN_CARD)]
    assert runner.taps == ([CN_RANDOM_MASTERY] if expected == "mastery_list" else [])
    assert runner.state == "mastery" and not runner._page_recovery_active
    assert (runner.completed, runner.generated, runner.closed_loops, runner.total_claimed) == (17, 18, 16, 4)
    assert runner.pending_mastery and not runner.pending_claim_all
    assert runner.events[0][0] == "late_post_battle_reward"


@pytest.mark.parametrize("expected", ["deck", "mastery_list"])
def test_pending_claim_all_cannot_be_taken_over_by_post_battle_recovery(expected, clock):
    runner = runner_for(repeat(frame("late_post_battle_reward")))
    runner.pending_claim_all = True
    runner._return_from_result = lambda: pytest.fail("Claim all needs its receipt recovery")
    runner._navigate = lambda *args: pytest.fail("Unconfirmed navigation")
    with pytest.raises(RecoveryExhausted, match="未确认"):
        runner._require(expected)
    assert runner.pending_claim_all and runner.pending_mastery
    assert runner.taps == []
    assert runner.events[-1][0] == "screen_mismatch"


@pytest.mark.parametrize("blocked", ["no_checkpoint", "nested_recovery"])
def test_reward_continuation_cannot_create_or_nest_recovery_context(blocked, clock):
    runner = runner_for(repeat(frame("late_post_battle_reward")))
    if blocked == "no_checkpoint":
        runner.pending_mastery = False
    else:
        runner._page_recovery_active = True
    runner._return_from_result = lambda: pytest.fail("Recovery must remain bounded and contextual")
    runner._navigate = lambda *args: pytest.fail("Unconfirmed navigation")
    with pytest.raises(RecoveryExhausted):
        runner._require("deck")
    assert runner.taps == []


def test_require_attempts_reward_recovery_at_most_twice(clock):
    runner = runner_for(repeat(frame("late_post_battle_reward")))
    returns = []
    runner._return_from_result = lambda: returns.append("reward")
    runner._navigate = lambda *args: None
    with pytest.raises(RecoveryExhausted):
        runner._require("deck")
    assert returns == ["reward", "reward"]
    assert not runner._page_recovery_active
    assert runner.taps == []


def test_collection_returns_through_verified_named_deck_navigation(clock):
    deck = frame("deck")
    runner = runner_for([frame("collection"), deck])
    clicks = []
    runner.device.click = lambda *point: clicks.append(point)
    runner.device.screenshot = lambda: deck
    assert runner._require("deck") is deck
    assert clicks == [CN_RANDOM_DECK_TAB]
    assert runner.taps == []
    assert runner.events[0][0] == "collection_return_to_deck"


def test_waiting_for_deck_can_recover_from_verified_lobby(clock):
    lobby = cv2.imread(str(FIXTURES.parent / "cn_567" / "classic1v1_lobby.png"))
    assert lobby is not None
    deck = frame("deck")
    runner = runner_for([lobby, deck])
    assert runner.vision.classify(lobby)[0] == "lobby"
    assert not random_ui_is(lobby, "deck")
    assert not random_ui_is(lobby, "collection")
    clicks = []
    runner.device.click = lambda *point: clicks.append(point)
    runner.device.screenshot = lambda: deck
    assert runner._require("deck") is deck
    assert clicks == [CARD_PAGE_ICON_FROM_CLASH_MAIN]
    assert runner.taps == []
    assert (runner.completed, runner.generated, runner.closed_loops) == (17, 18, 16)


def test_unknown_page_times_out_without_any_input(clock):
    unknown = np.zeros((633, 419, 3), dtype=np.uint8)
    runner = runner_for(repeat(unknown))
    runner._return_from_result = lambda: pytest.fail("Unknown page cannot justify reward input")
    runner._navigate = lambda *args: pytest.fail("Unknown page cannot justify navigation")
    with pytest.raises(RecoveryExhausted, match="未确认 deck"):
        runner._require("deck")
    assert runner.taps == []
    assert runner.events[-1][0] == "screen_mismatch"


@pytest.mark.parametrize("name", ["collection", "late_post_battle_reward"])
def test_startup_accepts_recognized_recovery_checkpoints(name, clock):
    source = frame(name)
    runner = runner_for([source])
    assert runner._startup_frame() is source


def test_startup_requires_post_battle_context_for_continuation_only_frame(clock):
    runner = runner_for(repeat(frame("late_post_battle_reward")))
    runner.pending_mastery = False
    runner.vision.classify = lambda _: ("unknown", None)
    with pytest.raises(RecoveryExhausted, match="90秒"):
        runner._startup_frame()
    assert runner.taps == []


def test_returning_waits_for_three_continuous_lobby_seconds_after_late_reward(clock):
    runner = runner_for([])
    snapshots = chain(["lobby", "late_reward"], repeat("lobby"))
    post_reward_lobby = []

    def snapshot():
        value = next(snapshots)
        if value == "lobby" and runner.taps and not post_reward_lobby:
            post_reward_lobby.append(clock.now)
        return value

    runner._frame = snapshot
    runner.vision = SimpleNamespace(
        classify=lambda source: ("lobby" if source == "lobby" else "unknown", None),
        reward_continuation=lambda source: source == "late_reward",
        find=lambda *args: None,
    )

    def tap(point, delay):
        runner.taps.append(point)
        loop_module.time.sleep(delay)

    runner._tap = tap
    runner._return_from_result()
    assert runner.taps == [CN_POST_WIN_REWARD_TAP]
    assert post_reward_lobby and clock.now - post_reward_lobby[0] >= 3
    assert [event for event, _ in runner.events] == ["returned_lobby"]


@pytest.mark.parametrize("claim_pending", [False, True])
def test_returning_unknown_continuation_without_post_battle_context_never_taps(claim_pending, clock):
    runner = runner_for(repeat("unknown"))
    runner.pending_mastery = claim_pending
    runner.pending_claim_all = claim_pending
    runner.vision = SimpleNamespace(
        classify=lambda _: ("unknown", None),
        reward_continuation=lambda _: True,
        find=lambda *args: None,
    )
    with pytest.raises(RecoveryExhausted, match="未返回大厅"):
        runner._return_from_result()
    assert runner.taps == []
    assert not runner.events


def test_collection_resume_preserves_counters_and_finishes_existing_mastery_checkpoint(clock):
    collection, deck = frame("collection"), frame("deck")
    runner = runner_for([collection, deck])
    runner._startup_frame = lambda: collection
    runner.device.click = lambda *args: None
    runner.device.screenshot = lambda: deck
    mastery, checkpoints = [], []
    runner._mastery = lambda: mastery.append("resumed-existing-battle")
    runner._checkpoint = lambda: checkpoints.append((runner.closed_loops, runner.pending_mastery))

    def stop_before_new_battle():
        raise KeyboardInterrupt

    runner._new_deck = stop_before_new_battle
    with pytest.raises(KeyboardInterrupt):
        runner.run_forever()
    assert mastery == ["resumed-existing-battle"]
    assert checkpoints == [(17, False)]
    assert (runner.completed, runner.generated, runner.total_claimed) == (17, 18, 4)
    assert not runner.pending_mastery and not runner.pending_battle
    assert any(event == "cycle_complete" and values.get("resumed") for event, values in runner.events)
