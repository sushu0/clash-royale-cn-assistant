"""Only the exact game-exit dialog may be cancelled inside active battle state."""

from pathlib import Path
from unittest.mock import Mock

import cv2
import pytest

from pyclashbot.bot import cn_1v1_loop as one_module
from pyclashbot.bot.cn_1v1_loop import ChineseOneVOneLoop, ChineseVision, RecoveryExhausted
from pyclashbot.bot.cn_random_mastery_loop import RandomMasteryLoop
from pyclashbot.bot.coords import CN_PAGE_GAME_EXIT_CANCEL, CN_PAGE_ROIS
from pyclashbot.detection.cn_page_navigation import cn_game_exit_cancel

FIXTURES = Path(__file__).with_name("fixtures")
POPUP = "cn_pages/news_list.png"
BATTLE = "cn_random_hand/live_hand_0.png"


def captured(name):
    frame = cv2.imread(str(FIXTURES / name))
    assert frame is not None, f"Missing exit-popup regression fixture: {name}"
    return frame


def battle_with_exit_dialog():
    frame, popup = captured(BATTLE), captured(POPUP)
    # The independent four-cue dialog region is observed; the underlying battle
    # is separate captured evidence. This is explicitly a synthetic composite.
    frame[193:451, 47:371] = popup[193:451, 47:371]
    assert cn_game_exit_cancel(frame) is not None
    return frame


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(one_module.time, "monotonic", lambda: 101.0)
    monkeypatch.setattr(one_module.time, "sleep", lambda _: None)


def random_runner(snapshots):
    runner = RandomMasteryLoop.__new__(RandomMasteryLoop)
    runner.stop_path = Mock(exists=Mock(return_value=False))
    runner._capture_frame = Mock(side_effect=snapshots)
    runner.vision = Mock(wraps=ChineseVision())
    runner.logger, runner._event = Mock(), Mock()
    runner._save = Mock(return_value={"fixture": True})
    runner._tap, runner._checkpoint, runner._recover_app = Mock(), Mock(), Mock()
    runner.state = "battle"
    runner.pending_battle, runner.pending_mastery, runner.pending_claim_all = True, True, True
    runner.reward_claim_id = "claim-id-kept"
    runner.reward_receipts = [{"id": "receipt-kept", "kind": "coins", "amount": 4000}]
    runner.completed, runner.generated, runner.closed_loops, runner.total_claimed = 1198, 1208, 1198, 156
    runner.cards_confirmed, runner.card_attempts, runner.recovery_attempts = 3, 4, 2
    return runner


def one_runner():
    runner = ChineseOneVOneLoop.__new__(ChineseOneVOneLoop)
    runner.vision = Mock(wraps=ChineseVision())
    runner.logger, runner._trace = Mock(), Mock()
    runner._save_evidence = Mock(return_value={"fixture": True})
    runner._tap, runner._recover, runner._set_state, runner._play_card = Mock(), Mock(), Mock(), Mock()
    runner._clock_stalled = Mock(return_value=False)
    runner.state, runner.state_since, runner.last_unknown_evidence = "battle", 100.0, 100.0
    runner.reward_pending, runner.reward_taps, runner.four_star_reward_seen = True, 7, True
    runner.last_reward_tap_at, runner.last_four_star_tap_at = 100.0, 99.0
    runner.battle_confirmations, runner.result_confirmations, runner.lobby_confirmations = 0, 0, 0
    runner.completed, runner.consecutive, runner.closed_loops = 1198, 5, 1198
    runner.cards_confirmed, runner.card_attempts, runner.recovery_attempts = 3, 4, 2
    runner._classic_menu_verified = True
    return runner


def test_random_active_battle_cancels_only_the_dialog_then_returns_new_battle_frame():
    popup, fresh_battle = battle_with_exit_dialog(), captured(BATTLE)
    runner = random_runner([popup, fresh_battle])
    assert runner._frame() is fresh_battle
    assert runner._capture_frame.call_count == 2
    runner._tap.assert_called_once_with(CN_PAGE_GAME_EXIT_CANCEL, 0.8)
    assert runner._save.call_args.args[1] is popup
    assert runner._event.call_args.args[0] == "game_exit_cancelled"
    assert runner._event.call_args.kwargs["attempt"] == 1
    assert all(call.args[0] is fresh_battle for call in runner.vision.find.call_args_list)
    assert runner.state == "battle" and runner.pending_battle and runner.pending_claim_all
    assert runner.reward_claim_id == "claim-id-kept"
    assert runner.reward_receipts == [{"id": "receipt-kept", "kind": "coins", "amount": 4000}]
    assert (runner.completed, runner.generated, runner.closed_loops, runner.total_claimed) == (1198, 1208, 1198, 156)
    assert (runner.cards_confirmed, runner.card_attempts, runner.recovery_attempts) == (3, 4, 2)
    runner._checkpoint.assert_not_called()
    runner._recover_app.assert_not_called()
    assert runner._exit_cancel_attempts == 0


