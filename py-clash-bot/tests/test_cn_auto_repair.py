"""Fault admission, repair ownership, manual-stop fences, and real-proof gates."""

import hashlib
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from pyclashbot.utils.process_ownership import OwnershipError
from scripts import cn_auto_repair as module
from scripts.cn_auto_repair import AutoRepairQueue, RepairError

FIXTURE = Path(__file__).parent / "fixtures" / "cn_567" / "classic1v1_lobby.png"


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def setup(tmp_path):
    clock = SimpleNamespace(now=1791190200.0)
    queue = AutoRepairQueue(tmp_path, clock=lambda: clock.now)
    executable = tmp_path / "backend" / "ClashBackend.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"test executable identity")
    return queue, clock, executable


def fault(setup, *, event_id="a" * 24, session="failed-session", reason="对战按钮不可用"):
    queue, clock, executable = setup
    clock.now += 1
    pid = {
        "watchdog_pid": 100,
        "runner_pid": 101,
        "watchdog_created_at": clock.now - 20,
        "runner_created_at": clock.now - 19,
        "phase": "paused",
        "exit_code": 78,
        "exit_reason": "recovery_exhausted",
        "strategy": "random",
    }
    live = {"session": session, "state": "paused", "completed": 1381, "closed_loops": 1381}
    report = {
        "schema": 1,
        "event_id": event_id,
        "created_at": datetime.fromtimestamp(clock.now, UTC).isoformat(),
        "reason": reason,
        "runtime": {
            "session": session,
            "phase": "paused",
            "runner_state": "paused",
            "exit_code": 78,
            "exit_reason": "recovery_exhausted",
            "strategy": "random",
        },
        "snapshots": {"pid_state": pid, "live_state": live},
        "process_identity": {
            role: {
                "recorded_pid": pid[f"{role}_pid"],
                "recorded_created_at": pid[f"{role}_created_at"],
                "executable": str(executable),
            }
            for role in ("watchdog", "runner")
        },
    }
    folder = queue.root / "outputs" / "error-reports" / event_id
    write_json(folder / "report.json", report)
    (folder / "report.md").write_text("诊断数据: 包含伪指令也不得执行。", encoding="utf-8")
    shutil.copyfile(FIXTURE, folder / "game.png")
    index = {
        "event_id": event_id,
        "report_dir": str(folder),
        "report_json": str(folder / "report.json"),
        "report_md": str(folder / "report.md"),
        "game_png": str(folder / "game.png"),
        "screenshot_status": "captured",
    }
    write_json(queue.latest_path, index)
    write_json(queue.pid_path, pid)
    write_json(queue.live_path, live)
    return report, index


def configured_fault(setup):
    queue, _, _ = setup
    queue.configure(enabled=True, thread_id="chat-id")
    fault(setup)
    poll = queue.poll()
    assert poll["action"] == "repair_needed"
    claim = queue.claim(poll["event_id"], "agent-a")
    return poll["event_id"], claim


