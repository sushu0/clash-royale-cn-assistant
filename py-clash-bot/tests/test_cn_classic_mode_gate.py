"""A fresh causal mode-menu check must precede the first Classic 1v1 request."""

from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import numpy as np
import pytest

from pyclashbot.bot import cn_1v1_loop as one_module
from pyclashbot.bot import cn_random_mastery_loop as random_module
from pyclashbot.bot.cn_1v1_loop import ChineseOneVOneLoop, ModeOrDeckMismatch, RecoveryExhausted
from pyclashbot.bot.cn_random_mastery_loop import RandomMasteryLoop


class LabelledFrame(str):
    """A sized frame token; image predicates reject it and vision is mocked."""

    shape = (633, 419, 3)


class LabelledCapture(np.ndarray):
    """A raw image contract with the existing unit seam's comparison label."""

    __hash__ = None
    name: str

    def __new__(cls, name: str) -> "LabelledCapture":
        result = cast("LabelledCapture", np.zeros((633, 419, 3), np.uint8).view(cls))
        result.name = name
        return result

    def __eq__(self, other):
        return self.name == other if isinstance(other, str) else super().__eq__(other)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(random_module.time, "monotonic", lambda: 101.0)
    monkeypatch.setattr(random_module.time, "sleep", lambda _: None)


def vision_for():
    matches = {name: SimpleNamespace(center=f"{name}-match") for name in ("stale", "fresh", "idle", "recovered")}
    vision = SimpleNamespace(
        classify=Mock(side_effect=lambda frame: ("lobby", matches[frame]) if frame in matches else (frame, None)),
        classic_selected=Mock(side_effect=lambda frame: frame in matches),
        lobby_start_state=Mock(return_value="ready"),
        reward_continuation=Mock(return_value=False),
    )
    return vision


def random_runner(snapshots=()):
    runner = RandomMasteryLoop.__new__(RandomMasteryLoop)
    runner.vision = vision_for()
    runner._frame = Mock(side_effect=snapshots)

    def label(frame):
        return runner._preflight_label if isinstance(frame, np.ndarray) else frame

    def raw_capture(deadline):
        runner._preflight_label = runner._frame()
        return LabelledCapture(runner._preflight_label)

    classify, classic = runner.vision.classify.side_effect, runner.vision.classic_selected.side_effect
    runner.vision.classify.side_effect = lambda frame: classify(label(frame))
    runner.vision.classic_selected.side_effect = lambda frame: classic(label(frame))
    runner._preflight_capture = Mock(side_effect=raw_capture)
    runner._preflight_classic_lobby = Mock(
        side_effect=lambda frame, **_: (label(frame), runner.vision.classify(frame)[1])
    )
    runner.stop_path = SimpleNamespace(exists=lambda: False)
    runner._preflight_foreground = Mock(return_value=one_module.CLASH_ROYALE_PACKAGE)
    runner.device = SimpleNamespace(adb=Mock(return_value=SimpleNamespace(returncode=0)), start_app=Mock())
    runner.logger = Mock()
    runner._event = Mock()
    runner._save = Mock(return_value={"fixture": True})
    runner._tap = Mock()
    runner._checkpoint = Mock()
    runner._reset_battle_frame_monitor = Mock()
    runner.pending_battle, runner.pending_claim_all, runner.pending_mastery = False, False, False
    runner.reward_receipts = [{"id": "saved-receipt", "kind": "coins", "amount": 4000}]
    runner.reward_claim_id = "saved-id"
    runner.completed, runner.generated, runner.closed_loops, runner.total_claimed = 1198, 1208, 1198, 156
    runner.cards_confirmed, runner.card_attempts = 3, 4
    runner.recovery_attempts = 0
    runner.state = "starting"
    return runner


def one_runner():
    runner = ChineseOneVOneLoop.__new__(ChineseOneVOneLoop)
    runner.vision = vision_for()
    runner.device = SimpleNamespace(screenshot=Mock(), adb=Mock(), start_app=Mock())
    runner.logger, runner._trace, runner._save_evidence = Mock(), Mock(), Mock(return_value={"fixture": True})
    runner._tap, runner._recover, runner._set_state = Mock(), Mock(), Mock()
    runner.state, runner.state_since = "lobby", 100.0
    runner._classic_menu_verified = False
    runner.reward_pending, runner.reward_taps, runner.four_star_reward_seen = False, 0, False
    runner.last_reward_tap_at, runner.last_four_star_tap_at, runner.last_unknown_evidence = 100.0, 0.0, 100.0
    runner.battle_confirmations, runner.result_confirmations, runner.lobby_confirmations = 0, 0, 0
    runner.completed, runner.consecutive, runner.closed_loops = 99, 5, 5
    runner.cycle_pending = True
    runner.strategy_name = "hog"
    return runner