def test_random_repeated_dialog_reobserves_each_attempt_and_sends_only_three_cancels():
    popups = [battle_with_exit_dialog() for _ in range(4)]
    runner = random_runner(popups)
    with pytest.raises(RecoveryExhausted, match="连续3次"):
        runner._frame()
    assert runner._capture_frame.call_count == 4 and runner._tap.call_count == 3
    assert all(call.args == (CN_PAGE_GAME_EXIT_CANCEL, 0.8) for call in runner._tap.call_args_list)
    assert [call.kwargs["attempt"] for call in runner._event.call_args_list] == [1, 2, 3]
    assert [call.args[1] is popup for call, popup in zip(runner._save.call_args_list, popups[:3], strict=True)] == [
        True
    ] * 3
    runner.vision.classify.assert_not_called()
    runner.vision.find.assert_not_called()
    runner._checkpoint.assert_not_called()
    runner._recover_app.assert_not_called()


def test_random_normal_frame_resets_cancel_budget_before_a_new_popup():
    first_battle, second_battle = captured(BATTLE), captured(BATTLE)
    runner = random_runner([battle_with_exit_dialog(), first_battle, battle_with_exit_dialog(), second_battle])
    assert runner._frame() is first_battle
    assert runner._frame() is second_battle
    assert [call.kwargs["attempt"] for call in runner._event.call_args_list] == [1, 1]
    assert runner._exit_cancel_attempts == 0


def test_random_stop_marker_has_priority_over_cancel_input_and_screenshot():
    runner = random_runner([battle_with_exit_dialog()])
    runner.stop_path.exists.return_value = True
    with pytest.raises(KeyboardInterrupt):
        runner._frame()
    runner._capture_frame.assert_not_called()
    runner._tap.assert_not_called()
    runner._event.assert_not_called()


def test_random_stop_after_one_cancel_prevents_recapture_or_another_input():
    runner = random_runner([battle_with_exit_dialog(), battle_with_exit_dialog()])

    def stop_after_tap(*_):
        runner.stop_path.exists.return_value = True

    runner._tap.side_effect = stop_after_tap
    with pytest.raises(KeyboardInterrupt):
        runner._frame()
    assert runner._capture_frame.call_count == runner._tap.call_count == 1
    runner._checkpoint.assert_not_called()
    assert runner.pending_battle and runner.pending_claim_all


def test_chinese_active_battle_cancels_dialog_before_classification_or_any_other_action():
    popup = battle_with_exit_dialog()
    runner = one_runner()
    runner._step(popup)
    runner._tap.assert_called_once_with(CN_PAGE_GAME_EXIT_CANCEL)
    runner.vision.classify.assert_not_called()
    runner._play_card.assert_not_called()
    runner._recover.assert_not_called()
    runner._set_state.assert_not_called()
    assert runner._save_evidence.call_args.args[1] is popup
    assert runner._trace.call_args.args[0]["event"] == "game_exit_cancelled"
    assert runner.state == "battle" and runner.reward_pending and runner.reward_taps == 7
    assert runner.four_star_reward_seen and runner.last_four_star_tap_at == 99.0
    assert (runner.completed, runner.consecutive, runner.closed_loops) == (1198, 5, 1198)
    assert (runner.cards_confirmed, runner.card_attempts, runner.recovery_attempts) == (3, 4, 2)
    assert runner._classic_menu_verified


def test_chinese_next_iteration_observes_new_battle_and_resets_cancel_budget():
    runner = one_runner()
    runner.reward_pending = False
    popup, battle = battle_with_exit_dialog(), captured(BATTLE)
    runner._step(popup)
    runner._step(battle)
    assert runner.vision.classify.call_args.args[0] is battle
    assert runner._exit_cancel_attempts == 0
    runner._tap.assert_called_once_with(CN_PAGE_GAME_EXIT_CANCEL)
    runner._play_card.assert_called_once_with(battle)
    assert runner.state == "battle"
    runner._step(battle_with_exit_dialog())
    assert runner._trace.call_args.args[0]["attempt"] == 1


def test_chinese_four_consecutive_dialog_frames_have_only_three_cancel_inputs():
    runner = one_runner()
    for _ in range(3):
        runner._step(battle_with_exit_dialog())
    with pytest.raises(RecoveryExhausted, match="连续3次"):
        runner._step(battle_with_exit_dialog())
    assert runner._tap.call_count == 3
    assert all(call.args == (CN_PAGE_GAME_EXIT_CANCEL,) for call in runner._tap.call_args_list)
    assert [call.args[0]["attempt"] for call in runner._trace.call_args_list] == [1, 2, 3]
    runner.vision.classify.assert_not_called()
    runner._recover.assert_not_called()


@pytest.mark.parametrize("cue", ["game_exit_title", "game_exit_message", "game_exit_cancel", "game_exit_confirm"])
def test_missing_any_exit_dialog_cue_cannot_authorize_cancel(cue):
    popup = battle_with_exit_dialog()
    x1, y1, x2, y2 = CN_PAGE_ROIS[cue]
    popup[y1:y2, x1:x2] = 0
    assert cn_game_exit_cancel(popup) is None
    runner = random_runner([popup])
    assert runner._frame() is popup
    runner._tap.assert_not_called()


@pytest.mark.parametrize(
    "name",
    ["cn_random_mastery/deck_confirm.png", "cn_random_mastery/deck_menu.png", "cn_pages/spectate_exit_confirm.png"],
)
def test_generate_menu_and_spectator_confirmation_cannot_authorize_game_exit_cancel(name):
    frame = captured(name)
    assert cn_game_exit_cancel(frame) is None
    random = random_runner([frame])
    assert random._frame() is frame
    random._tap.assert_not_called()
    chinese = one_runner()
    chinese.reward_pending = False
    chinese._step(frame)
    chinese._tap.assert_not_called()
    chinese._recover.assert_not_called()
