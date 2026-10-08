"""The WPF API must preserve bot ownership and keep stdout strictly JSONL."""

# Exact native Chinese punctuation is part of the log-encoding fixtures.
# ruff: noqa: RUF001

import io
import json
import sqlite3
import subprocess
import sys
import threading
import tkinter
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pyclashbot.utils import process_ownership
from pyclashbot.utils.battle_history import BattleHistory
from scripts import cn_bot_control, cn_desktop_entry, cn_windows_entry, stop_cn_1v1
from scripts import cn_wpf_backend as backend


@pytest.fixture
def fake_control(tmp_path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    state = {"value": "stopped"}
    window = SimpleNamespace(_start_worker=Mock(return_value="started"), _stop_worker=Mock(return_value="stopped"))
    return SimpleNamespace(
        OUTPUTS=outputs,
        TASK_ROOT=tmp_path,
        HISTORY_DB=outputs / "cn-battle-history.sqlite3",
        BATTLE_LOG=outputs / "cn-battles-live.log",
        WATCHDOG_LOG=outputs / "cn-watchdog.log",
        RANDOM_TRACE=outputs / "cn-random-mastery.jsonl",
        REWARDS_TRACE=outputs / "cn-mastery-rewards.jsonl",
        RANDOM_STATUS=outputs / "random-mastery-live-status.json",
        PID_FILE=work / "bot-processes.json",
        ADB=tmp_path / "adb.exe",
        MEMUC=tmp_path / "memuc.exe",
        SERIAL="offline-device",
        PYTHON=tmp_path / "python.exe",
        RUNTIME=SimpleNamespace(vm_index=0),
        ControlWindow=window,
        bot_state=lambda: state["value"],
        read_random_status=lambda: {"session": "offline-session", "state": "stopped"},
        selected_strategy=lambda: "random",
        mutable_state=state,
    )


def metadata_process(fake_control):
    return SimpleNamespace(
        create_time=lambda: 100.0,
        exe=lambda: str(fake_control.PYTHON),
        cmdline=lambda: [str(fake_control.PYTHON), "unrelated.py"],
        cwd=lambda: str(fake_control.TASK_ROOT),
        is_running=lambda: False,
    )


def test_snapshot_and_shutdown_never_start_stop_or_construct_a_window(fake_control):
    bridge = backend.BackendBridge(control=fake_control, read_only=True)
    bridge.initialize()
    snapshot = bridge.command("snapshot")
    response = bridge.command("shutdown")
    bridge.close()
    assert snapshot["state"] == "stopped"
    assert snapshot["selected_strategy"] == "random"
    assert set(snapshot["scopes"]) == {"random", "567", "hog", "all"}
    assert snapshot["runtime"]["serial"] == "offline-device"
    assert snapshot["reward_totals"] == {"rewards": 0, "coins": 0, "unknown_coin_items": 0}
    assert snapshot["error_report_pending"] is False
    assert response["shutdown"] is True
    fake_control.ControlWindow._start_worker.assert_not_called()
    fake_control.ControlWindow._stop_worker.assert_not_called()
    assert not fake_control.HISTORY_DB.exists()


def test_readonly_snapshot_reuses_battle_history_queries_without_modifying_database(fake_control):
    row = {
        "event": "battle_finished",
        "session": "sample",
        "battle": 1,
        "time": "2026-10-04 12:00:00",
        "policy": "random-policy",
        "outcome": "胜利",
        "cards_confirmed": 3,
        "card_attempts": 4,
        "evidence": {},
    }
    fake_control.RANDOM_TRACE.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    history = BattleHistory(fake_control.HISTORY_DB)
    history.ingest(fake_control.RANDOM_TRACE, "random")
    history.close()
    before = fake_control.HISTORY_DB.read_bytes()
    bridge = backend.BackendBridge(control=fake_control, read_only=True)
    bridge.initialize()
    snapshot = bridge.command("snapshot")
    assert snapshot["scopes"]["random"]["total"]["total"] == 1
    assert snapshot["scopes"]["random"]["total"]["wins"] == 1
    assert snapshot["scopes"]["all"]["records"][0]["confirmed"] == 3
    assert fake_control.HISTORY_DB.read_bytes() == before
    assert snapshot["history_error"] is None


@pytest.mark.parametrize("command", ["start", "stop", "shop_daily"])
def test_readonly_backend_refuses_control_commands(fake_control, command):
    bridge = backend.BackendBridge(control=fake_control, read_only=True)
    with pytest.raises(RuntimeError, match="不能"):
        bridge.command(command)
    fake_control.ControlWindow._start_worker.assert_not_called()
    fake_control.ControlWindow._stop_worker.assert_not_called()


@pytest.mark.parametrize("command", ["start", "stop"])
def test_control_commands_use_existing_worker_exactly_once_and_clear_busy(fake_control, command):
    bridge = backend.BackendBridge(control=fake_control)
    response = bridge.command(command)
    worker = fake_control.ControlWindow._start_worker if command == "start" else fake_control.ControlWindow._stop_worker
    worker.assert_called_once()
    if command == "start":
        assert worker.call_args.kwargs["cancel_event"].is_set() is False
        assert worker.call_args.kwargs["launch_lock"] is bridge._launch_lock
        assert callable(worker.call_args.kwargs["on_watchdog_started"])
    else:
        worker.assert_called_once_with()
    assert response["message"] == ("started" if command == "start" else "stopped")
    assert bridge.busy is None


def test_failed_start_has_error_and_can_be_observed_again(fake_control):
    fake_control.ControlWindow._start_worker.side_effect = RuntimeError("Android not ready")
    bridge = backend.BackendBridge(control=fake_control)
    with pytest.raises(RuntimeError, match="Android not ready"):
        bridge.command("start")
    assert bridge.busy is None
    assert bridge.snapshot()["state"] == "stopped"


def mock_installed_owner(
    fake_control, monkeypatch, *, executable=None, component="run_cn_1v1.py", created=100.0, alive=True
):
    path = executable or (fake_control.OUTPUTS / "desktop-app-20261004" / "ClashAssistant.exe")
    fake_control.PID_FILE.write_text(json.dumps({"runner_pid": 22, "runner_created_at": 100.0}), encoding="utf-8")
    process = SimpleNamespace(
        exe=lambda: str(path),
        create_time=lambda: created,
        is_running=Mock(return_value=alive),
        cmdline=lambda: [str(path), "--component", component],
    )
    monkeypatch.setattr(backend.psutil, "Process", lambda _pid: process)
    return path, process


def test_existing_installed_desktop_owner_is_visible_and_start_cannot_duplicate_it(fake_control, monkeypatch):
    path, _process = mock_installed_owner(fake_control, monkeypatch)
    bridge = backend.BackendBridge(control=fake_control)
    assert bridge.snapshot()["state"] == "running"
    assert bridge.snapshot()["runtime"]["active_owner_executable"] == str(path)
    assert bridge.command("start")["state"] == "running"
    fake_control.ControlWindow._start_worker.assert_not_called()


@pytest.mark.parametrize("bad_identity", ["executable", "component", "created", "nonfinite", "dead"])
def test_installed_owner_detection_rejects_untrusted_or_reused_identity(fake_control, monkeypatch, bad_identity):
    kwargs = {}
    if bad_identity == "executable":
        kwargs["executable"] = fake_control.TASK_ROOT / "unrelated.exe"
    elif bad_identity == "component":
        kwargs["component"] = "unrelated.py"
    elif bad_identity == "created":
        kwargs["created"] = 101.0
    elif bad_identity == "nonfinite":
        kwargs["created"] = float("nan")
    else:
        kwargs["alive"] = False
    mock_installed_owner(fake_control, monkeypatch, **kwargs)
    bridge = backend.BackendBridge(control=fake_control, read_only=True)
    assert bridge.snapshot()["state"] == "stopped"
    assert bridge.snapshot()["runtime"]["active_owner_executable"] is None


def test_stop_existing_installed_owner_uses_in_process_identity_checked_stopper(fake_control, monkeypatch):
    path, process = mock_installed_owner(fake_control, monkeypatch)

    def stopped(*_args, **_kwargs):
        process.is_running.return_value = False
        return SimpleNamespace(returncode=0, stdout=b"stopped", stderr=b"")

    stop = Mock(side_effect=stopped)
    monkeypatch.setattr(backend, "stop_bot", stop)
    bridge = backend.BackendBridge(control=fake_control)
    assert bridge.command("stop")["state"] == "stopped"
    stop.assert_called_once_with(fake_control.PID_FILE, trusted_executables=(path,))
    fake_control.ControlWindow._stop_worker.assert_not_called()


def test_protocol_whitelist_recovers_after_bad_json_and_exposes_only_jsonl(fake_control):
    bridge = backend.BackendBridge(control=fake_control, read_only=True)
    requests = [
        "{broken",
        json.dumps({"id": "unsafe", "command": "shell", "payload": "arbitrary"}),
        json.dumps({"id": "snapshot", "command": "snapshot"}),
        json.dumps({"id": "reports", "command": "reports"}),
        json.dumps({"id": "end", "command": "shutdown"}),
        json.dumps({"id": "too-late", "command": "start"}),
    ]
    output = io.StringIO()
    backend.serve(bridge, io.StringIO("\n".join(requests) + "\n"), output)
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert len(responses) == 5
    assert all(set(row) == {"id", "ok", "data", "error"} for row in responses)
    assert [row["ok"] for row in responses] == [False, False, True, True, True]
    assert responses[2]["data"]["state"] == "stopped"
    assert responses[3]["data"]["reports"] == []
    assert responses[4]["data"]["shutdown"] is True
    fake_control.ControlWindow._start_worker.assert_not_called()


def test_oversized_request_is_drained_without_losing_next_valid_request(fake_control):
    bridge = backend.BackendBridge(control=fake_control, read_only=True)
    huge = json.dumps({"id": "oversized", "command": "x" * (backend.MAX_REQUEST_BYTES * 3)})
    good = json.dumps({"id": "after", "command": "snapshot"})
    output = io.StringIO()
    backend.serve(bridge, io.StringIO(huge + "\n" + good + "\n"), output)
    rows = [json.loads(line) for line in output.getvalue().splitlines()]
    assert len(rows) == 2 and rows[0]["ok"] is False and rows[1]["id"] == "after" and rows[1]["ok"] is True


def test_snapshot_remains_available_and_stop_interrupts_pending_start(fake_control, monkeypatch):
    entered = threading.Event()
    order = []

    def start(*, cancel_event, **_kwargs):
        order.append("start-entered")
        entered.set()
        assert cancel_event.wait(3)
        order.append("start-cancelled")
        raise RuntimeError("启动已取消")

    def stop():
        order.append("stop-entered")
        fake_control.mutable_state["value"] = "stopped"
        return "stopped"

    fake_control.ControlWindow._start_worker.side_effect = start
    fake_control.ControlWindow._stop_worker.side_effect = stop
    bridge = backend.BackendBridge(control=fake_control)
    original_snapshot = bridge.snapshot

    def snapshot():
        assert entered.wait(3)
        result = original_snapshot()
        assert result["state"] == "starting" and result["busy"] == "start"
        return result

    monkeypatch.setattr(bridge, "snapshot", snapshot)
    requests = [{"id": name, "command": name} for name in ("start", "snapshot", "stop", "shutdown")]
    output = io.StringIO()
    backend.serve(bridge, io.StringIO("\n".join(json.dumps(row) for row in requests) + "\n"), output)
    rows = [json.loads(line) for line in output.getvalue().splitlines()]
    assert {row["id"] for row in rows} == {"start", "snapshot", "stop", "shutdown"}
    by_id = {row["id"]: row for row in rows}
    assert by_id["start"]["ok"] is False and "取消" in by_id["start"]["error"]
    assert all(by_id[name]["ok"] for name in ("snapshot", "stop", "shutdown"))
    assert order[0] == "start-entered"
    assert set(order[1:]) == {"start-cancelled", "stop-entered"}
    assert fake_control.mutable_state["value"] == "stopped"


def test_start_is_rejected_during_stop_and_does_not_run_later(fake_control):
    entered, release = threading.Event(), threading.Event()
    fake_control.ControlWindow._stop_worker.side_effect = lambda: (entered.set(), release.wait(3), "stopped")[-1]
    bridge = backend.BackendBridge(control=fake_control)
    stopped = threading.Thread(target=lambda: bridge.command("stop"))
    stopped.start()
    try:
        assert entered.wait(3)
        assert bridge.snapshot()["state"] == "stopping"
        with pytest.raises(RuntimeError, match="正在停止"):
            bridge.command("start")
        fake_control.ControlWindow._start_worker.assert_not_called()
    finally:
        release.set()
        stopped.join(3)
    assert not stopped.is_alive()
    bridge.command("start")
    fake_control.ControlWindow._start_worker.assert_called_once()


def test_unconfirmed_stop_requires_a_successful_retry_before_start(fake_control):
    bridge = backend.BackendBridge(control=fake_control)
    fake_control.ControlWindow._stop_worker.side_effect = RuntimeError("permission denied")
    with pytest.raises(RuntimeError, match="permission denied"):
        bridge.command("stop")
    assert bridge.snapshot()["state"] == "stopping"
    with pytest.raises(RuntimeError, match="尚未确认"):
        bridge.command("start")
    fake_control.ControlWindow._start_worker.assert_not_called()
    reconnected = backend.BackendBridge(control=fake_control)
    assert reconnected.snapshot()["state"] == "stopping"
    with pytest.raises(RuntimeError, match="尚未确认"):
        reconnected.command("start")
    fake_control.ControlWindow._stop_worker.side_effect = None
    bridge.command("stop")
    assert bridge.snapshot()["state"] == "stopped"
    bridge.command("start")
    fake_control.ControlWindow._start_worker.assert_called_once()


def test_stop_waits_for_cancellation_and_stops_unpublished_watchdog(fake_control, monkeypatch):
    entered, finish = threading.Event(), threading.Event()
    fake_watchdog = SimpleNamespace(pid=22)
    monkeypatch.setattr(backend.psutil, "Process", lambda _pid: metadata_process(fake_control))

    def start(*, cancel_event, launch_lock, on_watchdog_started):
        with launch_lock:
            on_watchdog_started(fake_watchdog)
        entered.set()
        assert cancel_event.wait(3)
        finish.set()
        raise RuntimeError("启动已取消")

    def stopped(*_args, **_kwargs):
        assert entered.is_set()

    fake_control.ControlWindow._start_worker.side_effect = start
    stop = Mock(side_effect=stopped)
    monkeypatch.setattr(backend, "stop_bot", stop)
    bridge = backend.BackendBridge(control=fake_control)
    errors = []

    def launching():
        try:
            bridge.command("start")
        except RuntimeError as error:
            errors.append(str(error))

    worker = threading.Thread(target=launching)
    worker.start()
    assert entered.wait(3)
    assert not fake_control.PID_FILE.exists()
    response = bridge.command("stop")
    worker.join(3)
    assert response["state"] == "stopped" and finish.is_set() and not worker.is_alive()
    stop.assert_called_once_with(fake_control.PID_FILE, pending_watchdog=(22, 100.0), trusted_executables=())
    assert len(errors) == 1 and "取消" in errors[0]


@pytest.mark.parametrize("cleanup_denied", [False, True])
def test_start_error_after_spawn_cleans_registered_watchdog_or_preserves_unknown(
    fake_control, monkeypatch, cleanup_denied
):
    monkeypatch.setattr(backend.psutil, "Process", lambda _pid: metadata_process(fake_control))

    def start(*, launch_lock, on_watchdog_started, **_kwargs):
        with launch_lock:
            on_watchdog_started(SimpleNamespace(pid=22))
        raise RuntimeError("watchdog readiness timed out")

    fake_control.ControlWindow._start_worker.side_effect = start
    cleanup = Mock(side_effect=RuntimeError("permission denied") if cleanup_denied else None)
    monkeypatch.setattr(backend, "stop_bot", cleanup)
    bridge = backend.BackendBridge(control=fake_control)
    with pytest.raises(RuntimeError, match="readiness timed out"):
        bridge.command("start")
    cleanup.assert_called_once_with(fake_control.PID_FILE, pending_watchdog=(22, 100.0))
    assert bridge._start_operation is None
    if cleanup_denied:
        assert bridge.snapshot()["state"] == "stopping"
        reconnected = backend.BackendBridge(control=fake_control)
        with pytest.raises(RuntimeError, match="尚未确认"):
            reconnected.command("start")
    else:
        assert bridge.snapshot()["state"] == "stopped"


def test_failed_start_cleanup_keeps_unpublished_identity_for_retry_after_reconnect(fake_control, monkeypatch):
    scripts = fake_control.TASK_ROOT / "scripts"
    scripts.mkdir()
    watchdog = scripts / "watch_cn_1v1.py"
    watchdog.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, str(watchdog)],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    monkeypatch.setattr(stop_cn_1v1, "RESOURCE_ROOT", fake_control.TASK_ROOT)
    identity = process_ownership.process_record(process.pid, watchdog)

    def start(*, on_watchdog_started, **_kwargs):
        on_watchdog_started(process)
        raise RuntimeError("readiness timed out")

    fake_control.ControlWindow._start_worker.side_effect = start
    monkeypatch.setattr(backend, "stop_bot", Mock(side_effect=RuntimeError("permission denied")))
    try:
        bridge = backend.BackendBridge(control=fake_control)
        with pytest.raises(RuntimeError, match="readiness timed out"):
            bridge.command("start")
        assert process.poll() is None and not fake_control.PID_FILE.exists()
        pending = json.loads(fake_control.PID_FILE.with_suffix(".pending.json").read_text())
        assert pending["watchdog_pid"] == identity["pid"]
        monkeypatch.setattr(backend, "stop_bot", stop_cn_1v1.stop_bot)

        def stop_retry():
            stop_cn_1v1.stop_bot(fake_control.PID_FILE)
            return "stopped"

        fake_control.ControlWindow._stop_worker.side_effect = stop_retry
        reconnected = backend.BackendBridge(control=fake_control)
        assert reconnected.snapshot()["state"] == "stopping"
        assert reconnected.command("stop")["state"] == "stopped"
        process.wait(timeout=2)
        assert json.loads(fake_control.PID_FILE.with_suffix(".pending.json").read_text())["phase"] == "stopped"
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=2)


