"""Repeated job failures consume recovery budget until real battle completion."""

from typing import TYPE_CHECKING, cast
from unittest.mock import Mock

from pyclashbot.bot import worker
from pyclashbot.utils.process_ownership import OwnershipError

if TYPE_CHECKING:
    from multiprocessing.synchronize import Event


class FakeEvent:
    def __init__(self):
        self.flag = False

    def is_set(self):
        return self.flag

    def set(self):
        self.flag = True


def _worker():
    process = object.__new__(worker.WorkerProcess)
    process.shutdown_event = cast("Event", FakeEvent())
    process.jobs = {}
    process.stats_queue = Mock()
    process.session_log_path = "unused"
    return process


def test_recovery_boot_success_cannot_erase_failed_work_budget(monkeypatch):
    process = _worker()
    failures, boots = [], []

    def tree(_emulator, _logger, state, *_):
        if state == "restart":
            boots.append(state)
            return "start"
        failures.append(state)
        if len(failures) > 7:
            process.shutdown_event.set()
        return "restart"

    monkeypatch.setattr(worker, "state_tree", tree)
    process._run_bot_loop(None, {}, Mock())
    assert len(failures) == 5
    assert len(boots) == 4


def test_repeated_job_exceptions_remain_bounded_after_successful_boot(monkeypatch):
    process = _worker()
    failures = []

    def tree(_emulator, _logger, state, *_):
        if state == "restart":
            return "start"
        failures.append(state)
        if len(failures) > 7:
            process.shutdown_event.set()
        raise RuntimeError("job did not recover")

    monkeypatch.setattr(worker, "state_tree", tree)
    monkeypatch.setattr(worker.traceback, "print_exc", lambda: None)
    process._run_bot_loop(None, {}, Mock())
    assert len(failures) == 5


def test_real_end_fight_completion_resets_the_recovery_budget(monkeypatch):
    process = _worker()
    states = iter(["restart", "start"] * 4 + ["end_fight", "start"] + ["restart", "start"] * 4 + ["start"])
    calls = []

    def tree(_emulator, _logger, state, *_):
        calls.append(state)
        answer = next(states)
        if len(calls) == 19:
            process.shutdown_event.set()
        return answer

    monkeypatch.setattr(worker, "state_tree", tree)
    process._run_bot_loop(None, {}, Mock())
    assert len(calls) == 19
    assert "end_fight" in calls


def test_failed_end_fight_does_not_reset_budget(monkeypatch):
    process = _worker()
    failures = []

    def tree(_emulator, _logger, state, *_):
        if state == "restart":
            return "end_fight"
        failures.append(state)
        if len(failures) > 7:
            process.shutdown_event.set()
        return "restart"

    monkeypatch.setattr(worker, "state_tree", tree)
    process._run_bot_loop(None, {}, Mock())
    assert len(failures) == 5


def test_worker_device_lock_conflict_prevents_any_emulator_setup(monkeypatch):
    process = _worker()
    logger = Mock()
    setup = Mock()
    process._setup_emulator = setup
    monkeypatch.setattr(worker, "attach_worker_file_logging", lambda *_: None)
    monkeypatch.setattr(worker, "ProcessLogger", lambda *_: logger)
    monkeypatch.setattr(worker.traceback, "print_exc", lambda: None)

    class HeldLock:
        def __enter__(self):
            raise OwnershipError("device owned")

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(worker, "ExclusiveFileLock", lambda _: HeldLock())
    process.run()
    setup.assert_not_called()
    assert logger.error.called
