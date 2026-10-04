"""Offline process identity, entrypoint cleanup and actual OS lock exclusion."""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import psutil
import pytest

from pyclashbot.utils import process_ownership as ownership
from scripts import run_cn_1v1 as run
from scripts import watch_cn_1v1 as watch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_cn_1v1.py"


class FakeProcess:
    def __init__(self, command, *, created=100.0, executable=None, running=True, pid=123):
        self.command = command
        self.created = created
        self.executable = executable or command[0]
        self.running = running
        self.pid = pid
        self.terminate = Mock()

    def create_time(self):
        return self.created

    def cmdline(self):
        return self.command

    def exe(self):
        return self.executable

    def cwd(self):
        return str(ROOT)

    def is_running(self):
        return self.running


class FakeLock:
    def __init__(self, *_):
        self.acquired = False
        self.released = False

    def acquire(self):
        self.acquired = True
        return self

    def release(self):
        self.released = True


def _argv(tmp_path, *, watchdog=False):
    arguments = [
        "bot",
        "--adb",
        "unused-adb",
        "--serial",
        "fake-device",
        "--strategy",
        "567",
        "--log",
        str(tmp_path / "battle.log"),
    ]
    if watchdog:
        arguments += [
            "--memuc",
            "unused-memuc",
            "--watchdog-log",
            str(tmp_path / "watch.log"),
            "--pid-file",
            str(tmp_path / "processes.json"),
        ]
    return arguments


@pytest.mark.parametrize(
    "command,created,running,accepted",
    [
        ([sys.executable, str(SCRIPT)], 100.0, True, True),
        ([sys.executable, str(SCRIPT)], 101.0, True, False),
        ([sys.executable, str(SCRIPT)], 100.0, False, False),
        ([sys.executable, str(ROOT / "other/run_cn_1v1.py")], 100.0, True, False),
        ([sys.executable, str(ROOT / "other.py"), "--input", str(SCRIPT)], 100.0, True, False),
        ([str(ROOT / "unrelated.exe"), "--component", "run_cn_1v1.py"], 100.0, True, False),
        ([str(ROOT / "unrelated.exe"), str(SCRIPT)], 100.0, True, False),
    ],
)
def test_verification_requires_exact_entrypoint_executable_and_creation(
    monkeypatch, command, created, running, accepted
):
    process = FakeProcess(command, created=created, running=running)
    monkeypatch.setattr(ownership.psutil, "Process", lambda _: process)
    assert (ownership.verified_process(123, SCRIPT, 100.0) is not None) is accepted


@pytest.mark.parametrize("created", [None, float("nan"), float("inf"), True, "not-a-time"])
def test_incomplete_or_nonfinite_creation_identity_is_rejected(monkeypatch, created):
    process = FakeProcess([sys.executable, str(SCRIPT)])
    monkeypatch.setattr(ownership.psutil, "Process", lambda _: process)
    assert ownership.verified_process(123, SCRIPT, created) is None


def test_inaccessible_process_identity_is_not_assumed(monkeypatch):
    def denied(_):
        raise psutil.AccessDenied(123)

    monkeypatch.setattr(ownership.psutil, "Process", denied)
    assert ownership.verified_process(123, SCRIPT, 100) is None


@pytest.mark.parametrize(
    "same_executable,component,accepted",
    [
        (True, "run_cn_1v1.py", True),
        (False, "run_cn_1v1.py", False),
        (True, "other.py", False),
    ],
)
def test_frozen_component_is_bound_to_the_installed_executable(
    tmp_path, monkeypatch, same_executable, component, accepted
):
    trusted = tmp_path / "installed/py-clash-bot.exe"
    executable = trusted if same_executable else tmp_path / "unrelated.exe"
    process = FakeProcess([str(executable), "--component", component])
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(trusted))
    monkeypatch.setattr(ownership, "load_runtime_config", lambda: SimpleNamespace(python=trusted))
    monkeypatch.setattr(ownership.psutil, "Process", lambda _: process)
    assert (ownership.verified_process(123, SCRIPT, 100) is not None) is accepted


def test_relative_source_entrypoint_resolves_against_process_working_directory(monkeypatch):
    process = FakeProcess([sys.executable, "scripts/run_cn_1v1.py"])
    monkeypatch.setattr(ownership.psutil, "Process", lambda _: process)
    assert ownership.verified_process(123, SCRIPT, 100) is not None