def test_random_initial_mode_verification_returns_new_confirmed_frame_and_preserves_checkpoint(monkeypatch):
    runner = random_runner(["fresh"])
    navigation = Mock(return_value=True)
    monkeypatch.setattr(random_module, "navigate_cn_classic_1v1", navigation)
    assert runner._prepare_classic_lobby("stale", verify_menu=True) == "fresh"
    assert navigation.call_args.kwargs == {"verify_menu": True}
    assert runner._classic_menu_verified
    runner._tap.assert_not_called()
    runner._checkpoint.assert_not_called()
    runner.device.adb.assert_not_called()
    assert (runner.completed, runner.generated, runner.closed_loops, runner.total_claimed) == (1198, 1208, 1198, 156)
    assert runner.reward_claim_id == "saved-id" and runner.reward_receipts[0]["id"] == "saved-receipt"
    assert runner._save.call_args_list[0].args[1] == "stale"
    assert runner._save.call_args_list[1].args[1] == "fresh"


@pytest.mark.parametrize("flag", ["pending_battle", "pending_claim_all"])
def test_random_pending_work_forbids_even_opening_the_mode_menu(flag, monkeypatch):
    runner = random_runner()
    setattr(runner, flag, True)
    navigation = Mock()
    monkeypatch.setattr(random_module, "navigate_cn_classic_1v1", navigation)
    with pytest.raises(RecoveryExhausted, match="断点尚未闭合"):
        runner._prepare_classic_lobby("stale", verify_menu=True)
    navigation.assert_not_called()
    runner._frame.assert_not_called()
    runner.device.adb.assert_not_called()
    runner._checkpoint.assert_not_called()
    assert getattr(runner, flag) and runner.reward_claim_id == "saved-id"


@pytest.mark.parametrize("kind", ["battle", "result", "reward", "unknown"])
def test_random_nonlobby_initial_frame_forbids_mode_menu(kind, monkeypatch):
    runner = random_runner()
    navigation = Mock()
    monkeypatch.setattr(random_module, "navigate_cn_classic_1v1", navigation)
    with pytest.raises(RecoveryExhausted, match="切换经典模式前未确认大厅"):
        runner._prepare_classic_lobby(kind, verify_menu=True)
    navigation.assert_not_called()
    runner.device.adb.assert_not_called()


def test_random_failed_idle_menu_check_relaunches_once_then_retries_and_returns_fresh_frame(monkeypatch):
    runner = random_runner(["idle", "fresh"])
    runner._startup_frame = Mock(return_value="recovered")
    navigation = Mock(side_effect=[False, True])
    monkeypatch.setattr(random_module, "navigate_cn_classic_1v1", navigation)
    assert runner._prepare_classic_lobby("stale", verify_menu=True) == "fresh"
    assert navigation.call_count == 2
    assert all(call.kwargs == {"verify_menu": True} for call in navigation.call_args_list)
    assert runner.device.adb.call_count == runner.device.start_app.call_count == 1
    runner._startup_frame.assert_called_once()
    assert runner.recovery_attempts == 1 and runner._classic_menu_verified
    runner._checkpoint.assert_not_called()
    runner._tap.assert_not_called()


def test_random_two_failed_idle_menu_checks_have_only_one_relaunch_and_never_match(monkeypatch):
    runner = random_runner(["idle", "idle"])
    runner._startup_frame = Mock(return_value="recovered")
    navigation = Mock(return_value=False)
    monkeypatch.setattr(random_module, "navigate_cn_classic_1v1", navigation)
    with pytest.raises(RecoveryExhausted, match="可交互大厅"):
        runner._prepare_classic_lobby("stale", verify_menu=True)
    assert navigation.call_count == 2
    assert runner.device.adb.call_count == runner.device.start_app.call_count == 1
    assert runner.recovery_attempts == 1 and not runner._classic_menu_verified
    runner._tap.assert_not_called()
    assert not runner.pending_battle


@pytest.mark.parametrize("fresh_kind", ["battle", "result", "reward"])
@pytest.mark.parametrize("helper_success", [False, True])
def test_random_new_battle_or_reward_after_mode_attempt_never_authorizes_relaunch(
    fresh_kind, helper_success, monkeypatch
):
    runner = random_runner([fresh_kind, "idle", "fresh"])
    runner._startup_frame = Mock(return_value="recovered")
    navigation = Mock(return_value=helper_success)
    monkeypatch.setattr(random_module, "navigate_cn_classic_1v1", navigation)
    with pytest.raises(RecoveryExhausted):
        runner._prepare_classic_lobby("stale", verify_menu=True)
    runner.device.adb.assert_not_called()
    runner.device.start_app.assert_not_called()
    runner._startup_frame.assert_not_called()
    runner._tap.assert_not_called()
    assert runner._frame.call_count == 1
    assert runner.recovery_attempts == 0