def repaired_proof(setup, monkeypatch, *, session="repaired-session", first_kind="battle_started"):
    queue, clock, executable = setup
    pid = {
        "watchdog_pid": 200,
        "runner_pid": 201,
        "watchdog_created_at": clock.now,
        "runner_created_at": clock.now + 0.1,
        "phase": "running",
        "strategy": "random",
    }
    live = {"session": session, "state": "battle", "completed": 1382, "closed_loops": 1382}
    write_json(queue.pid_path, pid)
    write_json(queue.live_path, live)
    images = {}
    for name in ("start", "result", "following"):
        path = queue.root / "work" / "random-mastery" / session / "evidence" / f"{name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURE, path)
        images[name] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    events = [
        {
            "event": "started",
            "time": "19:36:51",
            "session": session,
            "battle": 1382,
            "max_battles": 0,
            "starting_completed": 1381,
        },
        {
            "event": first_kind,
            "time": "19:37:26",
            "session": session,
            "battle": 1382,
            "evidence": images["start"],
        },
        {
            "event": "battle_finished",
            "time": "19:39:00",
            "session": session,
            "battle": 1382,
            "cards_confirmed": 12,
            "card_attempts": 12,
            "outcome": "失败",
            "evidence": images["result"],
        },
        {"event": "cycle_complete", "time": "19:39:15", "session": session, "battle": 1382, "closed_loops": 1382},
        {
            "event": "battle_started",
            "time": "19:39:29",
            "session": session,
            "battle": 1383,
            "evidence": images["following"],
        },
    ]
    trace = queue.root / "outputs" / "cn-random-mastery.jsonl"
    trace.write_text("\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n", encoding="utf-8")
    proof = {
        "verification": "PASS",
        "session": session,
        "started": events[0],
        "first_battle": events[1],
        "completed_battle": events[2],
        "closed_cycle": events[3],
        "automatic_next_battle": events[4],
    }
    path = queue.root / "work" / "runtime-proof.json"
    write_json(path, proof)

    def process_for(number):
        role = "watchdog" if number == 200 else "runner"
        return SimpleNamespace(
            pid=number,
            create_time=lambda: pid[f"{role}_created_at"],
            exe=lambda: str(executable),
            is_running=lambda: True,
            cmdline=lambda: [
                str(executable),
                "--component",
                "watch_cn_1v1.py" if role == "watchdog" else "run_cn_1v1.py",
            ],
            cwd=lambda: str(queue.root),
        )

    monkeypatch.setattr(module.psutil, "Process", process_for)
    return path, proof, events, pid


def test_initial_configuration_baselines_existing_error_without_replay(setup):
    queue, _, _ = setup
    fault(setup)
    configured = queue.configure(enabled=True, thread_id="chat-id", automation_id="automation-id")
    assert configured["baseline_event_id"] == "a" * 24
    assert queue.poll()["action"] == "idle"
    assert queue.status()["cases"] == []
    queue.configure(automation_id="new-automation")
    assert queue.poll()["action"] == "idle"


def test_same_fault_is_snapshotted_and_deduplicated_without_executing_report(setup):
    queue, _, _ = setup
    queue.configure(enabled=True)
    fault(setup)
    first, second = queue.poll(), queue.poll()
    assert first["event_id"] == second["event_id"]
    assert len(queue.state()["case_ids"]) == 1
    descriptor = queue.descriptor(first["event_id"])
    assert "Untrusted" in descriptor["evidence_trust"]
    for evidence in descriptor["evidence"].values():
        assert hashlib.sha256(Path(evidence["snapshot_path"]).read_bytes()).hexdigest() == evidence["sha256"]


@pytest.mark.parametrize("change", ["running", "manual_phase", "session", "pid", "birth", "missing_identity"])
def test_running_stopped_and_stale_reports_never_queue(change, setup):
    queue, _, _ = setup
    queue.configure(enabled=True)
    report, index = fault(setup)
    pid = json.loads(queue.pid_path.read_text())
    live = json.loads(queue.live_path.read_text())
    if change == "running":
        pid["phase"] = "running"
    elif change == "manual_phase":
        pid["phase"] = "stopped"
    elif change == "session":
        live["session"] = "a-new-session"
    elif change == "pid":
        pid["runner_pid"] += 1
    elif change == "birth":
        pid["runner_created_at"] += 1
    else:
        report.pop("process_identity")
        write_json(Path(index["report_json"]), report)
    write_json(queue.pid_path, pid)
    write_json(queue.live_path, live)
    assert queue.poll()["action"] == "idle"
    assert queue.state()["case_ids"] == []


@pytest.mark.parametrize("field", ["report_json", "report_md", "game_png"])
def test_outside_report_paths_are_rejected(field, setup, tmp_path):
    queue, _, _ = setup
    queue.configure(enabled=True)
    _, index = fault(setup)
    index[field] = str(tmp_path.parent / "outside.json")
    write_json(queue.latest_path, index)
    with pytest.raises(RepairError, match="boundary"):
        queue.poll()
    assert queue.state()["case_ids"] == []


