"""Legendary-background reveals preserve the completed battle's original receipt."""

from itertools import chain, repeat
from unittest.mock import Mock

import numpy as np
import pytest

from pyclashbot.bot import cn_random_mastery_loop as module
from pyclashbot.bot.cn_1v1_loop import RecoveryExhausted
from pyclashbot.bot.cn_random_mastery_loop import RandomMasteryLoop
from pyclashbot.bot.coords import CN_PUZZLE_REWARD_ROIS
from pyclashbot.detection.cn_puzzle_reward import puzzle_reward_action
from pyclashbot.emulators.base import CLASH_ROYALE_PACKAGE
from tests import test_cn_puzzle_reward_loop as helpers

POSITIVES = (
    "puzzle_reveal_legendary_20261007.png",
    "puzzle_reveal_legendary_before_relaunch_20261007.png",
    "puzzle_reveal_legendary_current_20261007.png",
)


@pytest.fixture
def clock(monkeypatch):
    return getattr(helpers.clock, "__wrapped__")(monkeypatch)


def legendary(name=POSITIVES[0]):
    return helpers.image(f"cn_puzzle_reward/{name}")


def runner_for(snapshots, tmp_path, clock):
    runner = helpers.runner_for(snapshots, tmp_path, clock)
    runner.completed, runner.closed_loops, runner.generated = 1846, 1845, 1860
    return runner


def preserved(runner):
    assert (runner.completed, runner.closed_loops, runner.generated, runner.total_claimed) == (1846, 1845, 1860, 205)
    assert runner.pending_mastery and not runner.pending_battle and not runner.pending_claim_all
    assert runner.reward_claim_id == "original-claim-id"
    assert runner.reward_receipts == [{"id": "original-claim-id", "kind": "coins", "amount": 4000}]
    assert runner.recovery_attempts == 1
    runner._checkpoint.assert_not_called()
    runner._recover_app.assert_not_called()
    runner.device.click.assert_not_called()
    runner.device.adb.assert_not_called()
    runner.device.start_app.assert_not_called()


@pytest.mark.parametrize("name", POSITIVES)
def test_real_legendary_reveal_is_owned_and_returns_to_stable_lobby(name, tmp_path, clock):
    reveal, fresh = legendary(name), helpers.lobby()
    action = puzzle_reward_action(reveal)
    assert action is not None and action[0] == "continue_puzzle_reward"
    runner = runner_for(chain([reveal], repeat(fresh)), tmp_path, clock)
    runner._return_from_result(allow_restart=False)
    runner._tap.assert_called_once_with(action[1], 3)
    assert runner._event.call_args.args == ("returned_lobby",)
    preserved(runner)


@pytest.mark.parametrize("name", POSITIVES)
def test_exact_legendary_startup_is_observation_only(name, tmp_path, clock):
    reveal = legendary(name)
    runner = runner_for([reveal], tmp_path, clock)
    runner._awaiting_relaunch_observation = True
    assert runner._startup_frame() is reveal
    runner._tap.assert_not_called()
    preserved(runner)


def test_real_run_entry_routes_legendary_to_old_mastery_then_next_battle_boundary(tmp_path, clock):
    reveal, fresh = legendary(), helpers.lobby()
    runner = runner_for(chain([reveal, reveal], repeat(fresh)), tmp_path, clock)
    runner._awaiting_relaunch_observation = True
    order = []
    original = runner._return_from_result
    runner._return_from_result = Mock(side_effect=lambda: order.append("return-legendary") or original())
    runner._prepare_classic_lobby = Mock(return_value=fresh)
    runner._navigate = Mock()
    runner._require = Mock()
    runner._mastery = Mock(side_effect=lambda: order.append("resume-master1846"))

    def next_battle_boundary():
        assert runner.completed == 1846 and runner.closed_loops == 1846
        assert not runner.pending_mastery
        order.append("prepare-next1847")
        raise KeyboardInterrupt

    runner._new_deck = Mock(side_effect=next_battle_boundary)
    with pytest.raises(KeyboardInterrupt):
        runner.run_forever()
    assert order == ["return-legendary", "resume-master1846", "prepare-next1847"]
    assert runner.completed == 1846 and runner.generated == 1860
    runner._checkpoint.assert_called_once()
    runner._recover_app.assert_not_called()
    action = puzzle_reward_action(reveal)
    assert action is not None
    runner._tap.assert_called_once_with(action[1], 3)
    assert any(call.args == ("cycle_complete",) and call.kwargs.get("resumed") for call in runner._event.call_args_list)