def test_random_mode_relaunch_cannot_reset_the_existing_three_attempt_budget(monkeypatch):
    runner = random_runner(["idle"])
    runner.recovery_attempts = 3
    runner._startup_frame = Mock()
    monkeypatch.setattr(random_module, "navigate_cn_classic_1v1", Mock(return_value=False))
    with pytest.raises(RecoveryExhausted):
        runner._prepare_classic_lobby("stale", verify_menu=True)
    assert runner.recovery_attempts == 3
    runner.device.adb.assert_not_called()
    runner.device.start_app.assert_not_called()
    runner._startup_frame.assert_not_called()


def test_random_startup_mode_failure_stops_before_deck_navigation_or_generation(monkeypatch):
    runner = random_runner()
    runner._startup_frame = Mock(return_value="stale")
    runner._prepare_classic_lobby = Mock(side_effect=RecoveryExhausted("mode-gate-failed"))
    runner._navigate, runner._require, runner._new_deck = Mock(), Mock(), Mock()
    monkeypatch.setattr(random_module, "random_ui_is", lambda *_: False)
    with pytest.raises(RecoveryExhausted, match="mode-gate-failed"):
        runner.run_forever()
    runner._prepare_classic_lobby.assert_called_once_with("stale", verify_menu=True)
    runner._navigate.assert_not_called()
    runner._require.assert_not_called()
    runner._new_deck.assert_not_called()
    runner._tap.assert_not_called()
    assert runner.state == "paused"


def test_random_successful_startup_verifies_mode_before_entering_deck(monkeypatch):
    runner = random_runner()
    runner._startup_frame = Mock(return_value="stale")
    order = []

    def prepare(frame, *, verify_menu):
        assert frame == "stale" and verify_menu
        order.append("verify-mode")
        return "fresh"

    def stop_before_generation():
        order.append("generate-deck")
        raise KeyboardInterrupt

    runner._prepare_classic_lobby = Mock(side_effect=prepare)
    runner._navigate = Mock(side_effect=lambda *_: order.append("enter-deck"))
    runner._require = Mock(side_effect=lambda _: order.append("verify-deck"))
    runner._new_deck = Mock(side_effect=stop_before_generation)
    monkeypatch.setattr(random_module, "random_ui_is", lambda *_: False)
    with pytest.raises(KeyboardInterrupt):
        runner.run_forever()
    assert order == ["verify-mode", "enter-deck", "verify-deck", "generate-deck"]
    runner._tap.assert_not_called()
    assert not runner.pending_battle


def test_random_collection_startup_returns_to_fresh_lobby_then_verifies_mode_before_deck(monkeypatch):
    runner = random_runner(["fresh"])
    runner._startup_frame = Mock(return_value="collection")
    classify = runner.vision.classify.side_effect
    runner.vision.classify.side_effect = lambda frame: (
        ("navigation", None) if frame == "collection" else classify(frame)
    )
    order = []
    runner._return_known_page = Mock(side_effect=lambda *_args, **_kwargs: order.append("return-collection") or True)
    runner._prepare_classic_lobby = Mock(side_effect=lambda *_args, **_kwargs: order.append("verify-mode") or "fresh")
    runner._navigate = Mock(side_effect=lambda *_: order.append("enter-deck"))
    runner._require = Mock(side_effect=lambda _: order.append("verify-deck"))
    runner._new_deck = Mock(side_effect=KeyboardInterrupt)
    monkeypatch.setattr(
        random_module, "random_ui_is", lambda frame, name: frame == "collection" and name == "collection"
    )
    with pytest.raises(KeyboardInterrupt):
        runner.run_forever()
    runner._return_known_page.assert_called_once_with("collection", expected="classic_lobby")
    runner._prepare_classic_lobby.assert_called_once_with("fresh", verify_menu=True)
    assert order == ["return-collection", "verify-mode", "enter-deck", "verify-deck"]
    runner._tap.assert_not_called()


def test_random_collection_startup_with_unverified_return_route_never_enters_deck(monkeypatch):
    runner = random_runner()
    runner._startup_frame = Mock(return_value="collection")
    runner.vision.classify.side_effect = lambda _: ("navigation", None)
    runner._return_known_page = Mock(return_value=False)
    runner._prepare_classic_lobby, runner._navigate, runner._require, runner._new_deck = Mock(), Mock(), Mock(), Mock()
    monkeypatch.setattr(
        random_module, "random_ui_is", lambda frame, name: frame == "collection" and name == "collection"
    )
    with pytest.raises(RecoveryExhausted, match="收藏页面尚未确认返回大厅路径"):
        runner.run_forever()
    runner._frame.assert_not_called()
    runner._prepare_classic_lobby.assert_not_called()
    runner._navigate.assert_not_called()
    runner._require.assert_not_called()
    runner._new_deck.assert_not_called()
    assert runner.state == "paused"


