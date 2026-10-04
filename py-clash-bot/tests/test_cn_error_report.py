"""Pause diagnostics must be durable, bounded, and incapable of game input."""

# Match the native Chinese diagnostic strings emitted by the real runner.
# ruff: noqa: RUF001

import io
import json
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from pyclashbot.utils import cn_error_report as reports
from scripts import watch_cn_1v1 as watch


@pytest.fixture
def pause(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    state = {
        "watchdog_pid": 2147483000,
        "runner_pid": 2147483001,
        "watchdog_created_at": 100.0,
        "runner_created_at": 101.0,
        "phase": "paused",
        "strategy": "random",
        "exit_reason": "recovery_exhausted",
        "exit_code": 78,
    }
    pid_file = work / "bot-processes.json"
    pid_file.write_text(json.dumps(state), encoding="utf-8")
    live = {"session": "20261004-100000", "state": "paused", "pid": state["runner_pid"], "strategy": "random_mastery"}
    state_path = outputs / "random-mastery-live-status.json"
    state_path.write_text(json.dumps(live), encoding="utf-8")
    trace = outputs / "cn-random-mastery.jsonl"
    trace.write_text(
        json.dumps({"event": "paused", "session": live["session"], "reason": "ADB 连接恢复已耗尽"}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    image = io.BytesIO()
    Image.new("RGB", (8, 12), (20, 40, 60)).save(image, format="PNG")
    png = image.getvalue()
    screenshot = Mock(return_value=SimpleNamespace(returncode=0, stdout=png, stderr=b""))
    monkeypatch.setattr(reports.subprocess, "run", screenshot)
    options = {
        "output_dir": outputs / "error-reports",
        "adb": tmp_path / "adb.exe",
        "serial": "127.0.0.1:21503",
        "pid_file": pid_file,
        "state_path": state_path,
        "log_paths": (trace,),
    }
    return SimpleNamespace(
        options=options,
        state=state,
        live=live,
        trace=trace,
        pid_file=pid_file,
        state_path=state_path,
        screenshot=screenshot,
        png=png,
    )


def test_pause_report_preserves_actual_cause_png_snapshot_and_latest_index(pause):
    reporter = reports.ErrorReporter(**pause.options)
    folder = reporter.capture_pause(background=False).result()
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    index = json.loads(reporter.latest_index.read_text(encoding="utf-8"))
    assert report["reason"] == "ADB 连接恢复已耗尽"
    assert report["runtime"]["session"] == pause.live["session"]
    assert report["runtime"]["phase"] == "paused"
    assert report["snapshots"]["pid_state"] == pause.state
    assert report["screenshot"]["status"] == "captured"
    assert (folder / "game.png").read_bytes() == pause.png
    assert report["game_input_sent"] is False
    assert report["process_identity"]["runner"]["recorded_pid"] == pause.state["runner_pid"]
    assert Path(index["report_md"]).is_file()
    assert Path(index["game_png"]).is_file()
    command = pause.screenshot.call_args.args[0]
    assert command == [str(pause.options["adb"]), "-s", "127.0.0.1:21503", "exec-out", "screencap", "-p"]
    assert pause.screenshot.call_args.kwargs["timeout"] == 8
    assert "+08:00" in report["created_at"]


@pytest.mark.parametrize("reason_source", ["argument", "pid_state", "live_state"])
def test_current_pause_reason_beats_unrelated_session_and_historic_recovery_error(pause, reason_source):
    controlled_reason = "功能验收故障（非实际机器人异常）：报告按钮验证"
    options = dict(pause.options)
    old_log = pause.trace.with_name("cn-battles-live.log")
    old_log.write_text(
        "2026-10-03 18:00:00,123 ERROR 恢复失败，运行器已停止: 过往故障，不属于本次事件\n", encoding="utf-8"
    )
    options["log_paths"] = (pause.trace, old_log)
    # A current session differs from the old paused event in the copied trace.
    live = {**pause.live, "session": "desktop-acceptance", "updated_at": "2026-10-04 10:00:00"}
    state = dict(pause.state)
    arguments = {}
    if reason_source == "argument":
        arguments["reason"] = controlled_reason
        state["reason"] = "lower priority PID cause"
    elif reason_source == "pid_state":
        state["reason"] = controlled_reason
        live["reason"] = "lower priority live cause"
    else:
        live["reason"] = controlled_reason
    pause.pid_file.write_text(json.dumps(state), encoding="utf-8")
    pause.state_path.write_text(json.dumps(live), encoding="utf-8")
    folder = reports.capture_pause_report(**options, **arguments)
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    latest = json.loads((options["output_dir"] / "latest-error-report.json").read_text(encoding="utf-8"))
    assert report["reason"] == controlled_reason
    assert latest["reason"] == controlled_reason
    assert controlled_reason in (folder / "report.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "session,old_failure_time,expected_reason",
    [
        ("new-session", "2026-10-03 18:00:00", "recovery_exhausted"),
        (None, "2026-10-03 18:00:00", "recovery_exhausted"),
        ("new-session", "2026-10-04 10:00:01", "本次终止故障"),
    ],
)
def test_only_matching_session_or_current_pause_timestamp_can_supply_log_reason(
    pause, session, old_failure_time, expected_reason
):
    live = {**pause.live, "session": session, "updated_at": "2026-10-04 10:00:00"}
    pause.state_path.write_text(json.dumps(live), encoding="utf-8")
    pause.pid_file.write_text(json.dumps({**pause.state, "ended_at": "2026-10-04 10:00:02"}), encoding="utf-8")
    log = pause.trace.with_name("cn-battles-live.log")
    log.write_text(f"{old_failure_time},123 ERROR 恢复失败，运行器已停止: 本次终止故障\n", encoding="utf-8")
    folder = reports.capture_pause_report(**{**pause.options, "log_paths": (pause.trace, log)})
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    assert report["reason"] == expected_reason


@pytest.mark.parametrize("failure", ["timeout", "nonzero", "invalid", "truncated"])
def test_failed_screenshot_still_commits_complete_reason_report_without_fake_image(pause, failure):
    if failure == "timeout":
        pause.screenshot.side_effect = subprocess.TimeoutExpired("screencap", 8)
    elif failure == "nonzero":
        pause.screenshot.return_value = SimpleNamespace(returncode=1, stdout=b"", stderr=b"device offline")
    else:
        pause.screenshot.return_value = SimpleNamespace(
            returncode=0, stdout=b"not a screenshot" if failure == "invalid" else b"\x89PNG\r\n\x1a\n", stderr=b""
        )
    folder = reports.capture_pause_report(**pause.options)
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    index = json.loads((pause.options["output_dir"] / "latest-error-report.json").read_text(encoding="utf-8"))
    assert report["screenshot"]["status"] == "failed"
    assert report["screenshot"]["error"]
    assert report["reason"] == "ADB 连接恢复已耗尽"
    assert (folder / "report.md").is_file()
    assert not (folder / "game.png").exists()
    assert index["game_png"] is None


def test_ui_pause_and_watchdog_exit_replay_share_one_immutable_report(pause):
    early = {**pause.state, "phase": "running"}
    for key in ("exit_reason", "exit_code"):
        early.pop(key)
    pause.pid_file.write_text(json.dumps(early), encoding="utf-8")
    first = reports.capture_pause_report(**pause.options)
    before = (first / "report.json").read_bytes()
    pause.pid_file.write_text(json.dumps({**pause.state, "ended_at": "2026-10-04 10:05:00"}), encoding="utf-8")
    replay = reports.capture_pause_report(**pause.options)
    assert replay == first
    assert (first / "report.json").read_bytes() == before
    pause.screenshot.assert_called_once()


def test_next_runner_pause_preserves_prior_report_and_updates_latest(pause):
    first = reports.capture_pause_report(**pause.options)
    before = (first / "report.json").read_bytes()
    pause.pid_file.write_text(json.dumps({**pause.state, "runner_created_at": 102.0}), encoding="utf-8")
    second = reports.capture_pause_report(**pause.options, reason="另一次暂停")
    assert first != second
    assert (first / "report.json").read_bytes() == before
    index = json.loads((pause.options["output_dir"] / "latest-error-report.json").read_text(encoding="utf-8"))
    assert Path(index["report_dir"]) == second
    assert pause.screenshot.call_count == 2


def test_background_capture_returns_without_waiting_and_same_event_shares_future(pause):
    entered, release = threading.Event(), threading.Event()

    def screenshot(*_args, **_kwargs):
        entered.set()
        assert release.wait(3)
        return SimpleNamespace(returncode=0, stdout=pause.png, stderr=b"")

    pause.screenshot.side_effect = screenshot
    reporter = reports.ErrorReporter(**pause.options)
    future = reporter.capture_pause()
    try:
        assert entered.wait(3)
        assert not future.done()
        assert reporter.capture_pause() is future
    finally:
        release.set()
    folder = future.result(timeout=5)
    assert (folder / "report.md").is_file()


def test_independent_ui_and_watchdog_capture_same_inflight_pause_only_once(pause):
    entered, release = threading.Event(), threading.Event()

    def screenshot(*_args, **_kwargs):
        entered.set()
        assert release.wait(3)
        return SimpleNamespace(returncode=0, stdout=pause.png, stderr=b"")

    pause.screenshot.side_effect = screenshot
    first_reporter = reports.ErrorReporter(**pause.options)
    second_reporter = reports.ErrorReporter(**pause.options)
    first = first_reporter.capture_pause()
    try:
        assert entered.wait(3)
        replay = second_reporter.capture_pause(background=False).result()
        assert not first.done()
        assert (replay / "report.json").is_file()
        assert json.loads((replay / "report.json").read_text(encoding="utf-8"))["screenshot"]["status"] == "pending"
    finally:
        release.set()
    assert first.result(timeout=5) == replay
    pause.screenshot.assert_called_once()


def test_failed_report_publication_can_retry_without_changing_pause_identity(pause, monkeypatch):
    write = reports.atomic_write_json
    failures = []

    def transient_failure(path, value):
        if not failures:
            failures.append(str(path))
            raise PermissionError("temporarily blocked diagnostic path")
        return write(path, value)

    monkeypatch.setattr(reports, "atomic_write_json", transient_failure)
    reporter = reports.ErrorReporter(**pause.options)
    with pytest.raises(PermissionError):
        reporter.capture_pause(background=False).result()
    pause.screenshot.assert_not_called()
    folder = reporter.capture_pause(background=False).result()
    assert (folder / "report.md").is_file()
    pause.screenshot.assert_called_once()


def test_reports_redact_state_and_json_log_credentials(pause):
    private_live = {**pause.live, "api_key": "DO_NOT_RETAIN_1", "nested": {"cookie": "DO_NOT_RETAIN_2"}}
    pause.state_path.write_text(json.dumps(private_live), encoding="utf-8")
    with pause.trace.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "event": "paused",
                    "session": pause.live["session"],
                    "reason": "request failed token=DO_NOT_RETAIN_3",
                    "password": "DO_NOT_RETAIN_4",
                }
            )
            + "\n"
        )
    folder = reports.capture_pause_report(**pause.options)
    report_text = (folder / "report.json").read_text(encoding="utf-8")
    markdown = (folder / "report.md").read_text(encoding="utf-8")
    assert "DO_NOT_RETAIN" not in report_text + markdown
    assert "已脱敏" in report_text


