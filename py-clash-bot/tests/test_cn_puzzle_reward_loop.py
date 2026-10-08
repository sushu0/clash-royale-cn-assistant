"""Observed post-battle puzzle stages preserve their original game-cycle receipt."""

from itertools import chain, repeat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import pytest

from pyclashbot.bot import cn_random_mastery_loop as module
from pyclashbot.bot.cn_1v1_loop import ChineseVision, RecoveryExhausted
from pyclashbot.bot.cn_random_mastery_loop import RandomMasteryLoop
from pyclashbot.detection.cn_puzzle_reward import puzzle_reward_action
from pyclashbot.emulators.base import CLASH_ROYALE_PACKAGE

FIXTURES = Path(__file__).with_name("fixtures")


def image(name):
    frame = cv2.imread(str(FIXTURES / name))
    assert frame is not None, name
    return frame


def opened(name="puzzle_open_20261007.png"):
    return image(f"cn_puzzle_reward/{name}")


def revealed():
    return image("cn_puzzle_reward/puzzle_reveal_20261007.png")


def lobby():
    return image("cn_pre_match/failed_lobby_20261006.png")


@pytest.fixture
def clock(monkeypatch):
    now = SimpleNamespace(value=100.0)
    monkeypatch.setattr(module.time, "monotonic", lambda: now.value)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: setattr(now, "value", now.value + seconds))
    return now


def runner_for(snapshots, tmp_path, clock):
    runner = RandomMasteryLoop.__new__(RandomMasteryLoop)
    runner._frame = Mock(side_effect=snapshots)
    runner._capture_frame = Mock()
    runner.stop_path = tmp_path / "STOP"
    runner.work = tmp_path
    runner.vision = ChineseVision()
    runner.device = SimpleNamespace(
        click=Mock(), adb=Mock(), start_app=Mock(), foreground_package=Mock(return_value=CLASH_ROYALE_PACKAGE)
    )
    runner.logger, runner._event, runner._save = Mock(), Mock(), Mock(return_value={"fixture": True})
    runner._tap = Mock(side_effect=lambda point, seconds: setattr(clock, "value", clock.value + seconds))
    runner._checkpoint, runner._recover_app = Mock(), Mock(side_effect=AssertionError("No extra app recovery"))
    runner.pending_mastery, runner.pending_claim_all, runner.pending_battle = True, False, False
    runner.completed, runner.closed_loops, runner.generated = 1841, 1840, 1855
    runner.total_claimed = 205
    runner.reward_claim_id = "original-claim-id"
    runner.reward_receipts = [{"id": "original-claim-id", "kind": "coins", "amount": 4000}]
    runner.recovery_attempts = 1
    runner.state = "returning"
    return runner


def preserved(runner):
    assert (runner.completed, runner.closed_loops, runner.generated, runner.total_claimed) == (1841, 1840, 1855, 205)
    assert runner.pending_mastery and not runner.pending_claim_all and not runner.pending_battle
    assert runner.reward_claim_id == "original-claim-id"
    assert runner.reward_receipts == [{"id": "original-claim-id", "kind": "coins", "amount": 4000}]
    assert runner.recovery_attempts == 1
    runner._checkpoint.assert_not_called()
    runner._recover_app.assert_not_called()
    runner.device.click.assert_not_called()
    runner.device.adb.assert_not_called()
    runner.device.start_app.assert_not_called()


@pytest.mark.parametrize("name", ["puzzle_open_20261007.png", "puzzle_open_phase2_20261007.png"])
def test_real_open_and_reveal_continue_to_stable_lobby_without_changing_counts(name, tmp_path, clock):
    entry, reveal, fresh = opened(name), revealed(), lobby()
    runner = runner_for(chain([entry, reveal], repeat(fresh)), tmp_path, clock)
    runner._return_from_result(allow_restart=False)
    entry_action = puzzle_reward_action(entry)
    reveal_action = puzzle_reward_action(reveal)
    assert entry_action is not None
    assert reveal_action is not None
    assert [call.args for call in runner._tap.call_args_list] == [
        (entry_action[1], 3),
        (reveal_action[1], 3),
    ]
    events = [call for call in runner._event.call_args_list if call.args == ("post_battle_puzzle_reward",)]
    assert [call.kwargs["tap"] for call in events] == [1, 2]
    assert runner._event.call_args.args == ("returned_lobby",)
    preserved(runner)