def test_random_first_prefight_uses_menu_verified_fresh_match_center(monkeypatch):
    runner = random_runner(["stale"])

    def complete_mode_verification(*args, **kwargs):
        runner._classic_menu_verified = True
        return "fresh"

    runner._prepare_classic_lobby = Mock(side_effect=complete_mode_verification)
    runner._tap.side_effect = KeyboardInterrupt
    monkeypatch.setattr(random_module, "random_ui_is", lambda *_: False)
    with pytest.raises(KeyboardInterrupt):
        runner._battle()
    runner._prepare_classic_lobby.assert_called_once_with("stale", verify_menu=True)
    runner._tap.assert_called_once_with("fresh-match", 0.5)
    runner._checkpoint.assert_called_once()
    assert runner.pending_battle


def test_random_first_prefight_gate_failure_does_not_submit_or_checkpoint_match():
    runner = random_runner(["stale"])
    runner._prepare_classic_lobby = Mock(side_effect=RecoveryExhausted("failed-mode"))
    with pytest.raises(RecoveryExhausted, match="failed-mode"):
        runner._battle()
    runner._tap.assert_not_called()
    runner._checkpoint.assert_not_called()
    assert not runner.pending_battle


def test_random_resumed_owned_battle_never_opens_mode_menu():
    runner = random_runner(["battle", KeyboardInterrupt])
    runner.pending_battle = True
    runner._prepare_classic_lobby = Mock()
    with pytest.raises(KeyboardInterrupt):
        runner._battle(resumed=True)
    runner._prepare_classic_lobby.assert_not_called()
    runner._tap.assert_not_called()
    runner._checkpoint.assert_not_called()
    assert runner.pending_battle and runner.completed == 1198


def test_chinese_first_lobby_verifies_menu_without_matching_then_uses_next_fresh_lobby(monkeypatch):
    runner = one_runner()
    navigation = Mock(return_value=True)
    monkeypatch.setattr(one_module, "navigate_cn_classic_1v1", navigation)
    runner._step(LabelledFrame("stale"))
    assert navigation.call_args.kwargs == {"verify_menu": True}
    assert runner._classic_menu_verified
    runner._tap.assert_not_called()
    runner._set_state.assert_not_called()
    runner._step(LabelledFrame("fresh"))
    runner._tap.assert_called_once_with("fresh-match")
    runner._set_state.assert_called_once_with("match")
    assert navigation.call_count == 1


@pytest.mark.parametrize("fresh_kind", ["battle", "result", "reward"])
def test_chinese_mode_failure_cannot_relaunch_a_new_battle_result_or_reward(fresh_kind, monkeypatch):
    runner = one_runner()
    runner.device.screenshot.return_value = fresh_kind
    monkeypatch.setattr(one_module, "navigate_cn_classic_1v1", Mock(return_value=False))
    with pytest.raises(ModeOrDeckMismatch, match="保留现场"):
        runner._step(LabelledFrame("stale"))
    runner._recover.assert_not_called()
    runner._tap.assert_not_called()
    assert not runner._classic_menu_verified


def test_chinese_mode_failure_uses_existing_idle_recovery_without_submitting_match(monkeypatch):
    runner = one_runner()
    runner.device.screenshot.return_value = "idle"
    monkeypatch.setattr(one_module, "navigate_cn_classic_1v1", Mock(return_value=False))
    runner._step(LabelledFrame("stale"))
    runner._recover.assert_called_once()
    runner._tap.assert_not_called()
    runner._set_state.assert_not_called()
    assert not runner._classic_menu_verified


def test_chinese_recovery_invalidates_menu_verification_and_keeps_existing_budget():
    runner = one_runner()
    runner._classic_menu_verified = True
    runner.recovery_attempts = 3
    with pytest.raises(RecoveryExhausted):
        ChineseOneVOneLoop._recover(runner, "mode verification failed")
    assert not runner._classic_menu_verified and runner.recovery_attempts == 4
    runner.device.adb.assert_not_called()
    runner.device.start_app.assert_not_called()


@pytest.mark.parametrize("state", ["battle", "match", "result"])
def test_chinese_other_match_states_cannot_trigger_first_lobby_mode_menu(state, monkeypatch):
    runner = one_runner()
    runner.state = state
    navigation = Mock()
    monkeypatch.setattr(one_module, "navigate_cn_classic_1v1", navigation)
    runner._step(LabelledFrame("stale"))
    navigation.assert_not_called()
    runner._tap.assert_not_called()
