"""Offline safety boundaries for frozen frames, transport and game recovery."""

import hashlib
import logging
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from pyclashbot.bot import cn_random_mastery_loop as loop_module
from pyclashbot.bot.cn_1v1_loop import ChineseVision, RecoveryExhausted
from pyclashbot.bot.cn_random_mastery_loop import RandomMasteryLoop
from pyclashbot.emulators.adb_base import AdbBasedController
from pyclashbot.emulators.base import CLASH_ROYALE_PACKAGE


@pytest.fixture
def clock(monkeypatch):
    value = SimpleNamespace(now=0.0)
    monkeypatch.setattr(loop_module.time, "monotonic", lambda: value.now)
    monkeypatch.setattr(loop_module.time, "sleep", lambda seconds: setattr(value, "now", value.now + seconds))
    return value


@pytest.fixture
def runner(tmp_path, clock):
    value = RandomMasteryLoop.__new__(RandomMasteryLoop)
    value.stop_path = tmp_path / "STOP"
    value.work = tmp_path
    value.serial = "127.0.0.1:21503"
    value.logger = logging.getLogger("random-stability-test")
    value.completed = 10
    value.generated = 11
    value.closed_loops = 9
    value.total_claimed = 2
    value.consecutive = 3
    value.card_attempts = value.cards_confirmed = 7
    value.pending_battle = True
    value.pending_mastery = False
    value.pending_claim_all = False
    value.events = []
    value.taps = []
    value._event = lambda event, **values: value.events.append((event, values))
    value._save = lambda *args: {"fixture": "test-frame"}
    value._checkpoint = Mock()
    value._tap = lambda point, delay=0.65: (value.taps.append(point), loop_module.time.sleep(delay))
    value.device = SimpleNamespace(
        adb=Mock(return_value=subprocess.CompletedProcess([], 0, stdout="device", stderr="")),
        screenshot=Mock(return_value=np.indices((633, 419))[0].astype(np.uint8).repeat(3).reshape(633, 419, 3)),
        start_app=Mock(),
    )
    value.vision = SimpleNamespace(find=Mock(return_value=None), classify=Mock(return_value=("connection", None)))
    return value


def counters(runner):
    return (
        runner.completed,
        runner.generated,
        runner.closed_loops,
        runner.total_claimed,
        runner.card_attempts,
        runner.cards_confirmed,
        runner.pending_battle,
        runner.pending_mastery,
        runner.pending_claim_all,
    )


def test_exact_battle_frame_requires_full_45_seconds(runner):
    frame = np.zeros((10, 10, 3), np.uint8)
    assert not runner._battle_frame_stalled("battle", frame, 10)
    assert not runner._battle_frame_stalled("battle", frame, 54)
    assert runner._battle_frame_stalled("battle", frame, 55)


def test_entire_frame_change_resets_stall_timer(runner):
    frame = np.zeros((10, 10, 3), np.uint8)
    assert not runner._battle_frame_stalled("battle", frame, 0)
    frame[-1, -1, -1] = 1
    assert not runner._battle_frame_stalled("battle", frame, 30)
    assert not runner._battle_frame_stalled("battle", frame, 74)
    assert runner._battle_frame_stalled("battle", frame, 75)


@pytest.mark.parametrize("kind", ["lobby", "result", "reward", "unknown", "connection", "matching"])
def test_nonbattle_static_pages_reset_monitor_and_never_freeze(runner, kind):
    frame = np.zeros((10, 10, 3), np.uint8)
    runner._battle_frame_stalled("battle", frame, 0)
    assert not runner._battle_frame_stalled(kind, frame, 90)
    assert not runner._battle_frame_stalled(kind, frame, 900)
    assert not runner._battle_frame_stalled("battle", frame, 901)
    assert not runner._battle_frame_stalled("battle", frame, 945)
    assert runner._battle_frame_stalled("battle", frame, 946)


def test_hash_sampling_is_at_most_once_per_second(runner, monkeypatch):
    frame = np.zeros((10, 10, 3), np.uint8)
    digest = Mock(wraps=hashlib.sha256)
    monkeypatch.setattr(loop_module.hashlib, "sha256", digest)
    for now in (0, 0.12, 0.7, 0.99, 1, 1.12, 1.99, 2):
        runner._battle_frame_stalled("battle", frame, now)
    assert digest.call_count == 3


