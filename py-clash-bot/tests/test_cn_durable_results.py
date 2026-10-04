"""Synthetic result publication survives each durable commit interruption."""

import hashlib
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from pyclashbot.bot import cn_random_mastery_loop as loop_module
from pyclashbot.bot.cn_1v1_loop import RecoveryExhausted
from pyclashbot.bot.cn_random_mastery_loop import RandomMasteryLoop
from pyclashbot.utils.persistence import append_jsonl_once, atomic_write_json, read_validated_json


class CommitInterruptedError(RuntimeError):
    """A synthetic process interruption at a named publication boundary."""


def runner_at(root, monkeypatch, *, restart=False):
    monkeypatch.setattr(loop_module, "ROOT", root)
    monkeypatch.setattr(loop_module.time, "sleep", lambda _: None)
    runner = RandomMasteryLoop.__new__(RandomMasteryLoop)
    runner.session = "20261004-000002" if restart else "20261004-000001"
    runner.work = root / "work" / "random-mastery" / runner.session
    runner.work.mkdir(parents=True, exist_ok=True)
    outputs = root / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    common = root / "work" / "random-mastery"
    runner.trace_path = outputs / "cn-random-mastery.jsonl"
    runner.checkpoint_path = common / "checkpoint.json"
    runner.result_outbox_path = common / "pending-result.json"
    runner.status_path = outputs / "status.json"
    runner.stop_path = common / "STOP"
    defaults = {
        "schema": 1,
        "completed": 4,
        "generated": 5,
        "closed_loops": 3,
        "total_claimed": 2,
        "pending_battle": True,
        "pending_mastery": False,
        "pending_claim_all": False,
        "reward_claim_id": None,
        "reward_receipts": [],
        "reward_slot": 0,
        "reward_phase": "",
    }
    state = read_validated_json(runner.checkpoint_path, runner._valid_checkpoint, default=defaults)
    for name, value in state.items():
        if name != "schema":
            setattr(runner, name, value)
    runner.state = "battle"
    runner.active_battle = runner.completed if runner.pending_mastery else runner.completed + 1
    runner.consecutive = 2
    runner.card_attempts = 8
    runner.cards_confirmed = 7
    runner.evidence_sequence = 0
    runner.experiment = {
        "rule_version": "test-rules",
        "strategy_hash": "a" * 64,
        "asset_hash": "b" * 64,
        "environment_hash": "c" * 64,
    }
    frame = np.zeros((633, 419, 3), dtype=np.uint8)
    runner._frame = lambda: frame
    runner.vision = SimpleNamespace(classify=lambda _: ("result", None), outcome=lambda _: "胜利")
    runner.logger = logging.getLogger("durable-result-tests")
    runner._event = lambda *_args, **_values: None
    runner._tap = lambda *_args: pytest.fail("A synthetic resumed result must not issue input")
    runner._play = lambda *_args: pytest.fail("A synthetic result must not deploy a card")
    runner._return_from_result = lambda: None
    runner._battle_frame_stalled = lambda *_args: False
    if not runner.checkpoint_path.exists():
        runner._checkpoint()
    return runner