def test_history_loop_recovers_after_one_ingest_failure_and_rebuilds_connection(fake_control, monkeypatch):
    recovered = threading.Event()
    bridge = backend.BackendBridge(control=fake_control)
    attempts = []
    first = Mock()
    first.ingest.side_effect = sqlite3.OperationalError("temporarily locked")
    second = Mock()
    second.ingest.return_value = False

    def snapshot(scope):
        assert bridge.history_error == "temporarily locked"
        return {**backend._empty_scope(scope), "recovered": True}

    second.snapshot.side_effect = snapshot
    second.reward_snapshot.return_value = {"rewards": 7, "coins": 80, "unknown_coin_items": 0}

    def factory(_path):
        value = first if not attempts else second
        attempts.append(value)
        return value

    monkeypatch.setattr(backend, "BattleHistory", factory)
    original_wait = bridge.stop_event.wait

    def wait(seconds):
        if len(attempts) >= 2:
            recovered.set()
            bridge.stop_event.set()
        return original_wait(min(seconds, 0.01))

    monkeypatch.setattr(bridge.stop_event, "wait", wait)
    bridge._history_loop()
    assert recovered.is_set() and attempts == [first, second]
    first.close.assert_called_once()
    second.close.assert_called_once()
    assert bridge.history_error is None and bridge.scopes["random"]["recovered"] is True
    assert bridge.reward_totals["rewards"] == 7


