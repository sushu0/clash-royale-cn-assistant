"""A fresh pre-match observation cannot send input or borrow a reward context."""

from itertools import repeat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from pyclashbot.bot import cn_random_mastery_loop as module
from pyclashbot.bot.cn_1v1_loop import ChineseVision, RecoveryExhausted
from pyclashbot.bot.cn_random_mastery_loop import RandomMasteryLoop
from pyclashbot.emulators.base import CLASH_ROYALE_PACKAGE

FIXTURES = Path(__file__).with_name("fixtures")


def frame(name="cn_pre_match/failed_lobby_20261006.png"):
    result = cv2.imread(str(FIXTURES / name))
    assert result is not None, name
    return result


@pytest.fixture
def clock(monkeypatch):
    current = SimpleNamespace(now=100.0)
    monkeypatch.setattr(module.time, "monotonic", lambda: current.now)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: setattr(current, "now", current.now + seconds))
    return current


def runner_for(snapshots, tmp_path, clock):
    snapshots = iter(snapshots)
    runner = RandomMasteryLoop.__new__(RandomMasteryLoop)
    runner.stop_path = tmp_path / "STOP"
    runner.vision = ChineseVision()
    runner._classic_menu_verified = True
    runner.pending_battle = runner.pending_mastery = runner.pending_claim_all = False
    runner.state = "generating_deck"
    runner.completed, runner.generated, runner.closed_loops = 1731, 1745, 1731
    runner.card_attempts, runner.cards_confirmed, runner.recovery_attempts = 7, 8, 2
    runner._event, runner._save = Mock(), Mock(return_value={"fixture": True})
    runner._tap, runner._checkpoint, runner._frame, runner._prepare_classic_lobby = Mock(), Mock(), Mock(), Mock()
    runner._use_recovery = Mock(side_effect=AssertionError("Pure observation cannot recover/reconnect"))
    reads = []

    def adb(command, *, binary_output=False, timeout):
        assert 0 < timeout <= 3
        reads.append((command, timeout))
        if command == "exec-out screencap -p":
            source = next(snapshots)
            if isinstance(source, BaseException):
                raise source
            ok, png = cv2.imencode(".png", source)
            assert ok and binary_output
            return SimpleNamespace(returncode=0, stdout=png.tobytes())
        assert command in ("shell dumpsys window", "shell dumpsys activity activities")
        return SimpleNamespace(returncode=0, stdout=f"mCurrentFocus Window{{ {runner.foreground}/Activity }}")

    runner.foreground = CLASH_ROYALE_PACKAGE
    runner.device = SimpleNamespace(adb=Mock(side_effect=adb), click=Mock(), start_app=Mock())
    runner.reads = reads
    return runner


def no_submission(runner):
    runner._tap.assert_not_called()
    runner._checkpoint.assert_not_called()
    runner._frame.assert_not_called()
    runner._prepare_classic_lobby.assert_not_called()
    runner._use_recovery.assert_not_called()
    runner.device.click.assert_not_called()
    runner.device.start_app.assert_not_called()
    assert not runner.pending_battle
    assert (runner.completed, runner.generated, runner.closed_loops, runner.recovery_attempts) == (1731, 1745, 1731, 2)


def test_unknown_transition_then_two_ready_frames_submits_only_the_latest_match(tmp_path, clock):
    unknown = np.zeros((633, 419, 3), np.uint8)
    good = frame()
    runner = runner_for([unknown, good, good], tmp_path, clock)
    order = []
    runner._checkpoint.side_effect = lambda: order.append(("checkpoint", clock.now))

    def stop_after_submit(point, delay):
        order.append(("tap", clock.now))
        raise KeyboardInterrupt

    runner._tap.side_effect = stop_after_submit
    with pytest.raises(KeyboardInterrupt):
        runner._battle()
    assert [row[0] for row in order] == ["checkpoint", "tap"]
    assert [row[1] for row in order] == pytest.approx([100.4, 100.4])
    assert runner.pending_battle
    runner._frame.assert_not_called()
    runner._prepare_classic_lobby.assert_not_called()
    assert [call.args[0] for call in runner._event.call_args_list] == ["match_requested"]