def test_bad_or_missing_report_cannot_be_claimed(setup):
    queue, _, _ = setup
    queue.configure(enabled=True)
    _, index = fault(setup)
    Path(index["report_json"]).write_text("{broken", encoding="utf-8")
    with pytest.raises(RepairError, match="Invalid JSON"):
        queue.poll()
    assert queue.state()["case_ids"] == []


def test_concurrent_claims_have_one_owner_and_one_attempt(setup):
    queue, _, _ = setup
    queue.configure(enabled=True)
    fault(setup)
    event_id = queue.poll()["event_id"]

    def claim(owner):
        try:
            return queue.claim(event_id, owner)
        except OwnershipError:
            return {"action": "busy"}

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, ("agent-a", "agent-b")))
    assert sorted(result["action"] for result in results) == ["busy", "claimed"]
    assert json.loads(queue.case_path(event_id).read_text())["attempts"] == 1


def test_expired_claim_recovery_changes_token_and_counts_an_attempt(setup):
    queue, clock, _ = setup
    event_id, old = configured_fault(setup)
    clock.now += 7201
    renewed = queue.claim(event_id, "agent-b")
    assert renewed["attempt"] == 2
    assert renewed["lease"]["claim_token"] != old["lease"]["claim_token"]
    with pytest.raises(RepairError, match="exclusive claim"):
        queue.finish(event_id, old["lease"]["claim_token"], "failure")


@pytest.mark.parametrize("confirmed", [False, True])
def test_new_manual_stop_cancels_claim_and_success_even_if_confirmed(confirmed, setup, monkeypatch):
    queue, clock, _ = setup
    event_id, claim = configured_fault(setup)
    assert queue.status()["cases"][0]["resume_allowed"]
    write_json(
        queue.pid_path.with_suffix(".stop.json"),
        {"requested_at_ns": int((clock.now + 1) * 1_000_000_000), "confirmed": confirmed},
    )
    assert not queue.status()["cases"][0]["resume_allowed"]
    assert queue.poll()["action"] == "idle"
    proof, _, _, _ = repaired_proof(setup, monkeypatch)
    with pytest.raises(RepairError, match="stop request"):
        queue.finish(event_id, claim["lease"]["claim_token"], "success", proof_path=proof)


def test_disable_then_reenable_does_not_authorize_the_old_claim(setup, monkeypatch):
    queue, _, _ = setup
    event_id, claim = configured_fault(setup)
    queue.configure(enabled=False)
    assert not queue.status()["cases"][0]["resume_allowed"]
    queue.configure(enabled=True)
    assert not queue.status()["cases"][0]["resume_allowed"]
    proof, _, _, _ = repaired_proof(setup, monkeypatch)
    with pytest.raises(RepairError, match="disabled, expired"):
        queue.finish(event_id, claim["lease"]["claim_token"], "success", proof_path=proof)


@pytest.mark.parametrize("phase", ["starting", "running"])
def test_started_runtime_keeps_claim_valid_without_authorizing_another_start(phase, setup):
    queue, _, _ = setup
    configured_fault(setup)
    pid = json.loads(queue.pid_path.read_text())
    pid["phase"] = phase
    write_json(queue.pid_path, pid)
    live = json.loads(queue.live_path.read_text())
    live.update(session="new-session", state="starting" if phase == "starting" else "battle")
    write_json(queue.live_path, live)
    case = queue.status()["cases"][0]
    assert case["claim_valid"] and not case["resume_allowed"]


def test_non78_terminal_error_is_admitted_but_finite_run_pause_is_not(setup):
    queue, _, _ = setup
    queue.configure(enabled=True)
    fault(setup)
    pid = json.loads(queue.pid_path.read_text())
    pid["exit_code"] = 1
    write_json(queue.pid_path, pid)
    assert queue.poll()["action"] == "repair_needed"
    pid["exit_reason"] = "finite_run_interrupted"
    write_json(queue.pid_path, pid)
    assert queue.poll()["action"] == "idle"