@pytest.mark.parametrize("blocked", ["unowned", "pending_claim_all", "pending_battle", "foreign_app"])
def test_transaction_or_foreign_context_does_not_authorize_legendary(blocked, tmp_path, clock, monkeypatch):
    runner = runner_for(repeat(legendary()), tmp_path, clock)
    if blocked == "unowned":
        runner.pending_mastery = False
    elif blocked == "foreign_app":
        runner.device.foreground_package.return_value = "com.example.foreign"
    else:
        setattr(runner, blocked, True)
    assert runner._post_battle_puzzle_action(legendary()) is None
    monkeypatch.setattr(module.time, "sleep", lambda seconds: setattr(clock, "value", clock.value + 30))
    with pytest.raises(RecoveryExhausted):
        runner._return_from_result(allow_restart=False)
    runner._tap.assert_not_called()
    runner._checkpoint.assert_not_called()
    runner._recover_app.assert_not_called()
    assert (runner.completed, runner.closed_loops) == (1846, 1845)


@pytest.mark.parametrize("cue", ["reveal_title", "reveal_unlocked"])
def test_missing_one_legendary_cue_does_not_allow_continue(cue, tmp_path, clock):
    reveal = legendary()
    x1, y1, x2, y2 = CN_PUZZLE_REWARD_ROIS[cue]
    reveal[y1:y2, x1:x2] = 0
    assert puzzle_reward_action(reveal) is None
    runner = runner_for([], tmp_path, clock)
    assert runner._post_battle_puzzle_action(reveal) is None
    runner._tap.assert_not_called()
    preserved(runner)


@pytest.mark.parametrize("factor", [0.0, 0.8, 0.9, 0.94])
def test_dimmed_legendary_panel_cannot_authorize_continue(factor, tmp_path, clock):
    reveal = (legendary().astype(np.float32) * factor).astype(np.uint8)
    assert puzzle_reward_action(reveal) is None
    runner = runner_for([], tmp_path, clock)
    assert runner._post_battle_puzzle_action(reveal) is None
    runner._tap.assert_not_called()
    preserved(runner)


def test_stop_before_capture_preserves_the_legendary_receipt(tmp_path, clock):
    runner = runner_for([], tmp_path, clock)
    runner._frame = RandomMasteryLoop._frame.__get__(runner)
    runner.stop_path.write_text("stop", encoding="utf-8")
    with pytest.raises(KeyboardInterrupt):
        runner._return_from_result(allow_restart=False)
    runner._capture_frame.assert_not_called()
    runner._tap.assert_not_called()
    preserved(runner)


def test_stop_after_evidence_preserves_the_legendary_receipt(tmp_path, clock):
    runner = runner_for([legendary()], tmp_path, clock)
    runner._tap = RandomMasteryLoop._tap.__get__(runner)

    def stop(label, source):
        runner.stop_path.write_text("stop", encoding="utf-8")
        return {"fixture": True}

    runner._save.side_effect = stop
    with pytest.raises(KeyboardInterrupt):
        runner._return_from_result(allow_restart=False)
    preserved(runner)


def test_legendary_still_cannot_exceed_forty_inputs(tmp_path, clock):
    runner = runner_for(repeat(legendary()), tmp_path, clock)
    runner._tap.side_effect = None
    with pytest.raises(RecoveryExhausted, match="步骤超过上限"):
        runner._return_from_result(allow_restart=False)
    assert runner._tap.call_count == 40
    preserved(runner)


def test_slow_legendary_foreground_read_cannot_borrow_a_fresh_120_seconds(tmp_path, clock):
    runner = runner_for([legendary()], tmp_path, clock)

    def slow():
        clock.value += 121
        return CLASH_ROYALE_PACKAGE

    runner.device.foreground_package.side_effect = slow
    with pytest.raises(RecoveryExhausted):
        runner._return_from_result(allow_restart=False)
    runner._tap.assert_not_called()
    assert clock.value == 221.0
    preserved(runner)


def test_unknown_120_second_timeout_does_not_clear_legendary_pending(tmp_path, clock, monkeypatch):
    unknown = helpers.image("cn_daily_gift/black_daily_timeout_20261006.png")
    runner = runner_for(repeat(unknown), tmp_path, clock)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: setattr(clock, "value", clock.value + 30))
    with pytest.raises(RecoveryExhausted):
        runner._return_from_result(allow_restart=False)
    assert clock.value == 220.0
    runner._tap.assert_not_called()
    preserved(runner)
