"""Offline regressions for unopened reward chests and fresh navigation sources."""

import logging
from itertools import repeat
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from pyclashbot.bot import cn_random_mastery_loop as loop_module
from pyclashbot.bot.cn_1v1_loop import THRESHOLDS, ChineseVision, RecoveryExhausted
from pyclashbot.bot.cn_random_mastery_loop import RandomMasteryLoop
from pyclashbot.bot.coords import CN_REWARD_BACKGROUND_ROI
from pyclashbot.bot.nav import PAGE_CN_CARD, PAGE_CN_MAIN

FIXTURES = Path(__file__).with_name("fixtures")


def frame(relative):
    source = cv2.imread(str(FIXTURES / relative))
    assert source is not None, f"Missing regression fixture: {relative}"
    return source


@pytest.fixture
def clock(monkeypatch):
    value = SimpleNamespace(now=0.0)

    def sleep(seconds):
        value.now += seconds

    monkeypatch.setattr(loop_module.time, "monotonic", lambda: value.now)
    monkeypatch.setattr(loop_module.time, "sleep", sleep)
    return value


def navigation_runner(snapshots, monkeypatch):
    runner = RandomMasteryLoop.__new__(RandomMasteryLoop)
    snapshots = iter(snapshots)
    runner.logger = logging.getLogger("cn-navigation-recovery-test")
    runner.device = SimpleNamespace(click=lambda *args: pytest.fail("No physical device input"))
    runner.vision = ChineseVision()
    runner.pending_mastery = True
    runner.pending_claim_all = False
    runner.state = "returning"
    runner.completed, runner.generated, runner.closed_loops = 19, 19, 18
    runner.total_claimed = 7
    runner.seen, runner.events, runner.nav_calls, runner.require_calls, runner.returns = [], [], [], [], []

    def snapshot():
        source = next(snapshots)
        runner.seen.append(source)
        return source

    def navigate(device, logger, start, end):
        source = runner.seen[-1]
        if start == PAGE_CN_MAIN:
            assert runner.vision.classify(source)[0] == "lobby"
        else:
            assert loop_module.random_ui_is(source, "deck")
        runner.nav_calls.append((start, end))
        return True

    runner._frame = snapshot
    runner._event = lambda event, **values: runner.events.append((event, values))
    runner._save = lambda *args: {"fixture": True}
    runner._tap = lambda *args: pytest.fail("Unknown navigation source must never be tapped")
    runner._require = runner.require_calls.append
    runner._return_from_result = lambda: runner.returns.append("reward-cleared")
    monkeypatch.setattr(loop_module, "navigate_main_page", navigate)
    return runner


def test_real_soft_floor_chest_is_a_verified_reward_without_lowering_old_thresholds():
    source = frame("cn_rewards/soft_floor_chest.png")
    vision = ChineseVision()
    assert source.shape == (633, 419, 3)
    assert vision.find(source, "reward_star") is not None
    assert vision.find(source, "reward_floor") is None
    assert vision.find(source, "reward_chest_unopened") is not None
    assert vision.unopened_star_reward(source)
    assert vision.classify(source)[0] == "reward"
    assert vision.reward_continuation(source)
    assert THRESHOLDS["reward_floor"] == 0.85
    assert THRESHOLDS["reward_star"] == 0.90
    assert THRESHOLDS["reward_chest_unopened"] == 0.92


@pytest.mark.parametrize("missing", ["reward_star", "reward_chest_unopened"])
def test_reward_chest_needs_both_star_and_box_evidence(missing):
    source = frame("cn_rewards/soft_floor_chest.png")
    vision = ChineseVision()
    match = vision.find(source, missing)
    assert match is not None
    source[match.y : match.y + match.height, match.x : match.x + match.width] = 0
    other = "reward_chest_unopened" if missing == "reward_star" else "reward_star"
    assert vision.find(source, other) is not None
    assert vision.find(source, missing) is None
    assert not vision.unopened_star_reward(source)
    assert vision.classify(source)[0] != "reward"
    assert not vision.reward_continuation(source)


