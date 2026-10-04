"""Offline desktop-shell behavior without launching or controlling a game."""

import ctypes
import os
import queue
import threading
import uuid
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest

from pyclashbot.interface import cn_desktop_shell as shell


def tray_with_fake_native(tmp_path):
    tray = shell._TrayWindow(tmp_path / "icon.ico", queue.Queue())
    tray.hwnd = 42
    tray._icon = 64
    tray._restart_message = 12345
    tray._api = cast(
        "shell._Win32",
        SimpleNamespace(
            user=SimpleNamespace(
                DestroyWindow=Mock(),
                PostQuitMessage=Mock(),
                DefWindowProcW=Mock(return_value=99),
                CreatePopupMenu=Mock(return_value=7),
                AppendMenuW=Mock(),
                GetCursorPos=Mock(),
                SetForegroundWindow=Mock(),
                TrackPopupMenu=Mock(return_value=shell.COMMAND_STOP),
                PostMessageW=Mock(),
                DestroyMenu=Mock(),
            ),
            shell=SimpleNamespace(Shell_NotifyIconW=Mock(return_value=True)),
        ),
    )
    return tray


def test_tooltip_obeys_utf16_limit_and_removes_nuls():
    tooltip = shell._tooltip("\x00准备运行" + "⚔" * 200 + "😀" * 200)
    assert "\x00" not in tooltip
    assert len(tooltip.encode("utf-16-le")) <= 254
    assert tooltip.startswith(shell.APP_TITLE)
    emoji_tooltip = shell._tooltip("😀" * 200)
    assert len(emoji_tooltip.encode("utf-16-le")) <= 254
    assert "\ufffd" not in emoji_tooltip


@pytest.mark.parametrize("running", [False, True])
def test_menu_prevents_duplicate_start_and_idle_stop(running):
    entries = {command: (text, flags) for command, text, flags in shell._menu_entries(running)}
    assert bool(entries[shell.COMMAND_START][1] & shell.MF_GRAYED) is running
    assert bool(entries[shell.COMMAND_STOP][1] & shell.MF_GRAYED) is not running
    assert entries[shell.COMMAND_SHOW] == ("显示主界面", 0)
    assert entries[shell.COMMAND_EXIT] == ("退出软件", 0)


@pytest.mark.parametrize("event", [shell.NIN_SELECT, shell.NIN_KEYSELECT, shell.WM_LBUTTONDBLCLK])
def test_native_callback_only_queues_restore(tmp_path, event):
    tray = tray_with_fake_native(tmp_path)
    # NOTIFYICON_VERSION_4 packs the icon ID in the upper lParam word.
    assert tray._handle_message(42, shell.WM_TRAY, 0, (1 << 16) | event) == 0
    assert tray.events.get_nowait() == "show"
    tray._api.user.DefWindowProcW.assert_not_called()


def test_explorer_restart_readds_icon_with_v4_protocol(tmp_path):
    tray = tray_with_fake_native(tmp_path)
    tray.icon_added = True
    tray._handle_message(42, tray._restart_message, 0, 0)
    calls = tray._api.shell.Shell_NotifyIconW.call_args_list
    assert [call.args[0] for call in calls] == [shell.NIM_ADD, shell.NIM_SETVERSION]
    assert tray.icon_added


def test_status_queue_coalesces_updates_and_keeps_latest_running_state(tmp_path):
    tray = tray_with_fake_native(tmp_path)
    tray.icon_added = True
    tray.update("正在连接", False)
    tray.update("正在对战", True)
    tray._apply_status()
    assert tray.running
    assert "正在对战" in tray.tooltip
    tray._api.shell.Shell_NotifyIconW.assert_called_once()
    assert tray._api.shell.Shell_NotifyIconW.call_args.args[0] == shell.NIM_MODIFY


def test_menu_selection_queues_action_and_always_destroys_menu(tmp_path):
    tray = tray_with_fake_native(tmp_path)
    tray.running = True
    tray._handle_message(42, shell.WM_TRAY, 0, shell.WM_CONTEXTMENU)
    assert tray.events.get_nowait() == "stop"
    tray._api.user.DestroyMenu.assert_called_once_with(7)
    tray._api.user.PostMessageW.assert_called_once_with(42, shell.WM_NULL, 0, 0)


def test_native_close_removes_icon_before_destroying_message_window(tmp_path):
    tray = tray_with_fake_native(tmp_path)
    tray.icon_added = True
    tray._handle_message(42, shell.WM_CLOSE, 0, 0)
    assert not tray.icon_added
    assert tray._api.shell.Shell_NotifyIconW.call_args.args[0] == shell.NIM_DELETE
    tray._api.user.DestroyWindow.assert_called_once_with(42)


def test_tk_dispatch_executes_callbacks_on_polling_thread():
    desktop = shell.DesktopShell.__new__(shell.DesktopShell)
    desktop._closed = False
    desktop._timer = "old"
    desktop._events = queue.Queue()
    desktop.root = SimpleNamespace(after=Mock(return_value="next"))
    threads = []
    desktop._callbacks = {"show": lambda: threads.append(threading.get_ident())}
    desktop._events.put("show")
    desktop._drain_events()
    assert threads == [threading.get_ident()]
    assert desktop._timer == "next"


@pytest.mark.skipif(os.name != "nt", reason="Native named mutex and event are Windows-only")
def test_real_single_instance_duplicate_only_signals_show_then_releases_handles():
    title = f"ClashAssistant.UnitTest.{uuid.uuid4().hex}"
    primary = shell.acquire_single_instance(title)
    duplicate = None
    replacement = None
    try:
        assert primary.is_primary
        duplicate = shell.acquire_single_instance(title)
        assert not duplicate.is_primary
        assert primary.consume_show_request()
        assert not primary.consume_show_request()
        duplicate.close()
        primary.close()
        replacement = shell.acquire_single_instance(title)
        assert replacement.is_primary
    finally:
        if replacement is not None:
            replacement.close()
        if duplicate is not None:
            duplicate.close()
        primary.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows ABI check")
def test_notify_icon_structure_matches_windows_abi():
    assert ctypes.sizeof(shell._NotifyIconData) == (976 if ctypes.sizeof(ctypes.c_void_p) == 8 else 956)