@pytest.mark.parametrize("source", [opened, revealed])
def test_startup_recognizes_exact_owned_panel_but_never_taps_it(source, tmp_path, clock):
    current = source()
    runner = runner_for([current], tmp_path, clock)
    runner._awaiting_relaunch_observation = True
    assert runner._startup_frame() is current
    runner._tap.assert_not_called()
    assert not runner._awaiting_relaunch_observation
    preserved(runner)


def test_relaunch_blue_and_black_only_observe_until_a_real_owned_panel(tmp_path, clock):
    blue = image("cn_daily_gift/loading_after_relaunch_20261006.png")
    black = image("cn_daily_gift/black_daily_timeout_20261006.png")
    current = opened()
    runner = runner_for([blue, black, current], tmp_path, clock)
    runner._awaiting_relaunch_observation = True
    assert runner._startup_frame() is current
    assert runner._frame.call_count == 3
    runner._tap.assert_not_called()
    preserved(runner)


@pytest.mark.parametrize("blocked", ["unowned", "pending_claim_all", "pending_battle", "foreign_app"])
def test_blocked_panel_cannot_mark_a_relaunch_ready(blocked, tmp_path, clock, monkeypatch):
    runner = runner_for(repeat(opened()), tmp_path, clock)
    runner._awaiting_relaunch_observation = True
    if blocked == "unowned":
        runner.pending_mastery = False
    elif blocked == "foreign_app":
        runner.device.foreground_package.return_value = "com.example.foreign"
    else:
        setattr(runner, blocked, True)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: setattr(clock, "value", clock.value + 30))
    with pytest.raises(RecoveryExhausted, match="90秒"):
        runner._startup_frame()
    runner._tap.assert_not_called()
    runner._checkpoint.assert_not_called()
    assert runner._awaiting_relaunch_observation
    assert (runner.completed, runner.closed_loops) == (1841, 1840)


def test_run_forever_routes_real_startup_panel_through_return_then_pending_mastery(tmp_path, clock):
    entry, reveal, fresh = opened(), revealed(), lobby()
    runner = runner_for(chain([entry, entry, reveal], repeat(fresh)), tmp_path, clock)
    runner._awaiting_relaunch_observation = True
    order = []
    original_return = runner._return_from_result
    runner._return_from_result = Mock(side_effect=lambda: order.append("return-rewards") or original_return())
    runner._prepare_classic_lobby = Mock(side_effect=lambda *args, **kwargs: order.append("verify-menu") or fresh)
    runner._navigate = Mock(side_effect=lambda *args: order.append("navigate-to-deck"))
    runner._require = Mock(side_effect=lambda name: order.append(f"require-{name}"))
    runner._mastery = Mock(side_effect=lambda: order.append("resume-mastery"))
    runner._new_deck = Mock(side_effect=KeyboardInterrupt)
    with pytest.raises(KeyboardInterrupt):
        runner.run_forever()
    assert order == ["return-rewards", "verify-menu", "navigate-to-deck", "require-deck", "resume-mastery"]
    assert runner._tap.call_count == 2
    assert any(call.args == ("resume_pending_mastery",) for call in runner._event.call_args_list)
    assert any(call.args == ("cycle_complete",) and call.kwargs.get("resumed") for call in runner._event.call_args_list)
    assert runner.completed == 1841 and runner.closed_loops == 1841 and runner.generated == 1855
    assert not runner.pending_mastery
    runner._checkpoint.assert_called_once()
    runner._recover_app.assert_not_called()


@pytest.mark.parametrize("blocked", ["unowned", "pending_claim_all", "pending_battle", "foreign_app"])
def test_owned_context_and_foreground_are_required_for_the_exact_panel(blocked, tmp_path, clock):
    runner = runner_for([], tmp_path, clock)
    if blocked == "unowned":
        runner.pending_mastery = False
    elif blocked == "foreign_app":
        runner.device.foreground_package.return_value = "com.example.foreign"
    else:
        setattr(runner, blocked, True)
    assert runner._post_battle_puzzle_action(opened()) is None
    assert runner._post_battle_puzzle_action(revealed()) is None
    runner._tap.assert_not_called()
    runner._checkpoint.assert_not_called()
    assert runner.completed == 1841 and runner.closed_loops == 1840