def test_pause_monitor_captures_evidence_without_game_controls(fake_control, monkeypatch):
    seen = threading.Event()
    future = Future()
    future.set_result(fake_control.OUTPUTS / "error-reports")

    def capture():
        seen.set()
        return future

    reporter = SimpleNamespace(capture_pause=Mock(side_effect=capture))
    monkeypatch.setattr(backend, "ErrorReporter", lambda *_, **__: reporter)
    fake_control.mutable_state["value"] = "paused"
    bridge = backend.BackendBridge(control=fake_control)
    monkeypatch.setattr(bridge, "_history_loop", lambda: bridge.stop_event.wait(3))
    bridge.initialize()
    try:
        assert seen.wait(3)
        reporter.capture_pause.assert_called()
    finally:
        bridge.close()
    fake_control.ControlWindow._start_worker.assert_not_called()
    fake_control.ControlWindow._stop_worker.assert_not_called()


def test_recent_events_redact_bot_log_credentials(fake_control):
    fake_control.BATTLE_LOG.write_text("bot request token=DO_NOT_RETAIN\n", encoding="utf-8")
    bridge = backend.BackendBridge(control=fake_control, read_only=True)
    events = bridge.snapshot()["recent_events"]
    assert events and "DO_NOT_RETAIN" not in "\n".join(events)