def test_transient_adb_timeout_reconnects_only_scoped_transport(runner):
    expected = runner.device.screenshot.return_value
    runner.device.screenshot.side_effect = [subprocess.TimeoutExpired("screencap", 30), expected]
    runner.device.adb.side_effect = [
        subprocess.CompletedProcess([], 1, stdout="offline"),
        subprocess.CompletedProcess([], 0, stdout="connected"),
    ]
    before = counters(runner)
    assert runner._frame() is expected
    assert [call.args[0] for call in runner.device.adb.call_args_list] == ["get-state", "connect 127.0.0.1:21503"]
    assert runner.recovery_attempts == 1
    assert counters(runner) == before
    runner.device.start_app.assert_not_called()
    assert runner.taps == []


def test_persistent_adb_failure_stops_after_three_recovery_attempts(runner):
    runner.device.screenshot.side_effect = RuntimeError("screencap failed")
    before = counters(runner)
    with pytest.raises(RecoveryExhausted, match="连续三次恢复"):
        runner._frame()
    assert runner.device.screenshot.call_count == 4
    assert runner.recovery_attempts == 3
    assert counters(runner) == before
    assert runner.taps == []


def test_connection_confirmation_is_reobserved_and_spends_budget(runner):
    popup = runner.device.screenshot.return_value
    fresh = popup.copy()
    runner.device.screenshot.side_effect = [popup, fresh]
    matches = iter([SimpleNamespace(center=(100, 200)), None])
    runner.vision.find.side_effect = lambda _frame, name: next(matches) if name == "connection_confirm" else None
    before = counters(runner)
    assert runner._frame() is fresh
    assert runner.taps == [(100, 200)]
    assert runner.recovery_attempts == 1
    assert counters(runner) == before
    runner.device.start_app.assert_not_called()


def test_unknown_page_never_authorizes_connection_input(runner):
    before = counters(runner)
    runner._frame()
    assert runner.taps == []
    assert counters(runner) == before
    assert runner.events == []


def test_reward_classification_takes_precedence_over_connection_template(runner):
    runner.vision.find.return_value = SimpleNamespace(center=(100, 200))
    runner.vision.classify.return_value = ("reward", None)
    runner._frame()
    assert runner.taps == []
    assert runner.events == []


def test_connection_recovery_never_exceeds_three_confirmed_taps(runner):
    runner.vision.find.return_value = SimpleNamespace(center=(100, 200))
    with pytest.raises(RecoveryExhausted, match="连续三次恢复"):
        runner._frame()
    assert runner.taps == [(100, 200)] * 3
    assert runner.recovery_attempts == 3


def test_app_restart_is_bounded_and_preserves_every_checkpoint_counter(runner):
    before = counters(runner)
    for _ in range(3):
        runner._recover_app("test freeze")
    with pytest.raises(RecoveryExhausted, match="连续三次恢复"):
        runner._recover_app("persistent freeze")
    assert runner.device.start_app.call_count == 3
    assert runner.device.adb.call_count == 3
    assert counters(runner) == before
    runner._checkpoint.assert_not_called()
    assert {call.args[0] for call in runner.device.adb.call_args_list} == {
        f"shell am force-stop {CLASH_ROYALE_PACKAGE}"
    }


def test_failed_force_stop_does_not_report_success_or_launch_again(runner):
    runner.device.adb.return_value = subprocess.CompletedProcess([], 1)
    before = counters(runner)
    with pytest.raises(RecoveryExhausted, match="游戏停止失败"):
        runner._recover_app("test freeze")
    runner.device.start_app.assert_not_called()
    assert counters(runner) == before


def configure_return(runner, clock, restarted_kind):
    runner.pending_battle = False
    runner.pending_mastery = True
    runner._startup_frame = Mock(return_value=restarted_kind)
    runner._frame = lambda: "unknown" if clock.now < 120 else restarted_kind
    runner.vision = SimpleNamespace(
        classify=lambda frame: (frame, None),
        reward_continuation=lambda _: False,
        find=lambda *args: None,
    )