@pytest.mark.parametrize("blocked", ["unowned", "pending_claim_all", "pending_battle", "foreign_app"])
def test_blocked_panels_never_click_even_through_the_return_loop(blocked, tmp_path, clock, monkeypatch):
    runner = runner_for(repeat(opened()), tmp_path, clock)
    if blocked == "unowned":
        runner.pending_mastery = False
    elif blocked == "foreign_app":
        runner.device.foreground_package.return_value = "com.example.foreign"
    else:
        setattr(runner, blocked, True)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: setattr(clock, "value", clock.value + 30))
    with pytest.raises(RecoveryExhausted):
        runner._return_from_result(allow_restart=False)
    runner._tap.assert_not_called()
    runner._checkpoint.assert_not_called()
    runner._recover_app.assert_not_called()
    assert runner.completed == 1841 and runner.closed_loops == 1840


def test_forty_reward_inputs_remain_the_hard_cap(tmp_path, clock):
    runner = runner_for(repeat(opened()), tmp_path, clock)
    runner._tap.side_effect = None
    with pytest.raises(RecoveryExhausted, match="步骤超过上限"):
        runner._return_from_result(allow_restart=False)
    assert runner._tap.call_count == 40
    assert len([call for call in runner._event.call_args_list if call.args == ("post_battle_puzzle_reward",)]) == 40
    preserved(runner)


def test_unknown_black_frame_exhausts_original_120_seconds_without_input(tmp_path, clock, monkeypatch):
    unknown = image("cn_daily_gift/black_daily_timeout_20261006.png")
    runner = runner_for(repeat(unknown), tmp_path, clock)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: setattr(clock, "value", clock.value + 30))
    with pytest.raises(RecoveryExhausted, match="未返回大厅"):
        runner._return_from_result(allow_restart=False)
    assert clock.value == 220.0
    runner._tap.assert_not_called()
    preserved(runner)


def test_slow_foreground_read_does_not_authorize_a_tap_after_120_seconds(tmp_path, clock):
    runner = runner_for([opened()], tmp_path, clock)

    def slow_foreground():
        clock.value += 121
        return CLASH_ROYALE_PACKAGE

    runner.device.foreground_package.side_effect = slow_foreground
    with pytest.raises(RecoveryExhausted):
        runner._return_from_result(allow_restart=False)
    runner._tap.assert_not_called()
    assert clock.value == 221.0
    preserved(runner)


def test_slow_evidence_can_be_recorded_but_cannot_borrow_another_120_seconds(tmp_path, clock):
    runner = runner_for([opened()], tmp_path, clock)

    def slow_save(label, source):
        clock.value += 121
        return {"fixture": True}

    runner._save.side_effect = slow_save
    with pytest.raises(RecoveryExhausted):
        runner._return_from_result(allow_restart=False)
    runner._tap.assert_not_called()
    assert runner._event.call_args.args == ("post_battle_puzzle_reward",)
    preserved(runner)


def test_user_stop_after_evidence_uses_the_existing_tap_gate(tmp_path, clock):
    runner = runner_for([opened()], tmp_path, clock)
    runner._tap = RandomMasteryLoop._tap.__get__(runner)

    def stop(label, source):
        runner.stop_path.write_text("stop", encoding="utf-8")
        return {"fixture": True}

    runner._save.side_effect = stop
    with pytest.raises(KeyboardInterrupt):
        runner._return_from_result(allow_restart=False)
    preserved(runner)


def test_user_stop_before_capture_never_reads_or_taps_the_panel(tmp_path, clock):
    runner = runner_for([], tmp_path, clock)
    runner._frame = RandomMasteryLoop._frame.__get__(runner)
    runner.stop_path.write_text("stop", encoding="utf-8")
    with pytest.raises(KeyboardInterrupt):
        runner._return_from_result(allow_restart=False)
    runner._capture_frame.assert_not_called()
    runner._tap.assert_not_called()
    preserved(runner)