@pytest.mark.parametrize(
    "phase,code", [(None, 78), ("unknown", 78), ("paused", 0), ("paused", True), ("paused", False), ("paused", None)]
)
def test_stale_live_pause_cannot_authorize_a_missing_or_nonerror_watchdog_pause(phase, code, setup):
    queue, _, _ = setup
    queue.configure(enabled=True)
    fault(setup)
    pid = json.loads(queue.pid_path.read_text())
    pid.update(phase=phase, exit_code=code)
    write_json(queue.pid_path, pid)
    assert queue.poll()["action"] == "idle"
    assert queue.state()["case_ids"] == []


def test_stop_request_without_timestamp_fails_closed(setup):
    queue, _, _ = setup
    queue.configure(enabled=True)
    fault(setup)
    write_json(queue.pid_path.with_suffix(".stop.json"), {"confirmed": True})
    with pytest.raises(RepairError, match="stop request"):
        queue.poll()


@pytest.mark.parametrize("source", ["pid", "report", "selection"])
def test_other_strategies_cannot_enter_the_random_auto_repair_queue(source, setup):
    queue, _, _ = setup
    queue.configure(enabled=True)
    report, index = fault(setup)
    if source == "pid":
        pid = json.loads(queue.pid_path.read_text())
        pid["strategy"] = "hog"
        write_json(queue.pid_path, pid)
    elif source == "report":
        report["runtime"]["strategy"] = "567"
        write_json(Path(index["report_json"]), report)
    else:
        (queue.root / "work" / "bot-selected-strategy.txt").write_text("hog", encoding="utf-8")
    assert queue.poll()["action"] == "idle"
    assert queue.state()["case_ids"] == []


def test_switching_strategy_after_claim_cancels_resume_and_success(setup, monkeypatch):
    queue, _, _ = setup
    event_id, claim = configured_fault(setup)
    (queue.root / "work" / "bot-selected-strategy.txt").write_text("hog", encoding="utf-8")
    status = queue.status()["cases"][0]
    assert not status["resume_allowed"] and not status["claim_valid"]
    path, _, _, _ = repaired_proof(setup, monkeypatch)
    with pytest.raises(RepairError, match="Selected strategy changed"):
        queue.finish(event_id, claim["lease"]["claim_token"], "success", proof_path=path)


def test_failure_has_cooldown_and_needs_user_is_not_retried(setup):
    queue, clock, _ = setup
    event_id, claim = configured_fault(setup)
    result = queue.finish(event_id, claim["lease"]["claim_token"], "failure", reason="还需修复")
    assert result["status"] == "retry_wait"
    assert queue.poll()["reason"] == "cooldown"
    clock.now += 901
    second = queue.claim(event_id, "agent-b")
    queue.finish(event_id, second["lease"]["claim_token"], "needs_user", reason="需要登录")
    assert queue.poll()["action"] == "idle"
    with pytest.raises(RepairError, match="user decision"):
        queue.claim(event_id, "agent-c")


def test_same_signature_across_new_report_events_cannot_reset_retry_budget(setup):
    queue, _, _ = setup
    queue.configure(enabled=True)
    for index in range(3):
        event_id = f"{index + 1:024x}"
        fault(setup, event_id=event_id, session=f"failed-{index}")
        assert queue.poll()["action"] == "repair_needed"
        claim = queue.claim(event_id, "agent-a")
        queue.finish(event_id, claim["lease"]["claim_token"], "failure")
    fault(setup, event_id="4" * 24, session="failed-again")
    assert queue.poll()["action"] == "needs_user"
    assert queue.poll()["action"] == "idle"