def test_post_result_timeout_restarts_once_and_confirms_stable_lobby(runner, clock):
    configure_return(runner, clock, "lobby")
    before = counters(runner)
    runner._return_from_result()
    runner.device.start_app.assert_called_once_with(CLASH_ROYALE_PACKAGE)
    assert any(event == "returned_lobby" for event, _ in runner.events)
    assert clock.now >= 123
    assert counters(runner) == before
    assert runner.pending_mastery


def test_post_result_timeout_has_only_one_app_restart(runner, clock):
    configure_return(runner, clock, "result")
    before = counters(runner)
    with pytest.raises(RecoveryExhausted, match="未返回大厅"):
        runner._return_from_result()
    runner.device.start_app.assert_called_once()
    assert counters(runner) == before
    assert runner.taps == []  # no detected result button
    assert clock.now < 242


@pytest.mark.parametrize(("pending_mastery", "pending_claim_all"), [(False, False), (True, True)])
def test_return_timeout_cannot_restart_without_safe_post_battle_context(
    runner, clock, pending_mastery, pending_claim_all
):
    configure_return(runner, clock, "unknown")
    runner.pending_mastery = pending_mastery
    runner.pending_claim_all = pending_claim_all
    before = counters(runner)
    with pytest.raises(RecoveryExhausted, match="未返回大厅"):
        runner._return_from_result()
    runner.device.start_app.assert_not_called()
    assert counters(runner) == before
    assert runner.taps == []


def test_post_result_restart_cannot_take_over_unrelated_battle(runner, clock):
    configure_return(runner, clock, "battle")
    before = counters(runner)
    with pytest.raises(RecoveryExhausted, match="未确认大厅或本局奖励"):
        runner._return_from_result()
    runner.device.start_app.assert_called_once()
    assert counters(runner) == before
    assert runner.taps == []


@pytest.mark.parametrize("recovered_kind", ["lobby", "reward", "unknown"])
def test_frozen_battle_without_verified_result_never_increments_completed(runner, recovered_kind):
    frame = np.zeros((633, 419, 3), np.uint8)
    runner._frame = lambda: frame
    runner.vision.classify = lambda source: (recovered_kind if source is not frame else "battle", None)
    runner._startup_frame = lambda: "recovered"

    def stalled(_kind, _frame, now):
        runner._battle_frame_changed_at = now - 45
        return True

    runner._battle_frame_stalled = stalled
    runner._play = Mock()
    before = counters(runner)
    with pytest.raises(RecoveryExhausted, match="不虚计完成数"):
        runner._battle(resumed=True)
    assert counters(runner) == before
    runner.device.start_app.assert_called_once()
    assert any(event == "battle_frame_frozen" for event, _ in runner.events)
    assert not any(event == "battle_finished" for event, _ in runner.events)
    runner._checkpoint.assert_not_called()
    runner._play.assert_not_called()


def test_freeze_recovery_to_verified_result_records_battle_only_once(runner):
    battle = np.zeros((633, 419, 3), np.uint8)
    result = battle.copy()
    frames = iter([battle, battle, result, result])
    runner._frame = lambda: next(frames)
    runner.vision.classify = lambda frame: ("battle" if frame is battle else "result", None)
    runner.vision.outcome = lambda _: "未知"
    runner._startup_frame = lambda: result

    def stalled(kind, _frame, now):
        runner._battle_frame_changed_at = now - 45
        return kind == "battle"

    runner._battle_frame_stalled = stalled
    runner._return_from_result = Mock()
    runner._battle(resumed=True)
    assert runner.completed == 11
    assert not runner.pending_battle and runner.pending_mastery
    assert runner.generated == 11 and runner.closed_loops == 9 and runner.total_claimed == 2
    assert [event for event, _ in runner.events].count("battle_finished") == 1
    assert runner.recovery_attempts == 1  # result alone cannot clear recovery budget
    runner._return_from_result.assert_called_once()