def test_utf8_watchdog_rows_are_preserved_without_legacy_reinterpretation(fake_control):
    text = "2026-10-04 16:00:00,001 INFO 对战完成，奖励已保存 ⚑"
    original = (text + "\n").encode("utf-8")
    fake_control.WATCHDOG_LOG.write_bytes(original)
    assert backend._safe_bot_tail(fake_control.WATCHDOG_LOG) == [text]
    assert fake_control.WATCHDOG_LOG.read_bytes() == original


def test_confirmed_legacy_watchdog_gb18030_rows_are_recovered_readonly(fake_control):
    text = "2026-10-03 23:16:59,743 INFO 卡牌大师：没有领取全部按钮，无可领奖励，关闭页面继续下一局"
    original = (text + "\n").encode("gb18030")
    fake_control.WATCHDOG_LOG.write_bytes(original)
    assert backend._safe_bot_tail(fake_control.WATCHDOG_LOG) == [text]
    assert fake_control.WATCHDOG_LOG.read_bytes() == original


def test_mixed_watchdog_encodings_are_decoded_line_by_line(fake_control):
    utf8 = "2026-10-04 16:00:00,001 INFO 当前守护消息 中文 ⚑"
    legacy = "2026-10-03 23:17:04,635 INFO 随机卡组已生成 第1004套，变化卡位=8"
    ascii_text = "2026-10-04 16:00:01,000 INFO ASCII metadata"
    fake_control.WATCHDOG_LOG.write_bytes(
        utf8.encode("utf-8") + b"\n" + legacy.encode("gb18030") + b"\r\n" + ascii_text.encode() + b"\n"
    )
    assert backend._safe_bot_tail(fake_control.WATCHDOG_LOG) == [utf8, legacy, ascii_text]