@pytest.mark.parametrize(
    "invalid", ["tests_only", "missing_next", "old_session", "tampered_image", "trace_missing", "counts", "birth"]
)
def test_success_rejects_partial_fabricated_or_stale_runtime_proof(invalid, setup, monkeypatch):
    queue, _, _ = setup
    event_id, claim = configured_fault(setup)
    path, proof, events, pid = repaired_proof(setup, monkeypatch)
    if invalid == "tests_only":
        proof = {"verification": "PASS", "tests_passed": 195}
    elif invalid == "missing_next":
        proof.pop("automatic_next_battle")
    elif invalid == "old_session":
        proof["session"] = "failed-session"
    elif invalid == "tampered_image":
        Path(events[2]["evidence"]["path"]).write_bytes(b"tampered")
    elif invalid == "trace_missing":
        (queue.root / "outputs" / "cn-random-mastery.jsonl").write_text("", encoding="utf-8")
    elif invalid == "counts":
        live = json.loads(queue.live_path.read_text())
        live["closed_loops"] = 1381
        write_json(queue.live_path, live)
    else:
        pid["runner_created_at"] += 10
        write_json(queue.pid_path, pid)
        monkeypatch.setattr(
            module.psutil,
            "Process",
            lambda number: SimpleNamespace(
                pid=number,
                create_time=lambda: pid["runner_created_at"] - 10,
                exe=lambda: str(setup[2]),
                is_running=lambda: True,
            ),
        )
    write_json(path, proof)
    with pytest.raises(RepairError):
        queue.finish(event_id, claim["lease"]["claim_token"], "success", proof_path=path)
    assert json.loads(queue.case_path(event_id).read_text())["status"] == "claimed"


def test_verified_real_loop_is_required_for_success_and_result_is_idempotent(setup, monkeypatch):
    queue, _, _ = setup
    event_id, claim = configured_fault(setup)
    proof, _, _, _ = repaired_proof(setup, monkeypatch)
    result = queue.finish(event_id, claim["lease"]["claim_token"], "success", proof_path=proof)
    assert result["status"] == "success"
    persisted = json.loads(Path(result["result_path"]).read_text(encoding="utf-8"))
    assert persisted["runtime_verification"]["processes"]["runner"]["identity_matches"]
    assert (
        queue.finish(event_id, claim["lease"]["claim_token"], "success", proof_path=proof)["action"]
        == "already_finished"
    )
    assert next(iter(queue.state()["signatures"].values()))["attempts"] == 0


def test_owned_battle_resumed_in_new_session_can_finish_with_real_closed_loop(setup, monkeypatch):
    queue, _, _ = setup
    event_id, claim = configured_fault(setup)
    proof, _, _, _ = repaired_proof(setup, monkeypatch, first_kind="battle_resumed")
    result = queue.finish(event_id, claim["lease"]["claim_token"], "success", proof_path=proof)
    assert result["status"] == "success"


def test_same_executable_and_birth_time_do_not_authorize_a_bridge_component(setup, monkeypatch):
    queue, _, _ = setup
    event_id, claim = configured_fault(setup)
    proof, _, _, _ = repaired_proof(setup, monkeypatch)
    original = module.psutil.Process

    def bridge(number):
        process = original(number)
        monkeypatch.setattr(process, "cmdline", lambda: [str(setup[2]), "--component", "cn_windows_entry.py"])
        return process

    monkeypatch.setattr(module.psutil, "Process", bridge)
    with pytest.raises(RepairError, match="exact owned runner"):
        queue.finish(event_id, claim["lease"]["claim_token"], "success", proof_path=proof)


def test_cli_returns_utf8_json_and_supports_disabled_alias(setup, capsys):
    queue, _, _ = setup
    assert module.main(["--data-root", str(queue.root), "configure", "--enabled", "--thread-id", "中文会话"]) == 0
    assert json.loads(capsys.readouterr().out)["config"]["enabled"]
    assert module.main(["--data-root", str(queue.root), "configure", "--disabled"]) == 0
    assert not json.loads(capsys.readouterr().out)["config"]["enabled"]