def test_unrelated_log_and_state_paths_are_rejected_before_read_or_adb(pause):
    with pytest.raises(ValueError, match="专属日志"):
        reports.ErrorReporter(**{**pause.options, "log_paths": (pause.trace.with_name("credentials.json"),)})
    with pytest.raises(ValueError, match="机器人状态"):
        reports.ErrorReporter(**{**pause.options, "state_path": pause.trace.with_name("secrets.json")})
    with pytest.raises(ValueError, match="PID 状态"):
        reports.ErrorReporter(**{**pause.options, "pid_file": pause.pid_file.with_name("runtime-config.json")})
    pause.screenshot.assert_not_called()


def test_running_robot_cannot_be_reported_as_a_pause(pause):
    pause.pid_file.write_text(json.dumps({**pause.state, "phase": "running"}), encoding="utf-8")
    pause.state_path.write_text(json.dumps({**pause.live, "state": "battle"}), encoding="utf-8")
    with pytest.raises(ValueError, match="已暂停"):
        reports.capture_pause_report(**pause.options)
    pause.screenshot.assert_not_called()


def test_corrupt_live_state_is_reported_without_losing_watchdog_pause_reason(pause):
    pause.state_path.write_text("{unfinished", encoding="utf-8")
    folder = reports.capture_pause_report(**pause.options, reason="恢复失败")
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    assert report["reason"] == "恢复失败"
    assert report["snapshot_errors"]["live_state"]
    assert report["snapshots"]["live_state"] == {}


