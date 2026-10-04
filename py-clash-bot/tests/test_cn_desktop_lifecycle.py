"""Desktop lifecycle preserves the emulator and never starts work on opening."""

from unittest.mock import Mock

import pytest

from scripts import cn_bot_control as console


def window_with_shell():
    window = console.ControlWindow.__new__(console.ControlWindow)
    window.root = Mock()
    window.notice = Mock()
    window.shell = Mock()
    window.shell.diagnostics.return_value = {"tray_icon_added": True}
    window.live_view = Mock()
    window.live_view.host.embedded = True
    window._hidden = False
    window._restore_embedding = False
    window._attach_after_id = None
    window._exit_requested = False
    window.history_stop = Mock()
    window.busy = None
    return window


def test_closing_hides_only_after_restoring_the_native_window():
    window = window_with_shell()
    sequence = []
    window.live_view.host.detach.side_effect = lambda: sequence.append("detach")
    window.root.withdraw.side_effect = lambda: sequence.append("hide")
    window._on_close()
    assert sequence == ["detach", "hide"]
    assert window._hidden and window._restore_embedding
    window.root.destroy.assert_not_called()
    window.history_stop.set.assert_not_called()


def test_failed_native_restore_keeps_the_host_visible():
    window = window_with_shell()
    window.live_view.host.detach.side_effect = RuntimeError("restore failed")
    window._on_close()
    window.root.withdraw.assert_not_called()
    window.root.destroy.assert_not_called()
    assert not window._hidden


def test_no_tray_never_hides_the_only_control_window():
    window = window_with_shell()
    window.shell.diagnostics.return_value = {"tray_icon_added": False}
    window._on_close()
    window.root.withdraw.assert_not_called()
    window.live_view.host.detach.assert_not_called()


def test_restoring_hidden_window_reembeds_after_showing():
    window = window_with_shell()
    window._hidden = True
    window._restore_embedding = True
    window._show_window()
    assert not window._hidden and window._restore_embedding
    window.root.deiconify.assert_called_once()
    window.root.after.assert_called_once_with(150, window._restore_live_view)


def test_rapid_show_hide_cancels_pending_embed_and_preserves_restore():
    window = window_with_shell()
    window._restore_embedding = True
    window.live_view.host.embedded = False
    window.root.after.return_value = "attach-id"
    window._show_window()
    window._on_close()
    window.root.after_cancel.assert_called_once_with("attach-id")
    assert window._hidden and window._restore_embedding
    window._restore_live_view()
    window.live_view.attach.assert_not_called()


@pytest.mark.parametrize("state", ["running", "starting"])
def test_exit_stops_live_work_before_destroying_the_host(monkeypatch, state):
    window = window_with_shell()
    monkeypatch.setattr(console, "bot_state", lambda: state)
    window._action = Mock()
    window._request_exit()
    assert window._exit_requested
    window._action.assert_called_once_with("stop", window._stop_worker)
    window.root.destroy.assert_not_called()


@pytest.mark.parametrize("state", ["stopped", "paused"])
def test_exit_with_no_live_worker_can_close_normally(monkeypatch, state):
    window = window_with_shell()
    monkeypatch.setattr(console, "bot_state", lambda: state)
    window._request_exit()
    window.live_view.close.assert_called_once()
    window.shell.close.assert_called_once()
    window.root.destroy.assert_called_once()


def test_paused_non_random_watchdog_is_visible(monkeypatch, tmp_path):
    record = tmp_path / "pid.json"
    record.write_text('{"watchdog_pid":1,"runner_pid":2,"phase":"paused","strategy":"567"}')
    monkeypatch.setattr(console, "PID_FILE", record)
    monkeypatch.setattr(console, "_is_our_process", lambda *_: False)
    monkeypatch.setattr(console, "selected_strategy", lambda: "567")
    assert console.bot_state() == "paused"


def test_orphaned_owned_runner_is_still_running(monkeypatch, tmp_path):
    record = tmp_path / "pid.json"
    record.write_text('{"watchdog_pid":1,"runner_pid":2,"phase":"running","strategy":"random"}')
    monkeypatch.setattr(console, "PID_FILE", record)
    monkeypatch.setattr(console, "_is_our_process", lambda pid, *_: pid == 2)
    assert console.bot_state() == "running"
