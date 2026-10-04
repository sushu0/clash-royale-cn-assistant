"""Offline cancellation and actual, isolated OS process-tree stop regressions."""

import json
import os
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import psutil
import pytest

from pyclashbot.utils import process_ownership as ownership
from scripts import cn_bot_control as control
from scripts import stop_cn_1v1 as stop
from scripts import watch_cn_1v1 as watch


def test_stop_without_pid_file_is_idempotent_and_does_not_touch_drain(tmp_path):
    pid_file = tmp_path / "pids.json"
    drain = tmp_path / "DRAIN"
    drain.write_text("keep calibration drain", encoding="utf-8")
    assert stop.stop_bot(pid_file) == []
    assert stop.stop_bot(pid_file) == []
    state = json.loads(pid_file.read_text(encoding="utf-8"))
    assert state["phase"] == "stopped" and state["exit_reason"] == "user_stopped"
    assert drain.read_text(encoding="utf-8") == "keep calibration drain"
    requested = json.loads(pid_file.with_suffix(".stop.json").read_text(encoding="utf-8"))["requested_at_ns"]
    assert ownership.stop_requested(pid_file, requested - 1)
    assert not ownership.stop_requested(pid_file, requested + 1)


def test_explicit_stop_wins_over_stale_random_pause_status(tmp_path, monkeypatch):
    pid_file = tmp_path / "pids.json"
    pid_file.write_text(json.dumps({"watchdog_pid": 0, "runner_pid": 0, "exit_reason": "user_stopped"}))
    monkeypatch.setattr(control, "PID_FILE", pid_file)
    monkeypatch.setattr(control, "_is_our_process", lambda *_args: False)
    monkeypatch.setattr(control, "selected_strategy", lambda: "random")
    monkeypatch.setattr(control, "read_random_status", lambda: {"state": "paused"})
    assert control.bot_state() == "stopped"


def test_cancelled_start_does_not_send_input_or_spawn_watchdog(monkeypatch):
    cancel = threading.Event()
    cancel.set()
    command = Mock()
    spawn = Mock()
    monkeypatch.setattr(control, "_run_cancellable", command)
    monkeypatch.setattr(control.subprocess, "Popen", spawn)
    with pytest.raises(RuntimeError, match="启动已取消"):
        control.ControlWindow._start_worker(cancel_event=cancel)
    command.assert_not_called()
    spawn.assert_not_called()


def test_startup_blocking_command_is_interrupted_promptly_without_an_emulator():
    cancel = threading.Event()
    timer = threading.Timer(0.15, cancel.set)
    started = time.monotonic()
    timer.start()
    try:
        with pytest.raises(RuntimeError, match="启动已取消"):
            control._run_cancellable([sys.executable, "-c", "import time; time.sleep(30)"], 20, cancel)
    finally:
        timer.cancel()
        timer.join(2)
    assert time.monotonic() - started < 2


def test_unpublished_watchdog_identity_access_denied_is_not_reported_stopped(tmp_path, monkeypatch):
    pid_file = tmp_path / "pids.json"
    candidate = SimpleNamespace(
        create_time=Mock(side_effect=psutil.AccessDenied(22)),
        exe=lambda: sys.executable,
        cmdline=lambda: [sys.executable, str(stop.RESOURCE_ROOT / "scripts/watch_cn_1v1.py")],
    )
    monkeypatch.setattr(stop.psutil, "Process", lambda _pid: candidate)
    with pytest.raises(RuntimeError, match=r"身份.*尚未确认"):
        stop.stop_bot(pid_file, pending_watchdog=(22, 100.0))
    assert not pid_file.exists()
    assert json.loads(pid_file.with_suffix(".stop.json").read_text())["confirmed"] is False


def test_watchdog_does_not_launch_after_late_stop_before_pid_publication(tmp_path, monkeypatch):
    pid_file = tmp_path / "pids.json"
    stop.stop_bot(pid_file)
    started = json.loads(pid_file.with_suffix(".stop.json").read_text())["requested_at_ns"] - 1
    monkeypatch.setattr(
        watch.sys,
        "argv",
        [
            "watch",
            "--adb",
            "unused",
            "--serial",
            "offline",
            "--memuc",
            "unused",
            "--log",
            str(tmp_path / "battle.log"),
            "--watchdog-log",
            str(tmp_path / "watch.log"),
            "--pid-file",
            str(pid_file),
            "--started-at-ns",
            str(started),
        ],
    )
    monkeypatch.setattr(watch.logging, "basicConfig", lambda **_kwargs: None)
    spawn = Mock()
    monkeypatch.setattr(watch.subprocess, "Popen", spawn)
    watch.main()
    spawn.assert_not_called()
    assert json.loads(pid_file.read_text())["exit_reason"] == "user_stopped"


@pytest.mark.skipif(os.name != "nt", reason="Windows process suspension and termination acceptance")
def test_stop_terminates_a_real_respawning_watchdog_and_all_children_only(tmp_path, monkeypatch):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    runner = scripts / "run_cn_1v1.py"
    watchdog = scripts / "watch_cn_1v1.py"
    runner.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    record = tmp_path / "spawned.jsonl"
    watchdog.write_text(
        "import json, subprocess, sys, time\nfrom pathlib import Path\nimport psutil\n"
        "runner, record = map(Path, sys.argv[1:])\n"
        "while True:\n"
        " child=subprocess.Popen([sys.executable,str(runner)],creationflags=subprocess.CREATE_NO_WINDOW)\n"
        " with record.open('a',encoding='utf-8') as stream:\n"
        "  stream.write(json.dumps({'pid':child.pid,'created':psutil.Process(child.pid).create_time()})+'\\n')\n"
        " time.sleep(0.03)\n",
        encoding="utf-8",
    )
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen([sys.executable, str(watchdog), str(runner), str(record)], creationflags=flags)
    unrelated = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"], creationflags=flags)
    pid_file = tmp_path / "pids.json"
    monkeypatch.setattr(stop, "RESOURCE_ROOT", tmp_path)
    children = []
    try:
        deadline = time.monotonic() + 4
        while (not record.exists() or not record.read_text().strip()) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert record.exists() and record.read_text().strip()
        children = [json.loads(line) for line in record.read_text().splitlines()]
        pid_file.write_text(
            json.dumps(
                {
                    "watchdog_pid": process.pid,
                    "watchdog_created_at": psutil.Process(process.pid).create_time(),
                    "runner_pid": children[-1]["pid"],
                    "runner_created_at": children[-1]["created"],
                }
            ),
            encoding="utf-8",
        )
        started = time.monotonic()
        stopped = stop.stop_bot(pid_file)
        process.wait(timeout=2)
        assert time.monotonic() - started < 5
        children = [json.loads(line) for line in record.read_text().splitlines()]
        assert {row["pid"] for row in children}.issubset(set(stopped))
        for row in children:
            assert ownership.verified_process(row["pid"], runner, row["created"]) is None
        assert unrelated.poll() is None
        assert json.loads(pid_file.read_text())["phase"] == "stopped"
    finally:
        for owned in (process, unrelated):
            if owned.poll() is None:
                owned.terminate()
            owned.wait(timeout=2)
        if record.exists():
            for row in (json.loads(line) for line in record.read_text().splitlines()):
                owned = ownership.verified_process(row["pid"], runner, row["created"])
                if owned is not None:
                    owned.terminate()
                    owned.wait(timeout=2)
