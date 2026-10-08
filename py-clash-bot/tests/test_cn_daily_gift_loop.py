"""Owned daily cosmetic reveals and fresh app-start observations remain separate."""

from itertools import chain, repeat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import pytest

from pyclashbot.bot import cn_random_mastery_loop as module
from pyclashbot.bot.cn_1v1_loop import ChineseVision, RecoveryExhausted
from pyclashbot.bot.cn_random_mastery_loop import RandomMasteryLoop
from pyclashbot.bot.coords import CN_DAILY_GIFT_COSMETIC_CHOICE, CN_POST_WIN_REWARD_TAP
from pyclashbot.emulators.base import CLASH_ROYALE_PACKAGE

FIXTURES = Path(__file__).with_name("fixtures")


def frame(name):
    image = cv2.imread(str(FIXTURES / name))
    assert image is not None, name
    return image


def emote():
    return frame("cn_daily_gift/emote_reveal_20261006.png")


def loading():
    return frame("cn_daily_gift/loading_after_relaunch_20261006.png")


def black():
    return frame("cn_daily_gift/black_daily_timeout_20261006.png")


def lobby():
    return frame("cn_pages/classic_glow_verified_lobby.png")


@pytest.fixture
def clock(monkeypatch):
    current = SimpleNamespace(now=500.0)
    monkeypatch.setattr(module.time, "monotonic", lambda: current.now)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: setattr(current, "now", current.now + seconds))
    return current


def runner_for(snapshots, tmp_path, clock):
    runner = RandomMasteryLoop.__new__(RandomMasteryLoop)
    runner.stop_path = tmp_path / "STOP"
    runner._capture_frame = Mock(side_effect=snapshots)
    runner.vision = ChineseVision()
    runner.device = SimpleNamespace(
        adb=Mock(return_value=SimpleNamespace(returncode=0)),
        start_app=Mock(),
        foreground_package=Mock(return_value=CLASH_ROYALE_PACKAGE),
        click=Mock(),
    )
    runner.logger, runner._event, runner._save = Mock(), Mock(), Mock(return_value={"fixture": True})
    runner._tap, runner._checkpoint, runner._reset_battle_frame_monitor = Mock(), Mock(), Mock()
    runner.pending_battle, runner.pending_mastery, runner.pending_claim_all = False, True, False
    runner._daily_reward_pending = False
    runner._daily_reward_started_at = clock.now - 5
    runner._daily_reward_taps = 0
    runner._daily_gift_attempts = 0
    runner._classic_menu_verified = True
    runner.recovery_attempts = 1
    runner.state = "returning"
    runner.completed, runner.generated, runner.closed_loops, runner.total_claimed = 1568, 1581, 1567, 185
    runner.reward_claim_id = "saved-claim-id"
    runner.reward_receipts = [{"id": "saved-claim-id", "kind": "coins", "amount": 4000}]
    return runner


def preserved(runner):
    assert (runner.completed, runner.generated, runner.closed_loops, runner.total_claimed) == (1568, 1581, 1567, 185)
    assert runner.reward_claim_id == "saved-claim-id"
    assert runner.reward_receipts == [{"id": "saved-claim-id", "kind": "coins", "amount": 4000}]
    assert runner.pending_mastery and not runner.pending_claim_all and not runner.pending_battle
    runner._checkpoint.assert_not_called()
    runner.device.click.assert_not_called()


def test_real_owned_emote_reveal_continues_once_then_returns_fresh_lobby(tmp_path, clock):
    source, fresh = emote(), lobby()
    runner = runner_for([source, fresh], tmp_path, clock)
    runner._daily_reward_pending = True
    assert runner._frame() is fresh
    runner._tap.assert_called_once_with(CN_POST_WIN_REWARD_TAP, 1.5)
    event = runner._event.call_args
    assert event.args == ("daily_gift_reward",)
    assert event.kwargs["action"] == "continue_daily_gift_reward"
    assert not runner._daily_reward_pending and runner._daily_reward_taps == 0
    preserved(runner)


def test_real_choice_establishes_daily_context_for_the_emote_and_no_other_transaction(tmp_path, clock):
    choice = frame("cn_daily_gift/daily_gift_choice_20261004.png")
    source, fresh = emote(), lobby()
    runner = runner_for([choice, source, fresh], tmp_path, clock)
    assert runner._frame() is fresh
    assert [call.args for call in runner._tap.call_args_list] == [
        (CN_DAILY_GIFT_COSMETIC_CHOICE, 1.5),
        (CN_POST_WIN_REWARD_TAP, 1.5),
    ]
    assert [call.args[0] for call in runner._event.call_args_list] == ["daily_gift_choice", "daily_gift_reward"]
    preserved(runner)