def test_only_completed_cycle_clears_consecutive_recovery_budget(runner, monkeypatch):
    runner.recovery_attempts = 3
    runner.pending_battle = False
    runner.pending_mastery = True
    runner._startup_frame = lambda: "deck"
    runner._frame = lambda: "deck"
    runner.vision.classify = lambda _: ("unknown", None)
    runner.vision.reward_continuation = lambda _: False
    monkeypatch.setattr(loop_module, "random_ui_is", lambda *args: False)
    runner._require = lambda _: "deck"
    runner._mastery = Mock()
    runner._new_deck = Mock(side_effect=KeyboardInterrupt)
    with pytest.raises(KeyboardInterrupt):
        runner.run_forever()
    assert runner.recovery_attempts == 0
    assert runner.closed_loops == 10
    assert not runner.pending_mastery
    assert runner.completed == 10 and runner.generated == 11 and runner.total_claimed == 2
    assert any(event == "cycle_complete" for event, _ in runner.events)


def test_actual_controller_bad_png_valueerror_is_retried_without_losing_counters(runner):
    expected = runner.device.screenshot.return_value
    encoded, data = cv2.imencode(".png", expected)
    assert encoded
    runner.device.adb.side_effect = [
        subprocess.CompletedProcess([], 0, stdout=b"not-a-png"),
        subprocess.CompletedProcess([], 0, stdout="device"),
        subprocess.CompletedProcess([], 0, stdout=data.tobytes()),
    ]
    runner.device.screenshot = lambda: AdbBasedController.screenshot(runner.device)
    before = counters(runner)
    assert np.array_equal(runner._frame(), expected)
    assert runner.recovery_attempts == 1
    assert counters(runner) == before
    assert runner.taps == []
    runner.device.start_app.assert_not_called()


def test_persistent_decode_valueerror_obeys_three_recovery_limit(runner):
    runner.device.screenshot.side_effect = ValueError(
        "Failed to decode screenshot. Image data may be corrupt or empty."
    )
    before = counters(runner)
    with pytest.raises(RecoveryExhausted, match="连续三次恢复"):
        runner._frame()
    assert runner.device.screenshot.call_count == 4
    assert counters(runner) == before
    assert runner.recovery_attempts == 3


def test_screenshot_argument_valueerror_is_never_swallowed_as_decode_error(runner):
    runner.device.screenshot.side_effect = ValueError("Invalid device serial format: invalid")
    with pytest.raises(ValueError, match="Invalid device serial"):
        runner._frame()
    assert runner.events == []
    runner.device.adb.assert_not_called()


def test_template_valueerror_is_outside_screenshot_retry_scope(runner):
    runner.vision.find.side_effect = ValueError("invalid template")
    with pytest.raises(ValueError, match="invalid template"):
        runner._frame()
    assert runner.events == []
    runner.device.adb.assert_not_called()


def connection_fixture(name):
    frame = cv2.imread(str(Path(__file__).with_name("fixtures") / "cn_connection" / f"interrupted-{name}.png"))
    assert frame is not None
    return frame


@pytest.mark.parametrize("name", ["01", "07"])
def test_real_interrupted_dialog_is_loaded_and_classified_from_two_text_lines(name):
    vision = ChineseVision()
    assert "connection_interrupted" in vision.templates
    assert vision.classify(connection_fixture(name))[0] == "connection_interrupted"


@pytest.mark.parametrize(("y1", "y2"), [(253, 287), (290, 315)])
def test_connection_requires_both_title_and_relogin_body(y1, y2):
    source = connection_fixture("01")
    source[y1:y2, 45:145] = 64
    assert ChineseVision().find(source, "connection_interrupted") is None


@pytest.mark.parametrize(
    "relative",
    [
        "cn_random_mastery/deck_confirm.png",
        "cn_random_mastery/mastery_claim_all.png",
        "cn_random_mastery/mastery_reward_coin.png",
        "cn_random_mastery/mastery_reward_continue.png",
        "cn_random_mastery/late_post_battle_reward.png",
        "cn_rewards/purple_reveal.png",
        "cn_rewards/blue_puzzle_reveal.png",
        "cn_rewards/four_star_chest.png",
        "cn_567/classic1v1_lobby.png",
        "cn_battle_cues/empty_lanes.png",
    ],
)
def test_real_rewards_confirmation_lobby_and_battle_never_match_relogin_dialog(relative):
    source = cv2.imread(str(Path(__file__).with_name("fixtures") / relative))
    assert source is not None
    assert ChineseVision().find(source, "connection_interrupted") is None


