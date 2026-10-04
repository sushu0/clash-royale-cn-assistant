"""Offline lifecycle boundary regressions; no emulator commands or processes run."""

from __future__ import annotations

import base64
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from pyclashbot.emulators import adb_base, base, bluestacks, google_play, memu, process_safety
from pyclashbot.emulators.adb import AdbController
from pyclashbot.emulators.base import EmulatorNotReadyError


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, duration):
        self.now += duration


def bare(controller):
    instance = controller.__new__(controller)
    instance._auto_stop_on_del = False
    instance.logger = Mock()
    return instance


def test_adb_default_timeout_and_override_are_bounded(monkeypatch):
    controller = bare(adb_base.AdbBasedController)
    controller.device_serial = "127.0.0.1:21503"
    run = Mock(return_value=subprocess.CompletedProcess("adb", 0, "", ""))
    monkeypatch.setattr(adb_base.subprocess, "run", run)
    controller.adb("get-state")
    assert run.call_args.kwargs["timeout"] == 30
    controller.adb("devices", timeout=2)
    assert run.call_args.kwargs["timeout"] == 2
    with pytest.raises(ValueError, match="positive"):
        controller.adb("devices", timeout=0)


def test_adb_discovery_timeout_is_failure(monkeypatch):
    run = Mock(side_effect=subprocess.TimeoutExpired("adb devices", 30))
    monkeypatch.setattr(adb_base.subprocess, "run", run)
    monkeypatch.setattr(adb_base.AdbBasedController, "find_adb", lambda: None)
    assert adb_base.AdbBasedController.discover_devices() == []
    assert run.call_args.kwargs["timeout"] == 30


def test_app_launch_and_installed_package_require_exact_success():
    controller = bare(adb_base.AdbBasedController)
    controller.adb = Mock(return_value=subprocess.CompletedProcess("adb", 0, "package:com.example.extra\n", ""))
    assert controller.is_app_installed("com.example") is False
    controller.adb.return_value = subprocess.CompletedProcess("adb", 1, "package:com.example\n", "failed")
    assert controller.is_app_installed("com.example") is False
    controller._check_app_installed = Mock(return_value=True)
    with pytest.raises(EmulatorNotReadyError, match="Failed to launch"):
        controller.start_app("com.example")


@pytest.mark.parametrize("with_override", [False, True])
def test_display_effective_state_and_exact_restore(with_override):
    controller = bare(AdbController)
    size_text = "Physical size: 1080x1920\n"
    density_text = "Physical density: 420\n"
    if with_override:
        size_text += "Override size: 720x1280\n"
        density_text += "Override density: 240\n"

    def fake_adb(command):
        output = size_text if command == "shell wm size" else density_text if command == "shell wm density" else ""
        return subprocess.CompletedProcess("adb", 0, output, "")

    controller.adb = Mock(side_effect=fake_adb)
    assert controller.get_screen_props() == (("720x1280", 240) if with_override else ("1080x1920", 420))
    controller.handle_screen_size_and_density()
    assert controller.original_size == ("720x1280" if with_override else "1080x1920")
    # Restarting the bot must not replace the pre-bot snapshot with its own override.
    size_text = "Physical size: 1080x1920\nOverride size: 419x633\n"
    density_text = "Physical density: 420\nOverride density: 160\n"
    controller.handle_screen_size_and_density()
    controller.restore_original_screen_props()
    controller.adb.assert_any_call("shell wm size 720x1280" if with_override else "shell wm size reset")
    controller.adb.assert_any_call("shell wm density 240" if with_override else "shell wm density reset")


def test_display_unknown_original_refuses_mutation():
    controller = bare(AdbController)
    controller.adb = Mock(return_value=subprocess.CompletedProcess("adb", 1, "", "offline"))
    with pytest.raises(EmulatorNotReadyError, match="refusing"):
        controller.handle_screen_size_and_density()
    assert all(call.args[0] in {"shell wm size", "shell wm density"} for call in controller.adb.call_args_list)


def test_display_restore_failure_remains_observable_and_attempts_both_properties():
    controller = bare(AdbController)
    controller._original_screen_props = {"size_override": None, "density_override": 240}
    controller.adb = Mock(return_value=subprocess.CompletedProcess("adb", 1, "", "offline"))
    with pytest.raises(EmulatorNotReadyError, match="size, density"):
        controller.restore_original_screen_props()
    assert controller.adb.call_count == 2