def rows(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize(
    "cut",
    [
        "before_outbox",
        "after_outbox",
        "after_result_manifest",
        "after_trace",
        "before_checkpoint",
        "after_checkpoint",
        "after_committed_outbox",
    ],
)
def test_result_commit_replays_once_after_each_interruption(tmp_path, monkeypatch, cut):
    runner = runner_at(tmp_path, monkeypatch)
    real_write, real_append = loop_module.atomic_write_json, loop_module.append_jsonl_once
    tripped = []

    def interrupt():
        tripped.append(cut)
        raise CommitInterruptedError(cut)

    def write(path, value, **kwargs):
        path = Path(path)
        is_outbox = path == runner.result_outbox_path
        is_checkpoint = path == runner.checkpoint_path
        if not tripped and cut == "before_outbox" and is_outbox:
            interrupt()
        if not tripped and cut == "before_checkpoint" and is_checkpoint:
            interrupt()
        real_write(path, value, **kwargs)
        if not tripped and (
            (cut == "after_outbox" and is_outbox and not value.get("committed"))
            or (cut == "after_result_manifest" and path.name == "battle-0005.json")
            or (cut == "after_checkpoint" and is_checkpoint)
            or (cut == "after_committed_outbox" and is_outbox and value.get("committed"))
        ):
            interrupt()

    def append(path, row, **kwargs):
        outcome = real_append(path, row, **kwargs)
        if not tripped and cut == "after_trace":
            interrupt()
        return outcome

    with monkeypatch.context() as faults:
        faults.setattr(loop_module, "atomic_write_json", write)
        faults.setattr(loop_module, "append_jsonl_once", append)
        with pytest.raises(CommitInterruptedError, match=cut):
            runner._battle(resumed=True)
    assert tripped == [cut]
    recovered = runner_at(tmp_path, monkeypatch, restart=True)
    recovered._recover_result_outbox()
    if cut == "before_outbox":
        assert recovered.completed == 4 and recovered.pending_battle
        assert rows(recovered.trace_path) == []
        recovered._battle(resumed=True)
    assert recovered.completed == 5
    assert recovered.pending_mastery and not recovered.pending_battle
    assert len([row for row in rows(recovered.trace_path) if row["event"] == "battle_finished"]) == 1
    original_session = recovered.session if cut == "before_outbox" else runner.session
    manifest = tmp_path / "work" / "random-mastery" / original_session / "battle-0005.json"
    result = json.loads(manifest.read_text(encoding="utf-8"))
    evidence = result["evidence"]
    assert hashlib.sha256(Path(evidence["path"]).read_bytes()).hexdigest() == evidence["sha256"]
    # Each fresh startup sees the committed journal without counting another game.
    for _ in range(3):
        restarted = runner_at(tmp_path, monkeypatch, restart=True)
        restarted._recover_result_outbox()
        assert restarted.completed == 5 and restarted.pending_mastery
        assert len(rows(restarted.trace_path)) == 1


def valid_outbox(runner, battle=5):
    frame = np.zeros((633, 419, 3), dtype=np.uint8)
    result = {
        "outcome": "胜利",
        "card_attempts": 8,
        "cards_confirmed": 7,
        "generation": 5,
        "evidence": runner._save("result", frame),
    }
    row = {
        "event": "battle_finished",
        "event_id": f"result:{runner.session}:{battle}",
        "session": runner.session,
        "battle": battle,
        "finished_battle": battle,
        "time": "2026-10-04 00:00:01",
        "policy": loop_module.POLICY_VERSION,
        "mode": "classic_1v1",
        "experiment": runner.experiment,
        **result,
    }
    return {"schema": 1, "row": row, "result": result, "committed": False}


def test_nonconsecutive_outbox_is_rejected_before_any_publication(tmp_path, monkeypatch):
    runner = runner_at(tmp_path, monkeypatch)
    value = valid_outbox(runner, battle=7)
    atomic_write_json(runner.result_outbox_path, value)
    with pytest.raises(RecoveryExhausted):
        runner._recover_result_outbox()
    assert runner.completed == 4
    assert rows(runner.trace_path) == []
    assert not (runner.work / "battle-0007.json").exists()


@pytest.mark.parametrize("session", ["1", "20261340-999999", "20261004-000001-extra"])
def test_outbox_session_requires_a_real_numeric_date_identity(tmp_path, monkeypatch, session):
    runner = runner_at(tmp_path, monkeypatch)
    runner.session = session
    runner.work = tmp_path / "work" / "random-mastery" / session
    runner.work.mkdir(parents=True, exist_ok=True)
    atomic_write_json(runner.result_outbox_path, valid_outbox(runner))
    with pytest.raises((RecoveryExhausted, ValueError)):
        runner._recover_result_outbox()
    assert rows(runner.trace_path) == []


def test_outbox_rejects_tampered_result_picture_before_publication(tmp_path, monkeypatch):
    runner = runner_at(tmp_path, monkeypatch)
    value = valid_outbox(runner)
    atomic_write_json(runner.result_outbox_path, value)
    Path(value["result"]["evidence"]["path"]).write_bytes(b"damaged")
    with pytest.raises(RecoveryExhausted):
        runner._recover_result_outbox()
    assert rows(runner.trace_path) == [] and runner.completed == 4


def test_schema_invalid_checkpoint_is_not_copied_over_its_valid_backup(tmp_path, monkeypatch):
    runner = runner_at(tmp_path, monkeypatch)
    earlier = json.loads(runner.checkpoint_path.read_text(encoding="utf-8"))
    atomic_write_json(runner.checkpoint_path.with_suffix(".json.bak"), earlier)
    atomic_write_json(runner.checkpoint_path, {"schema": 1, "completed": "bad"})
    runner._checkpoint()
    assert json.loads(runner.checkpoint_path.with_suffix(".json.bak").read_text(encoding="utf-8")) == earlier


@pytest.mark.parametrize(
    "mutation",
    [
        {"result": None},
        {"result": "bad"},
        {"row": {}},
        {"schema": True},
        {"event": "battle_started"},
        {"event_id": "another-result"},
        {"session": "20261004-000001/../escape"},
        {"session": "1"},
        {"finished_battle": True},
        {"card_attempts": "8"},
        {"evidence": {"path": []}},
    ],
)
def test_invalid_outbox_fails_closed_without_writing_history(tmp_path, monkeypatch, mutation):
    runner = runner_at(tmp_path, monkeypatch)
    value = valid_outbox(runner)
    for key, change in mutation.items():
        if key in ("result", "row", "schema"):
            value[key] = change
        else:
            value["row"][key] = change
    atomic_write_json(runner.result_outbox_path, value)
    with pytest.raises((RecoveryExhausted, ValueError)):
        runner._recover_result_outbox()
    assert runner.completed == 4 and runner.pending_battle
    assert rows(runner.trace_path) == []
    assert not (runner.work / "battle-0005.json").exists()


def test_critical_images_remain_immutable_after_ring_wrap(tmp_path, monkeypatch):
    runner = runner_at(tmp_path, monkeypatch)
    first = np.zeros((633, 419, 3), dtype=np.uint8)
    preserved = [runner._save(name, first) for name in ("result", "recovery", "mismatch", "frozen-battle")]
    for index in range(110):
        runner._save("battle", np.full_like(first, index))
    for evidence in preserved:
        assert hashlib.sha256(Path(evidence["path"]).read_bytes()).hexdigest() == evidence["sha256"]
        assert Path(evidence["path"]).parent.name == "evidence"


def test_repeated_immutable_picture_never_reopens_the_existing_file_for_writing(tmp_path, monkeypatch):
    runner = runner_at(tmp_path, monkeypatch)
    frame = np.zeros((633, 419, 3), dtype=np.uint8)
    evidence = runner._save("result", frame)
    path = Path(evidence["path"])
    old = path.read_bytes()
    original_open = Path.open

    def deny_mutation(source, mode="r", *args, **kwargs):
        if source == path and any(letter in mode for letter in ("w", "a", "+")):
            pytest.fail("An existing verified immutable picture must not be truncated")
        return original_open(source, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny_mutation)
    assert runner._save("result", frame) == evidence
    assert path.read_bytes() == old


def test_append_once_separates_interrupted_final_json_and_keeps_one_result(tmp_path):
    path = tmp_path / "trace.jsonl"
    path.write_bytes(b'{"event":"battle_started","session":')
    row = {"event": "battle_finished", "event_id": "result:20261004-000001:1", "finished_battle": 1}
    assert append_jsonl_once(path, row)
    assert not append_jsonl_once(path, row)
    lines = path.read_bytes().splitlines()
    assert len(lines) == 2 and json.loads(lines[1]) == row


def test_complete_json_without_newline_is_not_duplicated_by_recovery(tmp_path):
    path = tmp_path / "trace.jsonl"
    row = {"event": "battle_finished", "event_id": "result:20261004-000001:1", "finished_battle": 1}
    path.write_text(json.dumps(row), encoding="utf-8")
    append_jsonl_once(path, row)
    complete = [json.loads(line) for line in path.read_bytes().splitlines()]
    assert len(complete) == 1 and complete[0] == row