def test_interrupted_dialog_restarts_app_without_clicking_authentication_control(runner):
    runner.pending_battle = False
    runner.device.screenshot.return_value = connection_fixture("01")
    runner.vision = ChineseVision()
    restored = np.zeros((633, 419, 3), np.uint8)
    runner._startup_frame = Mock(return_value=restored)
    before = counters(runner)
    assert runner._frame() is restored
    assert runner.taps == []
    runner.device.start_app.assert_called_once_with(CLASH_ROYALE_PACKAGE)
    assert counters(runner) == before
    assert runner.recovery_attempts == 1


def test_pending_claim_all_keeps_receipt_boundary_and_does_not_relaunch_on_disconnect(runner):
    runner.device.screenshot.return_value = connection_fixture("07")
    runner.vision = ChineseVision()
    runner.pending_claim_all = True
    runner.pending_mastery = True
    before = counters(runner)
    with pytest.raises(RecoveryExhausted, match="领奖断点尚待核验"):
        runner._frame()
    assert counters(runner) == before
    assert runner.taps == []
    runner.device.start_app.assert_not_called()
    runner.device.adb.assert_not_called()


def test_repeated_actual_interrupted_dialog_is_limited_to_three_app_restarts(runner):
    runner.device.screenshot.return_value = connection_fixture("01")
    runner.vision = ChineseVision()
    runner._startup_frame = runner._frame
    before = counters(runner)
    with pytest.raises(RecoveryExhausted, match="连续三次恢复"):
        runner._frame()
    assert runner.device.start_app.call_count == 3
    assert counters(runner) == before
    assert runner.taps == []


def test_network_restart_to_lobby_preserves_pending_battle_without_new_deck(runner):
    runner.device.screenshot.return_value = connection_fixture("01")
    runner.vision = ChineseVision()
    classify = runner.vision.classify
    original_vision = runner.vision
    runner.vision = SimpleNamespace(
        find=original_vision.find, classify=lambda frame: ("lobby", None) if isinstance(frame, str) else classify(frame)
    )
    runner._startup_frame = lambda: "lobby"
    runner._new_deck = Mock()
    before = counters(runner)
    with pytest.raises(RecoveryExhausted, match="连接恢复后未确认待续本局"):
        runner._frame()
    assert counters(runner) == before
    assert runner.pending_battle
    assert runner.taps == []
    runner._new_deck.assert_not_called()
    runner._checkpoint.assert_not_called()
    runner.device.start_app.assert_called_once()


@pytest.mark.parametrize("kind", ["lobby", "reward", "deck", "unknown", "connection_interrupted"])
def test_startup_pending_battle_cannot_be_discarded_for_other_pages(runner, kind):
    runner._startup_frame = lambda: kind
    runner.vision.classify = lambda _: (kind, None)
    runner._require = Mock()
    runner._new_deck = Mock()
    before = counters(runner)
    with pytest.raises(RecoveryExhausted, match="启动时未确认待续本局"):
        runner.run_forever()
    assert counters(runner) == before
    assert runner.pending_battle
    runner._require.assert_not_called()
    runner._new_deck.assert_not_called()
    runner._checkpoint.assert_not_called()
    assert not any(event == "battle_finished" for event, _ in runner.events)


@pytest.mark.parametrize("restored_kind", ["battle", "result"])
def test_network_restart_to_owned_battle_or_result_resumes_and_counts_once(runner, restored_kind):
    battle = runner.device.screenshot.return_value.copy()
    result = battle.copy()
    result[0, 0] = 1
    runner.device.screenshot.side_effect = [connection_fixture("07"), result, result]
    runner.vision = ChineseVision()
    classify = runner.vision.classify

    def classify_frame(frame):
        if frame is battle:
            return "battle", None
        if frame is result:
            return "result", None
        return classify(frame)

    original_vision = runner.vision
    runner.vision = SimpleNamespace(find=original_vision.find, classify=classify_frame, outcome=lambda _: "未知")
    runner._startup_frame = lambda: battle if restored_kind == "battle" else result
    runner._new_deck = Mock()
    runner._return_from_result = Mock()
    runner._battle(resumed=True)
    assert runner.completed == 11
    assert runner.generated == 11 and runner.closed_loops == 9 and runner.total_claimed == 2
    assert not runner.pending_battle and runner.pending_mastery
    assert [event for event, _ in runner.events].count("battle_finished") == 1
    runner.device.start_app.assert_called_once()
    runner._return_from_result.assert_called_once()
    runner._new_deck.assert_not_called()
    assert runner.taps == []


