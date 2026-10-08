"""Unavailable lobby buttons cannot create a submitted-match checkpoint."""

from itertools import repeat
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from pyclashbot.bot import cn_random_mastery_loop as module
from pyclashbot.bot.cn_1v1_loop import RecoveryExhausted
from pyclashbot.bot.cn_random_mastery_loop import RandomMasteryLoop


@pytest.fixture
def clock(monkeypatch):
    current = SimpleNamespace(now=100.0)
    monkeypatch.setattr(module.time, "monotonic", lambda: current.now)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: setattr(current, "now", current.now + seconds))
    monkeypatch.setattr(module, "LOBBY_START_WAIT_SECONDS", 6.0)
    monkeypatch.setattr(module, "LOBBY_START_POLL_SECONDS", 2.0)
    monkeypatch.setattr(module, "LOBBY_START_REPORT_SECONDS", 2.0)
    return current


def runner_for(snapshots):
    runner = RandomMasteryLoop.__new__(RandomMasteryLoop)
    runner.pending_battle = runner.pending_mastery = runner.pending_claim_all = False
    runner._classic_menu_verified = True
    runner.completed, runner.generated, runner.closed_loops = 1380, 1392, 1380
    runner.cards_confirmed, runner.card_attempts = 27, 28
    runner.recovery_attempts = 2
    runner.state = "matching"
    runner.strategy_reason = "previous-battle-reason"
    runner.logger = Mock()
    runner._event, runner._save, runner._tap, runner._checkpoint = Mock(), Mock(), Mock(), Mock()
    runner._prepare_classic_lobby = Mock()
    runner._reset_battle_frame_monitor = Mock()
    runner._save.return_value = {"fixture": True}
    runner._frame = Mock(side_effect=snapshots)

    def label(frame):
        return runner._preflight_label if isinstance(frame, np.ndarray) else frame

    def raw_capture(deadline):
        runner._preflight_label = runner._frame()
        return np.zeros((633, 419, 3), np.uint8)

    runner._preflight_capture = Mock(side_effect=raw_capture)
    runner._preflight_classic_lobby = Mock(
        side_effect=lambda frame, **_: (label(frame), runner.vision.classify(frame)[1])
    )
    runner.stop_path = SimpleNamespace(exists=lambda: False)
    runner.vision = SimpleNamespace(
        classify=Mock(
            side_effect=lambda frame: (
                ("lobby", SimpleNamespace(center=f"{frame}-center"))
                if frame in ("disabled", "ready", "unknown", "wrong-mode")
                else (frame, None)
            )
        ),
        classic_selected=Mock(side_effect=lambda frame: frame != "wrong-mode"),
        lobby_start_state=Mock(side_effect=lambda frame: frame),
    )
    classify, classic, availability = (
        runner.vision.classify.side_effect,
        runner.vision.classic_selected.side_effect,
        runner.vision.lobby_start_state.side_effect,
    )
    runner.vision.classify.side_effect = lambda frame: classify(label(frame))
    runner.vision.classic_selected.side_effect = lambda frame: classic(label(frame))
    runner.vision.lobby_start_state.side_effect = lambda frame: availability(label(frame))
    return runner


def assert_no_submission(runner):
    runner._tap.assert_not_called()
    runner._checkpoint.assert_not_called()
    assert not runner.pending_battle
    assert (runner.completed, runner.generated, runner.closed_loops) == (1380, 1392, 1380)
    assert (runner.cards_confirmed, runner.card_attempts) == (27, 28)
    assert runner.recovery_attempts == 2
    assert all(call.args[0] != "match_requested" for call in runner._event.call_args_list)


def test_disabled_timeout_never_submits_a_match_or_changes_counts(clock):
    runner = runner_for(repeat("disabled"))
    with pytest.raises(RecoveryExhausted, match="未提交匹配"):
        runner._battle()
    assert_no_submission(runner)
    assert clock.now == 106.0
    assert runner._frame.call_count == 4
    assert "等待开放" in runner.strategy_reason
    assert [call.args[0] for call in runner._event.call_args_list] == [
        "lobby_start_unavailable",
        "lobby_start_waiting",
        "lobby_start_waiting",
    ]


def test_disabled_then_ready_submits_only_the_fresh_ready_match(clock):
    runner = runner_for(["disabled", "disabled", "ready"])
    order = []
    runner._checkpoint.side_effect = lambda: order.append(("checkpoint", clock.now))

    def stop_after_tap(point, delay):
        order.append(("tap", clock.now, point, delay))
        raise KeyboardInterrupt

    runner._tap.side_effect = stop_after_tap
    with pytest.raises(KeyboardInterrupt):
        runner._battle()
    assert order == [("checkpoint", 104.0), ("tap", 104.0, "ready-center", 0.5)]
    assert runner.pending_battle
    assert runner._checkpoint.call_count == 1
    assert [call.args[0] for call in runner._event.call_args_list] == [
        "lobby_start_unavailable",
        "lobby_start_waiting",
        "lobby_start_available",
        "match_requested",
    ]
    assert (runner.completed, runner.generated, runner.closed_loops) == (1380, 1392, 1380)


def test_ready_lobby_does_not_wait_or_reuse_an_old_match_center(clock):
    runner = runner_for(["ready"])
    runner._tap.side_effect = KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        runner._battle()
    runner._tap.assert_called_once_with("ready-center", 0.5)
    assert runner.pending_battle and clock.now == 100.0
    assert [call.args[0] for call in runner._event.call_args_list] == ["match_requested"]


@pytest.mark.parametrize("following", ["unknown", "battle", "result", "reward", "navigation", "wrong-mode"])
def test_disabled_wait_cannot_click_an_unverified_or_foreign_page(following, clock):
    runner = runner_for(["disabled", following])
    with pytest.raises(RecoveryExhausted, match="未提交匹配"):
        runner._battle()
    assert_no_submission(runner)


def test_missing_availability_helper_fails_closed(clock):
    runner = runner_for(["ready"])
    del runner.vision.lobby_start_state
    with pytest.raises(RecoveryExhausted, match="可用性检测未就绪"):
        runner._battle()
    assert_no_submission(runner)


@pytest.mark.parametrize("flag", ["pending_battle", "pending_mastery", "pending_claim_all"])
def test_unclosed_checkpoint_is_preserved_before_availability_wait(flag, clock):
    runner = runner_for([])
    setattr(runner, flag, True)
    with pytest.raises(RecoveryExhausted, match="断点尚未闭合"):
        runner._wait_for_lobby_start("disabled")
    assert getattr(runner, flag) is True
    runner._checkpoint.assert_not_called()
    runner._tap.assert_not_called()
    runner._frame.assert_not_called()
    assert runner.completed == 1380


def test_existing_owned_battle_resume_never_checks_or_waits_for_lobby_button(clock):
    runner = runner_for(["battle", KeyboardInterrupt])
    runner.pending_battle = True
    with pytest.raises(KeyboardInterrupt):
        runner._battle(resumed=True)
    runner.vision.lobby_start_state.assert_not_called()
    runner._tap.assert_not_called()
    runner._checkpoint.assert_not_called()
    assert runner.pending_battle and runner.completed == 1380