def test_failed_decoding_preserves_replacement_text_and_marks_uncertain_encoding(fake_control):
    fake_control.WATCHDOG_LOG.write_bytes(b"2026-10-04 16:00:00,001 ERROR invalid \xff\xfe\n")
    lines = backend._safe_bot_tail(fake_control.WATCHDOG_LOG)
    assert len(lines) == 1 and "\ufffd" in lines[0]
    assert "编码待确认" in lines[0] and "原始日志字节仍保留" in lines[0]


def test_unconfirmed_legacy_source_is_not_guessed_as_chinese(fake_control):
    text = "对战旧记录"
    fake_control.BATTLE_LOG.write_bytes(text.encode("gb18030") + b"\n")
    lines = backend._safe_bot_tail(fake_control.BATTLE_LOG)
    assert text not in lines[0] and "编码待确认" in lines[0]


def test_clipped_tail_drops_partial_line_and_keeps_complete_mixed_rows(fake_control):
    utf8, legacy = "2026-10-04 INFO UTF8 中文 ⚑", "2026-10-03 INFO 旧消息"
    fake_control.WATCHDOG_LOG.write_bytes(
        b"x" * (64 * 1024 + 128) + b"\n" + utf8.encode("utf-8") + b"\n" + legacy.encode("gb18030") + b"\n"
    )
    assert backend._safe_bot_tail(fake_control.WATCHDOG_LOG, maximum_lines=2) == [utf8, legacy]