def configure_session_limit(runner, monkeypatch, *, pending_mastery=False, pending_battle=False):
    runner.completed = 912
    runner.generated = 919
    runner.closed_loops = 911 if pending_mastery else 912
    runner.pending_mastery = pending_mastery
    runner.pending_battle = pending_battle
    runner._startup_frame = lambda: "battle" if runner.pending_battle else "deck"
    runner._frame = lambda: "deck"
    runner.vision = SimpleNamespace(
        classify=lambda frame: ("battle" if frame == "battle" else "unknown", None),
        reward_continuation=lambda _: False,
    )
    monkeypatch.setattr(loop_module, "random_ui_is", lambda frame, name: frame == "deck" and name == "deck")
    runner._require = lambda _: "deck"
    runner._mastery = Mock()
    runner._navigate = Mock()
    runner._new_deck = Mock()

    def finish_battle(resumed=False):
        if resumed:
            assert runner.pending_battle
        runner.completed += 1
        runner.pending_battle = False
        runner.pending_mastery = True

    runner._battle = Mock(side_effect=finish_battle)


def test_finite_limit_two_with_history_912_finishes_at_914(runner, monkeypatch):
    configure_session_limit(runner, monkeypatch)
    runner.run_forever(max_battles=2)
    assert runner.completed == 914
    assert runner._battle.call_count == 2 and runner._new_deck.call_count == 2
    assert runner._mastery.call_count == 2
    assert runner.state == "stopped" and not runner.pending_mastery
    finite = [values for event, values in runner.events if event == "finite_complete"]
    assert finite == [{"target": 2, "session_completed": 2, "starting_completed": 912, "total_completed": 914}]


def test_old_pending_mastery_cycle_does_not_consume_session_battle_limit(runner, monkeypatch):
    configure_session_limit(runner, monkeypatch, pending_mastery=True)
    runner.run_forever(max_battles=2)
    assert runner.completed == 914
    assert runner._battle.call_count == 2 and runner._new_deck.call_count == 2
    assert runner._mastery.call_count == 3  # old rewards plus two newly completed battles
    assert runner.closed_loops == 914
    assert [event for event, _ in runner.events].count("cycle_complete") == 3


def test_resumed_pending_battle_counts_one_and_limit_one_does_not_start_new_match(runner, monkeypatch):
    configure_session_limit(runner, monkeypatch, pending_battle=True)
    runner.run_forever(max_battles=1)
    assert runner.completed == 913
    runner._battle.assert_called_once_with(resumed=True)
    runner._new_deck.assert_not_called()
    assert runner._mastery.call_count == 1
    assert runner.state == "stopped" and not runner.pending_mastery and not runner.pending_battle


def test_resumed_pending_battle_plus_one_new_battle_satisfies_limit_two(runner, monkeypatch):
    configure_session_limit(runner, monkeypatch, pending_battle=True)
    runner.run_forever(max_battles=2)
    assert runner.completed == 914
    assert runner._battle.call_count == 2
    assert runner._battle.call_args_list[0].kwargs == {"resumed": True}
    runner._new_deck.assert_called_once()
    assert runner._mastery.call_count == 2


def test_zero_session_limit_does_not_stop_at_history_or_new_battles(runner, monkeypatch):
    configure_session_limit(runner, monkeypatch)

    def stop_after_three_battles():
        if runner.completed == 915:
            raise KeyboardInterrupt

    runner._new_deck.side_effect = stop_after_three_battles
    with pytest.raises(KeyboardInterrupt):
        runner.run_forever(max_battles=0)
    assert runner.completed == 915 and runner._battle.call_count == 3
    assert not any(event == "finite_complete" for event, _ in runner.events)