@pytest.mark.parametrize(
    "value,expected",
    [
        ("cn", base.GAME_PACKAGES["cn"]),
        ("global", base.GAME_PACKAGES["global"]),
        (base.GAME_PACKAGES["global"], base.GAME_PACKAGES["global"]),
    ],
)
def test_game_client_can_be_selected_explicitly(monkeypatch, value, expected):
    monkeypatch.setenv("PYCLASHBOT_GAME_PACKAGE", value)
    assert base.configured_game_package() == expected


def test_game_client_preserves_default_and_rejects_injection(monkeypatch):
    monkeypatch.delenv("PYCLASHBOT_GAME_PACKAGE", raising=False)
    assert base.configured_game_package() == base.GAME_PACKAGES["cn"]
    monkeypatch.setenv("PYCLASHBOT_GAME_PACKAGE", "bad; exit")
    with pytest.raises(ValueError):
        base.configured_game_package()


def test_process_discovery_requires_exact_path_and_birth_time(monkeypatch, tmp_path):
    allowed = str(tmp_path / "google" / "Service.exe")
    unrelated = str(tmp_path / "other" / "Service.exe")
    fake = [
        SimpleNamespace(info={"pid": 1, "exe": allowed, "create_time": 10, "ppid": 0}),
        SimpleNamespace(info={"pid": 2, "exe": unrelated, "create_time": 11, "ppid": 0}),
        SimpleNamespace(info={"pid": 3, "exe": allowed, "create_time": None, "ppid": 0}),
    ]
    monkeypatch.setattr(process_safety.psutil, "process_iter", Mock(return_value=fake))
    assert [record.pid for record in process_safety.installed_processes({allowed})] == [1]


@pytest.mark.parametrize("changed", ["path", "birth"])
def test_reused_or_replaced_process_is_never_killed(monkeypatch, tmp_path, changed):
    path = process_safety.normalized_executable(str(tmp_path / "Service.exe"))
    record = process_safety.ProcessIdentity(123, 10, path, 0)
    proc = Mock()
    proc.exe.return_value = path if changed == "birth" else str(tmp_path / "other.exe")
    proc.create_time.return_value = 11 if changed == "birth" else 10
    monkeypatch.setattr(process_safety.psutil, "Process", Mock(return_value=proc))
    assert process_safety.stop_processes([record], timeout=1) is True
    proc.kill.assert_not_called()


def test_process_stop_reports_access_denied(monkeypatch, tmp_path):
    path = process_safety.normalized_executable(str(tmp_path / "Service.exe"))
    record = process_safety.ProcessIdentity(123, 10, path, 0)
    monkeypatch.setattr(process_safety.psutil, "Process", Mock(side_effect=process_safety.psutil.AccessDenied(123)))
    assert process_safety.stop_processes([record], timeout=1) is False


def test_instance_processes_require_exact_instance_argument(monkeypatch, tmp_path):
    path = process_safety.normalized_executable(str(tmp_path / "HD-Player.exe"))
    records = [process_safety.ProcessIdentity(i, 10, path, 0) for i in range(3)]
    monkeypatch.setattr(process_safety, "installed_processes", Mock(return_value=records))
    procs = []
    for args in ([path, "--instance", "Tiramisu64"], [path, "--instance", "Tiramisu64_1"], [path]):
        proc = Mock()
        proc.exe.return_value = path
        proc.create_time.return_value = 10
        proc.cmdline.return_value = args
        procs.append(proc)
    monkeypatch.setattr(process_safety.psutil, "Process", Mock(side_effect=lambda pid: procs[pid]))
    assert process_safety.instance_processes(path, "Tiramisu64") == [records[0]]


def test_google_allowlist_excludes_shared_adb_and_unrelated_installation(tmp_path):
    controller = bare(google_play.GooglePlayEmulatorController)
    controller.base_folder = str(tmp_path / "google")
    root = tmp_path / "google" / "current" / "emulator"
    root.mkdir(parents=True)
    for name in ("crosvm.exe", "adb.exe", "unrelated.exe"):
        (root / name).write_bytes(b"")
    paths = controller._managed_executables()
    assert paths == {str((root / "crosvm.exe").resolve())}


def test_google_lifecycle_rejects_unowned_transport():
    controller = bare(google_play.GooglePlayEmulatorController)
    controller.device_serial = "127.0.0.1:21503"
    controller._owned_processes = Mock()
    with pytest.raises(EmulatorNotReadyError, match="unowned"):
        controller.stop()
    controller._owned_processes.assert_not_called()