def test_component_stdio_is_configured_as_utf8_before_dispatch(monkeypatch):
    calls = []

    class ConsoleStream(io.StringIO):
        def __init__(self, name):
            super().__init__()
            self.name = name

        def reconfigure(self, **kwargs):
            calls.append((self.name, kwargs))

    monkeypatch.setattr(backend.sys, "argv", ["ClashBackend.exe", "--component", "watch_cn_1v1.py"])
    for name in ("stdin", "stdout", "stderr"):
        monkeypatch.setattr(backend.sys, name, ConsoleStream(name))
    monkeypatch.setattr(cn_desktop_entry, "configure_desktop_runtime", lambda: None)
    dispatch = Mock(side_effect=lambda: calls.append(("dispatch", {})))
    monkeypatch.setattr(cn_windows_entry, "main", dispatch)
    backend.main()
    assert [name for name, _kwargs in calls] == ["stdin", "stdout", "stderr", "dispatch"]
    assert all(kwargs == {"encoding": "utf-8", "errors": "replace"} for _name, kwargs in calls[:3])
    dispatch.assert_called_once_with()


def test_source_control_module_import_does_not_create_tk_window():
    assert cn_bot_control.ControlWindow is not None
    assert getattr(tkinter, "_default_root") is None


def test_source_cli_from_other_working_directory_emits_jsonl_without_gui_or_bot(fake_control):
    requests = [{"id": "probe", "command": "snapshot"}, {"id": "end", "command": "shutdown"}]
    result = subprocess.run(
        [sys.executable, backend.__file__, "--data-root", str(fake_control.TASK_ROOT), "--read-only"],
        cwd=fake_control.TASK_ROOT,
        input="\n".join(json.dumps(row) for row in requests) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stderr
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(responses) == 2 and all(row["ok"] for row in responses)
    assert responses[0]["data"]["state"] == "stopped"
    assert not fake_control.PID_FILE.exists()
    assert not fake_control.HISTORY_DB.exists()