def test_reward_star_and_chest_with_green_sky_are_rejected():
    source = frame("cn_rewards/soft_floor_chest.png")
    x1, y1, x2, y2 = CN_REWARD_BACKGROUND_ROI
    source[y1:y2, x1:x2] = (0, 180, 0)
    vision = ChineseVision()
    assert vision.find(source, "reward_star") is not None
    assert vision.find(source, "reward_chest_unopened") is not None
    assert not vision.unopened_star_reward(source)
    assert vision.classify(source)[0] != "reward"
    assert not vision.reward_continuation(source)


def test_reward_star_and_chest_with_busy_blue_hud_are_rejected():
    source = frame("cn_rewards/soft_floor_chest.png")
    x1, y1, x2, y2 = CN_REWARD_BACKGROUND_ROI
    sky = source[y1:y2, x1:x2]
    sky[:] = (100, 30, 5)
    sky[:, (np.arange(sky.shape[1]) // 4) % 2 == 0] = (200, 80, 20)
    hsv = cv2.cvtColor(sky, cv2.COLOR_BGR2HSV)
    blue = (hsv[:, :, 0] >= 100) & (hsv[:, :, 0] <= 165) & (hsv[:, :, 1] >= 100) & (hsv[:, :, 2] >= 30)
    assert float(np.mean(blue)) >= 0.90
    assert float(np.mean(cv2.Canny(cv2.cvtColor(sky, cv2.COLOR_BGR2GRAY), 20, 60) > 0)) >= 0.025
    vision = ChineseVision()
    assert vision.find(source, "reward_star") is not None
    assert vision.find(source, "reward_chest_unopened") is not None
    assert not vision.unopened_star_reward(source)
    assert vision.classify(source)[0] != "reward"
    assert not vision.reward_continuation(source)


@pytest.mark.parametrize(
    "relative",
    [
        "cn_random_mastery/deck.png",
        "cn_random_mastery/deck_menu.png",
        "cn_random_mastery/deck_confirm.png",
        "cn_random_mastery/collection.png",
        "cn_random_mastery/mastery_list.png",
        "cn_random_mastery/mastery_detail.png",
        "cn_random_mastery/mastery_locked.png",
        "cn_567/classic1v1_lobby.png",
        "cn_567/classic2v2_lobby.png",
        "cn_567/classic_loss.png",
        "cn_results/win_two_zero.png",
        "cn_results/loss_with_blue_crown.png",
        "cn_random_hand/live_hand_0.png",
        "cn_567_v2/audit-b17-130336-observe.png",
    ],
)
def test_unopened_chest_variant_does_not_turn_other_real_pages_into_rewards(relative):
    source = frame(relative)
    vision = ChineseVision()
    assert not vision.unopened_star_reward(source)
    assert vision.classify(source)[0] != "reward"
    assert not vision.reward_continuation(source)


@pytest.mark.parametrize(("before_unknown", "after_unknown"), [(1, 0), (0, 3), (3, 4)])
def test_navigation_reobserves_transition_and_reward_until_a_fresh_lobby(
    before_unknown,
    after_unknown,
    clock,
    monkeypatch,
):
    unknown = np.zeros((633, 419, 3), dtype=np.uint8)
    reward = frame("cn_rewards/soft_floor_chest.png")
    lobby = frame("cn_567/classic1v1_lobby.png")
    snapshots = [unknown] * before_unknown + [reward] + [unknown] * after_unknown + [lobby]
    runner = navigation_runner(snapshots, monkeypatch)
    runner._navigate(PAGE_CN_MAIN, PAGE_CN_CARD)
    assert runner.returns == ["reward-cleared"]
    assert runner.nav_calls == [(PAGE_CN_MAIN, PAGE_CN_CARD)]
    assert runner.require_calls == ["deck"]
    assert runner.seen[-1] is lobby
    assert len(runner.seen) == len(snapshots)
    assert [event for event, _ in runner.events] == ["late_post_battle_reward"]
    assert (runner.completed, runner.generated, runner.closed_loops, runner.total_claimed) == (19, 19, 18, 7)
    assert runner.pending_mastery and not runner.pending_claim_all


def test_card_to_lobby_navigation_also_waits_for_its_verified_source(clock, monkeypatch):
    unknown = np.zeros((633, 419, 3), dtype=np.uint8)
    deck = frame("cn_random_mastery/deck.png")
    lobby = frame("cn_567/classic1v1_lobby.png")
    runner = navigation_runner([unknown, unknown, deck, lobby], monkeypatch)
    runner._navigate(PAGE_CN_CARD, PAGE_CN_MAIN)
    assert runner.nav_calls == [(PAGE_CN_CARD, PAGE_CN_MAIN)]
    assert runner.returns == []
    assert runner.require_calls == []
    assert runner.seen[-1] is lobby


def test_persistent_unknown_navigation_source_exits_with_evidence_and_no_input(clock, monkeypatch):
    unknown = np.zeros((633, 419, 3), dtype=np.uint8)
    runner = navigation_runner(repeat(unknown), monkeypatch)
    with pytest.raises(RecoveryExhausted, match="主页面导航失败"):
        runner._navigate(PAGE_CN_MAIN, PAGE_CN_CARD)
    assert runner.nav_calls == [] and runner.returns == [] and runner.require_calls == []
    assert 8 <= clock.now < 8.3
    event, values = runner.events[-1]
    assert event == "navigation_mismatch"
    assert values["expected"] == "lobby" and values["observed"] == "unknown"
    assert values["recoveries"] == 0 and values["evidence"] == {"fixture": True}


@pytest.mark.parametrize("context", ["claim_all_pending", "no_mastery_checkpoint", "card_source"])
def test_navigation_reward_recovery_requires_the_post_battle_lobby_context(context, clock, monkeypatch):
    runner = navigation_runner(repeat(frame("cn_rewards/soft_floor_chest.png")), monkeypatch)
    if context == "claim_all_pending":
        runner.pending_claim_all = True
    elif context == "no_mastery_checkpoint":
        runner.pending_mastery = False
    start, end = (PAGE_CN_CARD, PAGE_CN_MAIN) if context == "card_source" else (PAGE_CN_MAIN, PAGE_CN_CARD)
    with pytest.raises(RecoveryExhausted):
        runner._navigate(start, end)
    assert runner.returns == [] and runner.nav_calls == [] and runner.require_calls == []
    assert runner.events[-1][0] == "navigation_mismatch"
    assert runner.events[-1][1]["recoveries"] == 0
    if context == "claim_all_pending":
        assert runner.pending_claim_all


def test_repeated_reward_navigation_recovery_is_limited_to_two_attempts(clock, monkeypatch):
    runner = navigation_runner(repeat(frame("cn_rewards/soft_floor_chest.png")), monkeypatch)

    def clear_reward():
        runner.returns.append("reward-cleared")
        loop_module.time.sleep(120)

    runner._return_from_result = clear_reward
    with pytest.raises(RecoveryExhausted):
        runner._navigate(PAGE_CN_MAIN, PAGE_CN_CARD)
    assert runner.returns == ["reward-cleared", "reward-cleared"]
    assert runner.nav_calls == [] and runner.require_calls == []
    assert 248 <= clock.now < 248.3
    assert runner.events[-1][0] == "navigation_mismatch"
    assert runner.events[-1][1]["recoveries"] == 2


def test_unknown_after_reward_clear_has_one_bounded_fresh_observation_window(clock, monkeypatch):
    reward = frame("cn_rewards/soft_floor_chest.png")
    unknown = np.zeros((633, 419, 3), dtype=np.uint8)
    runner = navigation_runner([reward, *([unknown] * 60)], monkeypatch)

    def clear_reward():
        runner.returns.append("reward-cleared")
        loop_module.time.sleep(120)

    runner._return_from_result = clear_reward
    with pytest.raises(RecoveryExhausted):
        runner._navigate(PAGE_CN_MAIN, PAGE_CN_CARD)
    assert runner.returns == ["reward-cleared"]
    assert runner.nav_calls == [] and runner.require_calls == []
    assert 128 <= clock.now < 128.3
    assert runner.events[-1][0] == "navigation_mismatch"