def test_real_os_lock_excludes_a_second_offline_process_and_releases(tmp_path):
    path = tmp_path / "exclusive.lock"
    code = """import sys
from pathlib import Path
from pyclashbot.utils.process_ownership import ExclusiveFileLock, OwnershipError
try:
    lock=ExclusiveFileLock(Path(sys.argv[1])).acquire()
except OwnershipError:
    sys.exit(78)
lock.release()
sys.exit(0)
"""
    lock = ownership.ExclusiveFileLock(path).acquire()
    try:
        held = subprocess.run(
            [sys.executable, "-c", code, str(path)],
            cwd=ROOT,
            timeout=10,
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        assert held.returncode == 78, held.stderr.decode(errors="replace")
    finally:
        lock.release()
    released = subprocess.run(
        [sys.executable, "-c", code, str(path)],
        cwd=ROOT,
        timeout=10,
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    assert released.returncode == 0, released.stderr.decode(errors="replace")


def test_second_watchdog_cannot_overwrite_first_process_record(tmp_path, monkeypatch):
    state_path = tmp_path / "processes.json"
    original = {"watchdog_pid": 999, "runner_pid": 998, "phase": "running"}
    state_path.write_text(json.dumps(original), encoding="utf-8")
    before = state_path.read_bytes()
    lock = ownership.ExclusiveFileLock(state_path.with_suffix(".lock")).acquire()
    monkeypatch.setattr(watch.sys, "argv", _argv(tmp_path, watchdog=True))
    spawn = Mock()
    monkeypatch.setattr(watch.subprocess, "Popen", spawn)
    try:
        with pytest.raises(SystemExit) as error:
            watch.main()
        assert error.value.code == 78
    finally:
        lock.release()
    assert state_path.read_bytes() == before
    spawn.assert_not_called()


def test_runner_releases_device_lock_when_logging_setup_fails(tmp_path, monkeypatch):
    lock = FakeLock()
    monkeypatch.setattr(run, "ExclusiveFileLock", lambda *_: lock)
    monkeypatch.setattr(run, "device_lock_path", lambda: tmp_path / "device.lock")
    monkeypatch.setattr(run.logging, "FileHandler", Mock(side_effect=PermissionError("log path blocked")))
    monkeypatch.setattr(run, "ChineseOneVOneLoop", Mock())
    monkeypatch.setattr(sys, "argv", _argv(tmp_path))
    with pytest.raises(PermissionError):
        run.main()
    assert lock.acquired and lock.released


def test_runner_constructor_failure_releases_device_lock(tmp_path, monkeypatch):
    lock = FakeLock()
    monkeypatch.setattr(run, "ExclusiveFileLock", lambda *_: lock)
    monkeypatch.setattr(run, "device_lock_path", lambda: tmp_path / "device.lock")
    monkeypatch.setattr(run.logging, "basicConfig", lambda **_: None)
    monkeypatch.setattr(run, "ChineseOneVOneLoop", Mock(side_effect=RuntimeError("invalid configuration")))
    monkeypatch.setattr(sys, "argv", _argv(tmp_path))
    with pytest.raises(SystemExit) as error:
        run.main()
    assert error.value.code == 78
    assert lock.released


def _watch_setup(tmp_path, monkeypatch, *, execution_state=None):
    lock = FakeLock()
    monkeypatch.setattr(watch, "ExclusiveFileLock", lambda *_: lock)
    monkeypatch.setattr(watch.logging, "basicConfig", lambda **_: None)
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, watchdog=True))
    monkeypatch.setattr(
        watch,
        "ctypes",
        SimpleNamespace(
            windll=SimpleNamespace(kernel32=SimpleNamespace(SetThreadExecutionState=execution_state or (lambda _: 1)))
        ),
    )
    child = SimpleNamespace(pid=123, wait=Mock(return_value=0), poll=Mock(return_value=None), terminate=Mock())
    monkeypatch.setattr(watch.subprocess, "Popen", lambda *_, **__: child)
    monkeypatch.setattr(watch.psutil, "Process", lambda *_: SimpleNamespace(children=lambda **_: []))
    monkeypatch.setattr(
        watch, "process_record", lambda pid, script: {"pid": pid, "created_at": 100, "script": str(script)}
    )
    return lock, child


def test_watchdog_cleanup_error_still_releases_lock(tmp_path, monkeypatch):
    def power_state(value):
        if value == watch.ES_CONTINUOUS:
            raise OSError("sleep-state cleanup failed")
        return 1

    lock, _ = _watch_setup(tmp_path, monkeypatch, execution_state=power_state)
    try:
        watch.main()
    except OSError:
        pass
    assert lock.released


def test_watchdog_identity_publication_failure_does_not_leave_untracked_runner(tmp_path, monkeypatch):
    lock, child = _watch_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(watch, "process_record", Mock(side_effect=psutil.AccessDenied(123)))
    try:
        watch.main()
    except psutil.Error:
        pass
    assert lock.released
    child.terminate.assert_called_once()


def test_failed_spawn_cleanup_only_touches_verified_bot_descendants(monkeypatch):
    owned = FakeProcess([sys.executable, str(SCRIPT)], pid=321)
    unrelated = FakeProcess([sys.executable, str(ROOT / "unrelated.py")], pid=322)
    parent = SimpleNamespace(children=lambda **_: [owned, unrelated])
    monkeypatch.setattr(
        watch.psutil, "Process", lambda pid: parent if pid == 123 else owned if pid == 321 else unrelated
    )
    spawned = SimpleNamespace(pid=123, poll=Mock(return_value=None), terminate=Mock(), wait=Mock(return_value=0))
    watch._cleanup_failed_spawn(spawned)
    owned.terminate.assert_called_once()
    unrelated.terminate.assert_not_called()
    spawned.terminate.assert_called_once()