def test_google_stopping_cannot_loop_past_total_deadline(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(google_play.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(google_play.time, "sleep", clock.sleep)
    controller = bare(google_play.GooglePlayEmulatorController)
    controller.device_serial = controller.DEFAULT_DEVICE_SERIAL
    controller._owned_processes = Mock(return_value=[object()])
    controller.stop = Mock(return_value=True)
    with pytest.raises(EmulatorNotReadyError, match="timed out"):
        controller._stop_and_wait(timeout=0.25)
    assert clock.now == pytest.approx(0.25)
    assert all(0 < call.kwargs["timeout"] <= 0.25 for call in controller.stop.call_args_list)


def test_google_stop_passes_snapshot_to_identity_checked_termination(monkeypatch):
    controller = bare(google_play.GooglePlayEmulatorController)
    controller.device_serial = controller.DEFAULT_DEVICE_SERIAL
    records = [object()]
    controller._owned_processes = Mock(return_value=records)
    stop = Mock(return_value=True)
    monkeypatch.setattr(google_play, "stop_processes", stop)
    assert controller.stop(timeout=1) is True
    stop.assert_called_once_with(records, 1)


def test_memu_capture_is_bounded_and_never_returns_synthetic_success(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(memu.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(memu.time, "sleep", clock.sleep)
    pmc = Mock()
    pmc.send_adb_command_vm.return_value = "not an image"
    capture = memu.MemuScreenCapture(pmc)
    with pytest.raises(EmulatorNotReadyError, match="deadline"):
        capture[0]
    assert pmc.send_adb_command_vm.call_count == 3
    assert all(0 < call.kwargs["timeout"] <= 10 for call in pmc.send_adb_command_vm.call_args_list)
    with pytest.raises(EmulatorNotReadyError, match="index"):
        capture[None]


def test_memu_capture_valid_png_preserves_bgr():
    pmc = Mock()
    expected = np.zeros((2, 3, 3), dtype=np.uint8)
    expected[0, 0] = (12, 34, 56)
    ok, encoded = cv2.imencode(".png", expected)
    assert ok
    pmc.send_adb_command_vm.return_value = base64.b64encode(encoded).decode("ascii")
    assert np.array_equal(memu.MemuScreenCapture(pmc)[0], expected)


def test_memu_capture_timeout_consumes_only_total_budget(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(memu.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(memu.time, "sleep", clock.sleep)
    pmc = Mock()

    def timed_out(**kwargs):
        clock.now += kwargs["timeout"]
        raise subprocess.TimeoutExpired("memuc adb", kwargs["timeout"])

    pmc.send_adb_command_vm.side_effect = timed_out
    with pytest.raises(EmulatorNotReadyError, match="deadline"):
        memu.MemuScreenCapture(pmc)[0]
    assert clock.now == 10
    assert pmc.send_adb_command_vm.call_count == 1


def test_memu_low_level_helpers_all_receive_timeout(monkeypatch):
    pmc = memu.BoundedPyMemuc.__new__(memu.BoundedPyMemuc)
    run = Mock(return_value=(0, ""))
    monkeypatch.setattr(memu.PyMemuc, "memuc_run", run)
    assert pmc.list_vm_info() == []
    assert run.call_args.kwargs["timeout"] == 30
    with pytest.raises(ValueError, match="blocking"):
        pmc.memuc_run(["start"], non_blocking=True)


def test_memu_low_level_operations_respect_remaining_budget(monkeypatch):
    pmc = memu.BoundedPyMemuc.__new__(memu.BoundedPyMemuc)
    pmc.operation_deadline = 5
    clock = Clock()
    clock.now = 4
    monkeypatch.setattr(memu.time, "monotonic", clock.monotonic)
    run = Mock(return_value=(0, ""))
    monkeypatch.setattr(memu.PyMemuc, "memuc_run", run)
    pmc.list_vm_info()
    assert run.call_args.kwargs["timeout"] == 1
    clock.now = 5
    with pytest.raises(subprocess.TimeoutExpired):
        pmc.list_vm_info()
    assert run.call_count == 1


def test_memu_restart_stops_selected_vm_without_global_process_kill(monkeypatch):
    controller = bare(memu.MemuEmulatorController)
    controller.vm_index = 5
    controller.pmc = Mock()
    controller.pmc.operation_deadline = None
    controller._check_for_emulator_running = Mock(side_effect=[True, False])
    monkeypatch.setattr(memu.time, "sleep", Mock())
    processes = Mock(side_effect=AssertionError("global process iteration is forbidden"))
    monkeypatch.setattr(memu.psutil, "process_iter", processes)
    controller._close_everything_memu()
    call = controller.pmc.stop_vm.call_args
    assert call.kwargs["vm_index"] == 5
    assert 0 < call.kwargs["timeout"] <= 30
    assert controller.pmc.operation_deadline is None
    processes.assert_not_called()


def test_memu_stop_failure_blocks_reconfiguration():
    controller = bare(memu.MemuEmulatorController)
    controller.vm_index = 5
    controller.stop = Mock(return_value=False)
    controller.configure = Mock()
    controller.render_mode = "directx"
    with pytest.raises(EmulatorNotReadyError, match="did not stop"):
        controller.restart()
    controller.configure.assert_not_called()


def test_memu_unverifiable_screen_is_failure(monkeypatch):
    controller = bare(memu.MemuEmulatorController)
    controller.vm_index = 5
    controller.pmc = Mock()
    controller.screenshot = Mock(side_effect=EmulatorNotReadyError("capture failed"))
    monkeypatch.setattr(memu.time, "sleep", Mock())
    assert controller._check_vm_size() is False


def test_memu_discovery_requires_exact_managed_name():
    controller = bare(memu.MemuEmulatorController)
    controller.pmc = Mock()
    controller.pmc.list_vm_info.return_value = [{"index": 1, "title": "user-pyclashbot-136-backup"}]
    assert controller._get_clashbot_vm_index() is False
    controller.pmc.list_vm_info.return_value = [
        {"index": 1, "title": memu.EMULATOR_NAME},
        {"index": 2, "title": memu.EMULATOR_NAME},
    ]
    with pytest.raises(EmulatorNotReadyError, match="ambiguous"):
        controller._get_clashbot_vm_index()


@pytest.mark.parametrize(
    "internal,display,accepted",
    [
        ("Nougat64", "My unsigned-in game", False),
        ("Tiramisu64", "My unsigned-in game", False),
        ("Nougat64", "pyclashbot-136", False),
        ("Tiramisu64", "pyclashbot-136", True),
    ],
)
def test_bluestacks_only_explicit_managed_android13_is_accepted(internal, display, accepted):
    controller = bare(bluestacks.BlueStacksEmulatorController)
    controller.instance_name = "pyclashbot-136"
    controller.bs_conf_path = "mock-conf"
    controller.mim_meta_path = "mock-metadata"
    controller._read_text = Mock(
        return_value=f'bst.instance.{internal}.display_name="{display}"\n'
        f'bst.instance.{internal}.google_account_logins=""\n'
        f'bst.instance.{internal}.adb_port="5555"\n'
    )
    controller._open_multi_instance_manager = Mock(side_effect=AssertionError("unrequested UI must not open"))
    controller._reuse_and_rename_internal = Mock(side_effect=AssertionError("user VM must not be renamed"))
    if accepted:
        controller._ensure_managed_instance()
        assert controller.internal_name == internal
        assert controller.instance_port == 5555
    else:
        with pytest.raises(EmulatorNotReadyError, match="managed"):
            controller._ensure_managed_instance()
    controller._open_multi_instance_manager.assert_not_called()
    controller._reuse_and_rename_internal.assert_not_called()


def test_bluestacks_renderer_defaults_and_server_recovery_are_scoped(monkeypatch):
    controller = bare(bluestacks.BlueStacksEmulatorController)
    controller.instance_name = "pyclashbot-136"
    controller.expected_dims = (419, 633)
    controller.render_settings = {}
    monkeypatch.setattr(bluestacks, "is_macos", lambda: False)
    conf, changed = controller._compose_instance_conf("", "Tiramisu64")
    assert changed
    assert 'graphics_renderer="dx"' in conf
    controller.device_serial = "127.0.0.1:5555"
    controller.adb = Mock()
    controller._reset_adb_server()
    controller.adb.assert_called_once_with("disconnect 127.0.0.1:5555")


def test_bluestacks_stop_uses_exact_owned_instance_and_rejects_other_display(monkeypatch):
    controller = bare(bluestacks.BlueStacksEmulatorController)
    controller.instance_name = "pyclashbot-136"
    controller.internal_name = "Tiramisu64"
    controller.emulator_executable_path = "D:\\BlueStacks\\HD-Player.exe"
    records = [object()]
    query = Mock(return_value=records)
    stop = Mock(return_value=True)
    monkeypatch.setattr(bluestacks, "instance_processes", query)
    monkeypatch.setattr(bluestacks, "stop_processes", stop)
    controller.stop()
    query.assert_called_once_with(controller.emulator_executable_path, "Tiramisu64")
    stop.assert_called_once_with(records, timeout=30)
    with pytest.raises(EmulatorNotReadyError, match="unmanaged"):
        controller.stop(display_name="My game")