def test_unowned_emote_reveal_never_authorizes_a_daily_reward_tap(tmp_path, clock):
    source = emote()
    runner = runner_for([source], tmp_path, clock)
    assert runner._frame() is source
    runner._tap.assert_not_called()
    runner._event.assert_not_called()
    preserved(runner)


@pytest.mark.parametrize("expired", ["time", "taps"])
def test_new_reveal_detector_preserves_existing_daily_reward_limits(expired, tmp_path, clock):
    runner = runner_for([emote()], tmp_path, clock)
    runner._daily_reward_pending = True
    if expired == "time":
        runner._daily_reward_started_at = clock.now - 121
    else:
        runner._daily_reward_taps = 40
    with pytest.raises(RecoveryExhausted):
        runner._frame()
    runner._tap.assert_not_called()
    preserved(runner)


def test_successful_force_stop_discards_only_the_old_daily_reveal_context(tmp_path, clock):
    runner = runner_for([], tmp_path, clock)
    runner._daily_reward_pending = True
    runner._daily_reward_started_at = clock.now - 121
    runner._daily_reward_taps, runner._daily_gift_attempts = 7, 2
    runner._recover_app("post-result relaunch", emote())
    assert not runner._daily_reward_pending
    assert runner._daily_reward_started_at is None
    assert runner._daily_reward_taps == runner._daily_gift_attempts == 0
    assert runner._awaiting_relaunch_observation
    assert runner.recovery_attempts == 2
    runner.device.start_app.assert_called_once_with(CLASH_ROYALE_PACKAGE)
    runner._tap.assert_not_called()
    preserved(runner)


def test_failed_force_stop_keeps_the_original_daily_context_and_does_not_start(tmp_path, clock):
    runner = runner_for([], tmp_path, clock)
    runner._daily_reward_pending = True
    runner._daily_reward_started_at = clock.now - 121
    runner._daily_reward_taps, runner._daily_gift_attempts = 7, 2
    runner.device.adb.return_value = SimpleNamespace(returncode=1)
    with pytest.raises(RecoveryExhausted, match="游戏停止失败"):
        runner._recover_app("post-result relaunch", emote())
    assert runner._daily_reward_pending and runner._daily_reward_started_at == clock.now - 121
    assert runner._daily_reward_taps == 7 and runner._daily_gift_attempts == 2
    assert not getattr(runner, "_awaiting_relaunch_observation", False)
    runner.device.start_app.assert_not_called()
    runner._tap.assert_not_called()
    preserved(runner)


def test_real_blue_and_black_after_relaunch_get_observation_only_before_the_fresh_lobby(tmp_path, clock):
    blue, empty, fresh = loading(), black(), lobby()
    assert ChineseVision().reward_continuation(blue)  # The former broad-context false positive.
    snapshots = chain(repeat(empty, 6), [blue, fresh])
    runner = runner_for(snapshots, tmp_path, clock)
    runner._daily_reward_pending = True
    runner._daily_reward_started_at = clock.now - 121
    runner._recover_app("post-result relaunch", emote())
    assert runner._startup_frame() is fresh
    assert runner._capture_frame.call_count == 8
    assert not runner._awaiting_relaunch_observation
    assert not runner._daily_reward_pending
    runner._tap.assert_not_called()
    preserved(runner)


def test_relaunch_loading_cannot_become_ready_by_broad_reward_context(tmp_path, clock, monkeypatch):
    # Advance the wall-clock deadline without replaying 180 identical expensive
    # vision passes; every supplied frame remains the real ambiguous loader.
    monkeypatch.setattr(module.time, "sleep", lambda seconds: setattr(clock, "now", clock.now + 30.0))
    runner = runner_for(repeat(loading()), tmp_path, clock)
    runner._recover_app("post-result relaunch", emote())
    with pytest.raises(RecoveryExhausted, match="90秒"):
        runner._startup_frame()
    assert clock.now == 590.0
    assert runner._awaiting_relaunch_observation
    assert runner.recovery_attempts == 2
    runner._tap.assert_not_called()
    preserved(runner)


def test_user_stop_during_relaunch_observation_prevents_loading_input(tmp_path, clock):
    runner = runner_for([loading()], tmp_path, clock)
    runner._recover_app("post-result relaunch", emote())
    runner.stop_path.write_text("stop", encoding="utf-8")
    with pytest.raises(KeyboardInterrupt):
        runner._startup_frame()
    runner._capture_frame.assert_not_called()
    runner._tap.assert_not_called()
    preserved(runner)