def test_continuous_unknown_exhausts_one_deadline_without_input_or_recovery(tmp_path, clock):
    runner = runner_for(repeat(np.zeros((633, 419, 3), np.uint8)), tmp_path, clock)
    with pytest.raises(RecoveryExhausted, match="未提交匹配"):
        runner._battle()
    assert clock.now == pytest.approx(103.0)
    no_submission(runner)
    event = runner._event.call_args
    assert event.args == ("pre_match_rejected",)
    assert event.kwargs["kind"] == "unknown"
    assert event.kwargs["has_match"] is False
    runner._save.assert_called_once()
    assert runner._save.call_args.args[0] == "mismatch"


@pytest.mark.parametrize(
    "name",
    [
        "cn_567/classic2v2_lobby.png",
        "cn_random_hand/live_hand_0.png",
        "cn_results/win_two_zero.png",
        "cn_shop_daily/live-gem-confirm.png",
        "cn_shop_daily/live-gold-confirm.png",
        "cn_shop_daily/live-free-reward-1.png",
        "cn_pages/king_skin_promotion_20261006.png",
        "cn_daily_gift/daily_gift_choice_20261004.png",
        "cn_rewards/four_star_chest.png",
        "cn_rewards/four_star_card.png",
    ],
)
def test_recognized_foreign_modes_pages_payments_and_rewards_get_no_input(name, tmp_path, clock):
    runner = runner_for(repeat(frame(name)), tmp_path, clock)
    with pytest.raises(RecoveryExhausted):
        runner._battle()
    no_submission(runner)
    assert runner._event.call_args.args == ("pre_match_rejected",)


def test_foreign_app_rejects_even_a_valid_classic_frame(tmp_path, clock):
    runner = runner_for([frame()], tmp_path, clock)
    runner.foreground = "com.example.foreign"
    with pytest.raises(RecoveryExhausted):
        runner._battle()
    no_submission(runner)
    assert runner._event.call_args.kwargs["eligible_reason"] == "foreign_app"


def test_foreign_app_cannot_open_the_first_unverified_mode_menu(tmp_path, clock):
    runner = runner_for([frame()], tmp_path, clock)
    runner._classic_menu_verified = False
    runner.foreground = "com.example.foreign"
    with pytest.raises(RecoveryExhausted):
        runner._battle()
    no_submission(runner)
    assert runner._event.call_args.kwargs["eligible_reason"] == "foreign_app"


def test_real_loading_still_gets_observation_only_before_two_known_lobbies(tmp_path, clock):
    blue = frame("cn_daily_gift/loading_after_relaunch_20261006.png")
    assert ChineseVision().reward_continuation(blue)
    runner = runner_for([blue, frame(), frame()], tmp_path, clock)
    runner._tap.side_effect = KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        runner._battle()
    assert runner.pending_battle
    runner._frame.assert_not_called()
    assert clock.now == pytest.approx(100.4)


def test_first_causal_menu_verification_is_still_required(tmp_path, clock):
    runner = runner_for([frame(), frame()], tmp_path, clock)
    runner._classic_menu_verified = False

    def causal(*args, **kwargs):
        assert kwargs == {"verify_menu": True}
        runner._classic_menu_verified = True
        return frame()

    runner._prepare_classic_lobby.side_effect = causal
    runner._tap.side_effect = KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        runner._battle()
    runner._prepare_classic_lobby.assert_called_once()
    assert runner.pending_battle


def test_stop_after_final_availability_prevents_checkpoint_and_tap(tmp_path, clock):
    runner = runner_for([frame(), frame()], tmp_path, clock)

    def stop_before_commit(source):
        runner.stop_path.write_text("stop", encoding="utf-8")
        return source, runner.vision.classify(source)[1]

    runner._wait_for_lobby_start = Mock(side_effect=stop_before_commit)
    with pytest.raises(KeyboardInterrupt):
        runner._battle()
    no_submission(runner)