@pytest.mark.parametrize(
    "exit_code,limit,expected_spawns,exit_reason",
    [
        (78, 0, 1, "recovery_exhausted"),
        (1, 5, 1, "finite_run_interrupted"),
        (1, 0, 4, "recovery_exhausted"),
        (0, 0, 1, None),
    ],
)
def test_watchdog_reports_terminal_pause_once_without_changing_recovery_budget(
    tmp_path, monkeypatch, exit_code, limit, expected_spawns, exit_reason
):
    outputs = tmp_path / "outputs"
    state_file = tmp_path / "work" / "bot-processes.json"
    argv = [
        "watch_cn_1v1.py",
        "--adb",
        "adb.exe",
        "--serial",
        "offline-test",
        "--memuc",
        "memuc.exe",
        "--log",
        str(outputs / "cn-battles-live.log"),
        "--watchdog-log",
        str(outputs / "cn-watchdog.log"),
        "--pid-file",
        str(state_file),
        "--strategy",
        "random",
        "--max-battles",
        str(limit),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(watch, "load_runtime_config", lambda: SimpleNamespace(data_root=tmp_path))
    monkeypatch.setattr(watch.logging, "basicConfig", lambda **_: None)
    monkeypatch.setattr(
        watch,
        "ctypes",
        SimpleNamespace(windll=SimpleNamespace(kernel32=SimpleNamespace(SetThreadExecutionState=lambda _: 1))),
    )
    child = SimpleNamespace(pid=2147483000, wait=Mock(return_value=exit_code))
    launch = Mock(return_value=child)
    monkeypatch.setattr(watch.subprocess, "Popen", launch)
    monkeypatch.setattr(watch, "process_record", lambda *_: {"created_at": 100.0})
    monkeypatch.setattr(watch.time, "sleep", lambda _: None)
    capture = Mock()
    monkeypatch.setattr(watch, "_report_pause", capture)
    watch.main()
    assert launch.call_count == expected_spawns
    if exit_reason:
        capture.assert_called_once()
        reported = capture.call_args.args[1]
        assert reported["phase"] == "paused"
        assert reported["exit_reason"] == exit_reason
        assert json.loads(state_file.read_text(encoding="utf-8")) == reported
    else:
        capture.assert_not_called()
