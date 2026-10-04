"""A fresh start can reconcile an unresolved match only at a proven idle lobby."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from pyclashbot.bot import cn_random_mastery_loop as loop_module
from pyclashbot.bot.cn_1v1_loop import RecoveryExhausted
from pyclashbot.bot.cn_random_mastery_loop import RandomMasteryLoop
from pyclashbot.emulators.base import CLASH_ROYALE_PACKAGE


def frame(kind):
    picture = np.indices((633, 419))[0].astype(np.uint8).repeat(3).reshape(633, 419, 3)
    return SimpleNamespace(kind=kind, picture=picture)


@pytest.fixture
def runner(tmp_path, monkeypatch):
    loop = RandomMasteryLoop.__new__(RandomMasteryLoop)
    loop.completed, loop.generated, loop.closed_loops, loop.total_claimed = 1262, 1273, 1262, 217
    loop.pending_battle, loop.pending_mastery, loop.pending_claim_all = True, False, False
    loop.reward_claim_id, loop.reward_receipts = "old-claim", [{"id": "receipt", "kind": "coins", "amount": 800}]
    loop.reward_slot, loop.reward_phase = 1, "done"
    loop.card_attempts, loop.cards_confirmed = 23, 23
    loop.last_action = {"old_attempt": True}
    loop.evidence_sequence = 0
    loop.session, loop.work, loop.state = "20261005-003900", tmp_path, "starting"
    loop.checkpoint_path = tmp_path / "checkpoint.json"
    loop.result_outbox_path = tmp_path / "pending-result.json"
    loop.logger, loop._tap, loop._event = Mock(), Mock(), Mock()
    loop.device = SimpleNamespace(foreground_package=Mock(return_value=CLASH_ROYALE_PACKAGE))
    loop.vision = SimpleNamespace(
        classify=Mock(side_effect=lambda observed: (observed.kind, object() if observed.kind == "lobby" else None)),
        find=Mock(return_value=None),
        reward_continuation=Mock(return_value=False),
    )
    loop._frame = Mock(return_value=frame("lobby"))
    save = loop._save
    loop._save = lambda name, observed: save(name, observed.picture)
    loop._checkpoint()
    loop._checkpoint = Mock(wraps=loop._checkpoint)
    loop.result_outbox_path.write_bytes(b'{"schema":1,"committed":true,"result":{"battle":1262}}')
    monkeypatch.setattr(loop_module.time, "sleep", lambda _: None)
    return loop


def counts(loop):
    return loop.completed, loop.generated, loop.closed_loops, loop.total_claimed


def test_two_logged_in_lobby_observations_preserve_unresolved_evidence_without_a_result(runner):
    original = runner.checkpoint_path.read_bytes()
    old_result = runner.result_outbox_path.read_bytes()
    old_counts = counts(runner)
    fresh = runner._frame.return_value

    assert runner._reconcile_pending_startup(frame("lobby")) is fresh

    assert not runner.pending_battle
    assert counts(runner) == old_counts
    assert not runner.pending_mastery and not runner.pending_claim_all
    assert runner.card_attempts == runner.cards_confirmed == 0
    assert runner.last_action == {}
    assert runner.result_outbox_path.read_bytes() == old_result
    (archived,) = runner.work.glob("unresolved-battle-1263-*.json")
    record = json.loads(archived.read_text(encoding="utf-8"))
    assert record["checkpoint_before"] == json.loads(original)
    assert record["battle"] == 1263 and record["generation"] == 1273
    assert record["event"] == "pending_battle_unresolved" and record["counts_as_completed"] is False
    assert "outcome" not in record and "finished_battle" not in record
    assert record["card_attempts"] == record["cards_confirmed"] == 23
    assert len(record["observations"]) == 2
    for observation in record["observations"]:
        picture = Path(observation["path"])
        assert picture.parent == runner.work / "evidence"
        assert hashlib.sha256(picture.read_bytes()).hexdigest() == observation["sha256"]
    assert json.loads(runner.checkpoint_path.with_suffix(".json.bak").read_text(encoding="utf-8"))["pending_battle"]
    assert not json.loads(runner.checkpoint_path.read_text(encoding="utf-8"))["pending_battle"]
    assert runner.device.foreground_package.call_count == 2
    runner._frame.assert_called_once()
    runner._checkpoint.assert_called_once()
    runner._tap.assert_not_called()
    assert [call.args[0] for call in runner._event.call_args_list] == ["pending_battle_unresolved"]


@pytest.mark.parametrize("kind", ["battle", "result"])
def test_owned_battle_or_result_is_resumed_without_clearing_checkpoint(runner, kind):
    observed = frame(kind)
    assert runner._reconcile_pending_startup(observed) is observed
    assert runner.pending_battle and counts(runner) == (1262, 1273, 1262, 217)
    runner._frame.assert_not_called()
    runner._checkpoint.assert_not_called()
    runner._event.assert_not_called()


@pytest.mark.parametrize("kind", ["battle", "result"])
def test_lobby_transition_to_owned_battle_or_result_resumes_it(runner, kind):
    resumed = frame(kind)
    runner._frame.return_value = resumed
    assert runner._reconcile_pending_startup(frame("lobby")) is resumed
    assert runner.pending_battle
    assert not list(runner.work.glob("unresolved-battle-*.json"))
    runner._checkpoint.assert_not_called()
    runner._tap.assert_not_called()


@pytest.mark.parametrize("kind", ["unknown", "matching", "reward", "connection", "deck", "collection"])
def test_unproven_initial_screen_keeps_original_checkpoint(runner, kind):
    original = runner.checkpoint_path.read_bytes()
    with pytest.raises(RecoveryExhausted, match="启动时未确认待续本局"):
        runner._reconcile_pending_startup(frame(kind))
    assert runner.pending_battle and runner.checkpoint_path.read_bytes() == original
    runner._frame.assert_not_called()
    runner._checkpoint.assert_not_called()
    runner._tap.assert_not_called()


@pytest.mark.parametrize("kind", ["unknown", "matching", "reward", "connection", "deck"])
def test_second_observation_must_still_be_an_idle_lobby(runner, kind):
    runner._frame.return_value = frame(kind)
    with pytest.raises(RecoveryExhausted, match="稳定空闲大厅"):
        runner._reconcile_pending_startup(frame("lobby"))
    assert runner.pending_battle
    assert not list(runner.work.glob("unresolved-battle-*.json"))
    runner._checkpoint.assert_not_called()
    runner._tap.assert_not_called()


@pytest.mark.parametrize("problem", ["no_match", "battle_hud", "reward", "other_app", "mastery", "claim"])
def test_lobby_classification_alone_cannot_close_the_attempt(runner, problem):
    if problem == "no_match":
        runner.vision.classify.return_value = ("lobby", None)
        runner.vision.classify.side_effect = None
    elif problem == "battle_hud":
        runner.vision.find.return_value = object()
    elif problem == "reward":
        runner.vision.reward_continuation.return_value = True
    elif problem == "other_app":
        runner.device.foreground_package.return_value = "android.launcher"
    elif problem == "mastery":
        runner.pending_mastery = True
    else:
        runner.pending_claim_all = True
    with pytest.raises(RecoveryExhausted, match="启动时未确认待续本局"):
        runner._reconcile_pending_startup(frame("lobby"))
    assert runner.pending_battle
    runner._frame.assert_not_called()
    runner._checkpoint.assert_not_called()


def test_foreground_must_remain_the_game_for_the_second_observation(runner):
    runner.device.foreground_package.side_effect = [CLASH_ROYALE_PACKAGE, "android.launcher"]
    with pytest.raises(RecoveryExhausted, match="稳定空闲大厅"):
        runner._reconcile_pending_startup(frame("lobby"))
    assert runner.pending_battle
    runner._checkpoint.assert_not_called()


def test_stop_during_confirmation_keeps_pending_battle(runner):
    runner._frame.side_effect = KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        runner._reconcile_pending_startup(frame("lobby"))
    assert runner.pending_battle
    runner._checkpoint.assert_not_called()


def test_archive_failure_does_not_clear_the_live_checkpoint(runner, monkeypatch):
    monkeypatch.setattr(loop_module, "atomic_write_json", Mock(side_effect=OSError("archive is not writable")))
    with pytest.raises(OSError, match="archive is not writable"):
        runner._reconcile_pending_startup(frame("lobby"))
    assert runner.pending_battle
    runner._checkpoint.assert_not_called()
    runner._event.assert_not_called()


def test_checkpoint_failure_retains_pending_flag_and_saved_unresolved_evidence(runner):
    runner._checkpoint.side_effect = OSError("checkpoint is not writable")
    with pytest.raises(OSError, match="checkpoint is not writable"):
        runner._reconcile_pending_startup(frame("lobby"))
    assert runner.pending_battle and counts(runner) == (1262, 1273, 1262, 217)
    assert runner.card_attempts == runner.cards_confirmed == 23
    assert len(list(runner.work.glob("unresolved-battle-*.json"))) == 1
    assert json.loads(runner.checkpoint_path.read_text(encoding="utf-8"))["pending_battle"]


def test_explicit_start_proceeds_to_a_new_deck_after_safe_reconciliation(runner, monkeypatch):
    lobby = frame("lobby")
    runner._startup_frame = Mock(return_value=lobby)
    runner._prepare_classic_lobby = Mock(side_effect=lambda observed, **_: observed)
    runner._navigate, runner._require = Mock(), Mock()
    runner._new_deck = Mock(side_effect=KeyboardInterrupt)
    monkeypatch.setattr(loop_module, "random_ui_is", lambda *_: False)
    with pytest.raises(KeyboardInterrupt):
        runner.run_forever()
    assert not runner.pending_battle
    runner._prepare_classic_lobby.assert_called_once_with(runner._frame.return_value, verify_menu=True)
    runner._new_deck.assert_called_once()
    assert counts(runner) == (1262, 1273, 1262, 217)
    assert "battle_finished" not in [call.args[0] for call in runner._event.call_args_list]