def test_relaunch_inside_availability_wait_cannot_borrow_the_previous_menu_verification(tmp_path, clock):
    runner = runner_for([frame(), frame()], tmp_path, clock)

    def changed_context(source):
        runner._classic_menu_verified = False
        return source, runner.vision.classify(source)[1]

    runner._wait_for_lobby_start = Mock(side_effect=changed_context)
    with pytest.raises(RecoveryExhausted):
        runner._battle()
    no_submission(runner)
    event = runner._event.call_args
    assert event.args == ("pre_match_rejected",)
    assert event.kwargs["eligible_reason"] == "context_changed_before_commit"
    assert event.kwargs["menu_verified"] is False
    assert event.kwargs["classic_selected"] is True
    assert event.kwargs["availability"] == "ready"


@pytest.mark.parametrize("flag", ["pending_battle", "pending_mastery", "pending_claim_all"])
def test_a_new_transaction_during_availability_wait_cannot_be_overwritten(flag, tmp_path, clock):
    runner = runner_for([frame(), frame()], tmp_path, clock)

    def changed_context(source):
        setattr(runner, flag, True)
        return source, runner.vision.classify(source)[1]

    runner._wait_for_lobby_start = Mock(side_effect=changed_context)
    with pytest.raises(RecoveryExhausted):
        runner._battle()
    runner._tap.assert_not_called()
    runner._checkpoint.assert_not_called()
    assert getattr(runner, flag) is True
    assert runner._event.call_args.kwargs["eligible_reason"] == "context_changed_before_commit"
    assert runner._event.call_args.kwargs[flag] is True
    assert (runner.completed, runner.closed_loops) == (1731, 1731)


@pytest.mark.parametrize("flag", ["pending_battle", "pending_mastery", "pending_claim_all"])
@pytest.mark.parametrize("menu_verified", [False, True])
def test_formal_pending_transaction_cannot_authorize_preflight(flag, menu_verified, tmp_path, clock):
    runner = runner_for([frame()], tmp_path, clock)
    runner._classic_menu_verified = menu_verified
    setattr(runner, flag, True)
    with pytest.raises(RecoveryExhausted):
        runner._battle()
    assert getattr(runner, flag)
    runner._tap.assert_not_called()
    runner._checkpoint.assert_not_called()
    runner._prepare_classic_lobby.assert_not_called()
    runner.device.adb.assert_not_called()


def test_disabled_frames_have_to_agree_then_use_the_separate_availability_gate(tmp_path, clock):
    disabled = frame("cn_lobby_availability/disabled_before_match.png")
    good = frame()
    runner = runner_for([disabled, disabled], tmp_path, clock)
    result = runner._preflight_classic_lobby(good, deadline=103.0)
    assert result[0] is not good
    assert runner.vision.lobby_start_state(result[0]) == "disabled"
    assert clock.now == pytest.approx(100.4)
    no_submission(runner)


def test_stop_before_and_after_capture_prevents_any_commit(tmp_path, clock):
    runner = runner_for([frame()], tmp_path, clock)
    original = runner.device.adb.side_effect

    def stop_after_read(*args, **kwargs):
        result = original(*args, **kwargs)
        runner.stop_path.write_text("stop", encoding="utf-8")
        return result

    runner.device.adb.side_effect = stop_after_read
    with pytest.raises(KeyboardInterrupt):
        runner._battle()
    no_submission(runner)


def test_slow_read_that_consumes_the_budget_cannot_become_ready(tmp_path, clock):
    runner = runner_for([frame()], tmp_path, clock)
    original = runner.device.adb.side_effect

    def slow(*args, **kwargs):
        result = original(*args, **kwargs)
        clock.now += 3.0
        return result

    runner.device.adb.side_effect = slow
    with pytest.raises(RecoveryExhausted):
        runner._battle()
    no_submission(runner)
    assert runner._event.call_args.kwargs["eligible_reason"] == "capture_failed:TimeoutError"


def test_menu_unverified_cannot_be_replaced_by_two_lobby_frames(tmp_path, clock):
    runner = runner_for([frame()], tmp_path, clock)
    runner._classic_menu_verified = False
    with pytest.raises(RecoveryExhausted):
        runner._preflight_classic_lobby(frame(), deadline=103.0)
    no_submission(runner)
    assert runner._event.call_args.kwargs["eligible_reason"] == "menu_unverified"
