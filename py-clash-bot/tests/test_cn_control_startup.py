"""Offline checks for the control console's MEmu startup and readiness gates."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

path = Path(__file__).resolve().parents[1] / "scripts" / "cn_bot_control.py"
spec = importlib.util.spec_from_file_location("cn_control_startup_tests", path)
assert spec is not None and spec.loader is not None
console = importlib.util.module_from_spec(spec)
spec.loader.exec_module(console)


@pytest.fixture
def offline_startup(tmp_path, monkeypatch):
    installation = tmp_path / "Microvirt" / "MEmu"
    installation.mkdir(parents=True)
    for name, target in {
        "PYTHON": tmp_path / "python.exe",
        "ADB": tmp_path / "adb.exe",
        "MEMUC": installation / "memuc.exe",
        "WATCHDOG": tmp_path / "watch_cn_1v1.py",
    }.items():
        target.touch()
        monkeypatch.setattr(console, name, target)
    for name in ("BATTLE_LOG", "WATCHDOG_LOG", "PID_FILE"):
        monkeypatch.setattr(console, name, tmp_path / name)
    monkeypatch.setattr(console, "REPO", tmp_path)
    monkeypatch.setattr(console, "selected_strategy", lambda: "random")
    monkeypatch.setattr(console, "bot_state", Mock(side_effect=["stopped", "running"]))

    state = SimpleNamespace(
        vm_status=(0, "stopped"),
        vm_list=(0, "0,MEmu,0,0,0,0\n"),
        adb_results=[(0, "device")],
        boot_results=[(0, "1")],
        connect_results=[(0, "connected")],
        command_advances={},
        timed_calls=[],
        package_results=[(0, f"package:{console.PACKAGE}")],
        package_advances=[0.0],
        android_ready_at=None,
        package_started_at=None,
        memu_exe=installation / "MEmu.exe",
        clock=SimpleNamespace(now=0.0, sleeps=[]),
    )

    def next_result(results):
        result = results[0]
        if len(results) > 1:
            results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def fake_run(command, timeout=20):
        state.timed_calls.append((command, timeout, state.clock.now))
        for marker, seconds in state.command_advances.items():
            if marker in command:
                state.clock.now += min(seconds, timeout)
        if command == [str(console.MEMUC), "isvmrunning", "-i", "0"]:
            returncode, output = state.vm_status
        elif command == [str(console.MEMUC), "listvms"]:
            returncode, output = state.vm_list
        elif command == [str(console.ADB), "-s", console.SERIAL, "get-state"]:
            returncode, output = next_result(state.adb_results)
        elif command == [
            str(console.ADB),
            "-s",
            console.SERIAL,
            "shell",
            "getprop",
            "sys.boot_completed",
        ]:
            returncode, output = next_result(state.boot_results)
            if returncode == 0 and output.strip() == "1" and state.clock.now < 90:
                state.android_ready_at = state.clock.now
        elif command == [str(console.ADB), "connect", console.SERIAL]:
            returncode, output = next_result(state.connect_results)
        elif command == [
            str(console.ADB),
            "-s",
            console.SERIAL,
            "shell",
            "pm",
            "list",
            "packages",
            console.PACKAGE,
        ]:
            assert state.android_ready_at is not None, "Package lookup must follow Android readiness"
            if state.package_started_at is None:
                state.package_started_at = state.clock.now
            state.clock.now += min(next_result(state.package_advances), timeout)
            returncode, output = next_result(state.package_results)
        elif command == [
            str(console.ADB),
            "-s",
            console.SERIAL,
            "shell",
            "monkey",
            "-p",
            console.PACKAGE,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        ]:
            returncode, output = 0, "Events injected: 1"
        else:
            pytest.fail(f"Unexpected subprocess command: {command!r}")
        return SimpleNamespace(returncode=returncode, stdout=output, stderr="")

    def fake_sleep(seconds):
        state.clock.sleeps.append(seconds)
        state.clock.now += seconds

    state.run = Mock(side_effect=fake_run)
    state.popen = Mock()
    monkeypatch.setattr(console, "_run", state.run)
    monkeypatch.setattr(console.subprocess, "Popen", state.popen)
    monkeypatch.setattr(
        console.subprocess,
        "run",
        Mock(side_effect=AssertionError("Direct subprocess.run is forbidden in offline tests")),
    )
    monkeypatch.setattr(
        console,
        "time",
        SimpleNamespace(monotonic=lambda: state.clock.now, sleep=fake_sleep),
    )
    return state


def test_only_vm_zero_starts_installation_gui_and_recovers_adb(offline_startup):
    state = offline_startup
    state.memu_exe.touch()
    state.adb_results = [(0, "offline"), (0, "device")]

    assert "已启动" in console.ControlWindow._start_worker()

    gui, watchdog = state.popen.call_args_list
    assert gui.args == ([str(state.memu_exe)],)
    assert gui.kwargs == {
        "cwd": console.MEMUC.parent,
        "stdin": console.subprocess.DEVNULL,
        "stdout": console.subprocess.DEVNULL,
        "stderr": console.subprocess.DEVNULL,
        "creationflags": getattr(console.subprocess, "CREATE_NO_WINDOW", 0),
    }
    assert watchdog.args[0][:2] == [str(console.PYTHON), str(console.WATCHDOG)]
    assert watchdog.kwargs["cwd"] == console.REPO
    state.run.assert_any_call([str(console.MEMUC), "listvms"])
    state.run.assert_any_call([str(console.ADB), "connect", console.SERIAL], timeout=5)
    commands = [call.args[0] for call in state.run.call_args_list]
    assert all(command[:2] != [str(console.MEMUC), "start"] for command in commands)
    assert any("monkey" in command for command in commands)


@pytest.mark.parametrize(
    ("returncode", "output"),
    [
        (0, "0,MEmu,0,0,0,0\n1,Other,0,0,0,0\n"),
        (0, "1,MEmu,0,0,0,0\n"),
        (0, " \n\n"),
        (1, "0,MEmu,0,0,0,0\n"),
        (0, "0\n"),
    ],
    ids=["multiple-vms", "nonzero-vm", "empty-list", "query-failed", "malformed-row"],
)
def test_unclear_vm_list_refuses_all_launches(offline_startup, returncode, output):
    state = offline_startup
    state.vm_list = returncode, output

    with pytest.raises(RuntimeError, match="只能自动启动唯一的 0 号 MEmu 实例"):
        console.ControlWindow._start_worker()

    state.popen.assert_not_called()
    assert [call.args[0] for call in state.run.call_args_list] == [
        [str(console.MEMUC), "isvmrunning", "-i", "0"],
        [str(console.MEMUC), "listvms"],
    ]


def test_missing_gui_executable_refuses_launch(offline_startup):
    state = offline_startup

    with pytest.raises(RuntimeError, match=r"缺少必要文件.*MEmu\.exe"):
        console.ControlWindow._start_worker()

    state.popen.assert_not_called()
    assert not any("get-state" in call.args[0] for call in state.run.call_args_list)


def test_adb_timeout_blocks_game_and_watchdog(offline_startup):
    state = offline_startup
    state.memu_exe.touch()
    state.adb_results = [(1, "offline")]

    with pytest.raises(RuntimeError, match="ADB 设备未连接或 Android 未完成启动"):
        console.ControlWindow._start_worker()

    state.popen.assert_called_once()
    assert state.popen.call_args.args == ([str(state.memu_exe)],)
    assert sum(state.clock.sleeps) == 90
    commands = [call.args[0] for call in state.run.call_args_list]
    assert any("connect" in command for command in commands)
    assert all("packages" not in command and "monkey" not in command for command in commands)


def test_connect_timeout_is_retried_until_android_is_ready(offline_startup):
    state = offline_startup
    state.vm_status = 0, "running"
    state.adb_results = [(1, "offline"), (1, "offline"), (0, "device")]
    state.connect_results = [
        console.subprocess.TimeoutExpired("adb connect", 5),
        (0, "connected"),
    ]

    assert "已启动" in console.ControlWindow._start_worker()

    commands = [call.args[0] for call in state.run.call_args_list]
    assert sum("connect" in command for command in commands) == 2
    assert commands.index(next(command for command in commands if "getprop" in command)) < (
        commands.index(next(command for command in commands if "packages" in command))
    )
    state.popen.assert_called_once()


def test_online_android_waits_for_boot_before_package_lookup(offline_startup):
    state = offline_startup
    state.vm_status = 0, "running"
    state.boot_results = [(0, "0"), (0, "0"), (0, "1")]

    assert "已启动" in console.ControlWindow._start_worker()

    commands = [call.args[0] for call in state.run.call_args_list]
    boot_positions = [index for index, command in enumerate(commands) if "getprop" in command]
    package_positions = [index for index, command in enumerate(commands) if "packages" in command]
    assert len(boot_positions) == 3
    assert package_positions == [boot_positions[-1] + 1]
    assert not any("connect" in command for command in commands)
    assert state.clock.sleeps[0:2] == [2, 2]


@pytest.mark.parametrize("command_kind", ["get-state", "getprop"])
@pytest.mark.parametrize("error_kind", ["timeout", "oserror"])
def test_transient_adb_read_failure_keeps_waiting(offline_startup, command_kind, error_kind):
    state = offline_startup
    state.vm_status = 0, "running"
    error = (
        console.subprocess.TimeoutExpired(command_kind, 5)
        if error_kind == "timeout"
        else OSError("temporary adb failure")
    )
    if command_kind == "get-state":
        state.adb_results = [error, (0, "device")]
    else:
        state.boot_results = [error, (0, "1")]

    assert "已启动" in console.ControlWindow._start_worker()

    commands = [call.args[0] for call in state.run.call_args_list]
    assert sum(command_kind in command for command in commands) == 2
    assert not any("connect" in command for command in commands)
    assert state.clock.sleeps[0] == 2
    state.popen.assert_called_once()


def test_online_android_that_never_boots_stops_at_deadline(offline_startup):
    state = offline_startup
    state.vm_status = 0, "running"
    state.boot_results = [(0, "0")]

    with pytest.raises(RuntimeError, match="ADB 设备未连接或 Android 未完成启动"):
        console.ControlWindow._start_worker()

    assert state.clock.now == 90
    state.popen.assert_not_called()
    commands = [call.args[0] for call in state.run.call_args_list]
    assert any("getprop" in command for command in commands)
    assert all(
        "connect" not in command and "packages" not in command and "monkey" not in command for command in commands
    )


@pytest.mark.parametrize("command_kind", ["get-state", "getprop", "connect"])
def test_each_readiness_timeout_respects_remaining_deadline(offline_startup, command_kind):
    state = offline_startup
    state.vm_status = 0, "running"
    state.command_advances = {"get-state": 5, "getprop": 5, "connect": 5}
    if command_kind == "get-state":
        state.command_advances["getprop"] = 4
    if command_kind == "connect":
        state.adb_results = [(1, "offline")]
    else:
        state.boot_results = [(0, "0")]

    with pytest.raises(RuntimeError, match="ADB 设备未连接或 Android 未完成启动"):
        console.ControlWindow._start_worker()

    readiness_calls = [
        (command, timeout, start)
        for command, timeout, start in state.timed_calls
        if any(marker in command for marker in ("get-state", "getprop", "connect"))
    ]
    assert all(0 < timeout <= min(5, 90 - start) for _, timeout, start in readiness_calls)
    assert any(command_kind in command and timeout < 5 for command, timeout, _ in readiness_calls)
    assert state.clock.now == 90
    assert sum(state.clock.sleeps) < 90
    state.popen.assert_not_called()
    commands = [call.args[0] for call in state.run.call_args_list]
    assert all("packages" not in command and "monkey" not in command for command in commands)


def test_boot_response_at_deadline_does_not_launch_game(offline_startup):
    state = offline_startup
    state.vm_status = 0, "running"
    state.boot_results = [(0, "0")] * 7 + [(0, "1")]
    state.command_advances = {"get-state": 5, "getprop": 5}

    with pytest.raises(RuntimeError, match="ADB 设备未连接或 Android 未完成启动"):
        console.ControlWindow._start_worker()

    assert state.boot_results == [(0, "1")]
    assert state.clock.now == 90
    state.popen.assert_not_called()
    commands = [call.args[0] for call in state.run.call_args_list]
    assert all("packages" not in command and "monkey" not in command for command in commands)


def test_missing_game_blocks_monkey_and_watchdog(offline_startup):
    state = offline_startup
    state.vm_status = 0, "running"
    state.package_results = [(0, "package:com.example.other")]

    with pytest.raises(RuntimeError, match="未找到腾讯版"):
        console.ControlWindow._start_worker()

    assert state.clock.now == state.package_started_at + 20
    assert sum("packages" in call.args[0] for call in state.run.call_args_list) >= 2
    state.popen.assert_not_called()
    assert not any("monkey" in call.args[0] for call in state.run.call_args_list)


@pytest.mark.parametrize("error_kind", ["nonzero", "timeout", "oserror"])
def test_transient_package_query_failure_recovers(offline_startup, error_kind):
    state = offline_startup
    state.vm_status = 0, "running"
    failure = {
        "nonzero": (1, "package manager is starting"),
        "timeout": console.subprocess.TimeoutExpired("adb shell pm", 5),
        "oserror": OSError("temporary adb failure"),
    }[error_kind]
    state.package_results = [failure, (0, f"package:{console.PACKAGE}")]

    assert "已启动" in console.ControlWindow._start_worker()

    commands = [call.args[0] for call in state.run.call_args_list]
    package_positions = [index for index, command in enumerate(commands) if "packages" in command]
    assert len(package_positions) == 2
    assert package_positions[-1] < commands.index(next(command for command in commands if "monkey" in command))
    assert state.clock.sleeps == [1]
    state.popen.assert_called_once()


def test_empty_package_list_waits_until_game_is_discovered(offline_startup):
    state = offline_startup
    state.vm_status = 0, "running"
    state.package_results = [
        (0, " \n\n"),
        (0, f"package:com.example.other\n  package:{console.PACKAGE}  \n"),
    ]

    assert "已启动" in console.ControlWindow._start_worker()

    assert sum("packages" in call.args[0] for call in state.run.call_args_list) == 2
    assert state.clock.sleeps == [1]
    state.popen.assert_called_once()


@pytest.mark.parametrize("error_kind", ["nonzero", "timeout", "oserror"])
def test_persistent_package_query_failure_reports_not_ready(offline_startup, error_kind):
    state = offline_startup
    state.vm_status = 0, "running"
    state.package_results = [
        {
            "nonzero": (1, "package manager is starting"),
            "timeout": console.subprocess.TimeoutExpired("adb shell pm", 5),
            "oserror": OSError("temporary adb failure"),
        }[error_kind]
    ]

    with pytest.raises(RuntimeError, match="Android 游戏包列表尚未就绪") as failure:
        console.ControlWindow._start_worker()

    assert "未找到腾讯版" not in str(failure.value)
    assert state.clock.now == state.package_started_at + 20
    state.popen.assert_not_called()
    assert not any("monkey" in call.args[0] for call in state.run.call_args_list)


@pytest.mark.parametrize("empty_queries", [1, 2])
def test_empty_package_queries_before_persistent_failure_do_not_prove_missing_game(
    offline_startup,
    empty_queries,
):
    state = offline_startup
    state.vm_status = 0, "running"
    state.package_results = [(0, "")] * empty_queries + [(1, "package manager stopped")]

    with pytest.raises(RuntimeError, match="Android 游戏包列表尚未就绪") as failure:
        console.ControlWindow._start_worker()

    assert "未找到腾讯版" not in str(failure.value)
    assert state.clock.now == state.package_started_at + 20
    state.popen.assert_not_called()
    assert not any("monkey" in call.args[0] for call in state.run.call_args_list)


def test_package_timeout_and_sleep_respect_remaining_deadline(offline_startup):
    state = offline_startup
    state.vm_status = 0, "running"
    state.package_results = [(0, "")]
    state.package_advances = [5, 5, 4.25, 0.0]

    with pytest.raises(RuntimeError, match="未找到腾讯版"):
        console.ControlWindow._start_worker()

    deadline = state.package_started_at + 20
    package_calls = [(timeout, start) for command, timeout, start in state.timed_calls if "packages" in command]
    assert all(0 < timeout <= min(5, deadline - start) for timeout, start in package_calls)
    assert package_calls[-1][0] == 0.75
    assert all(0 < duration <= 1 for duration in state.clock.sleeps)
    assert state.clock.sleeps[-1] == 0.75
    assert state.clock.now == deadline
    state.popen.assert_not_called()
    assert not any("monkey" in call.args[0] for call in state.run.call_args_list)


def test_package_window_remains_available_after_slow_android_boot(offline_startup):
    state = offline_startup
    state.vm_status = 0, "running"
    state.boot_results = [(0, "0")] * 44 + [(0, "1")]
    state.package_results = [(0, ""), (0, f"package:{console.PACKAGE}")]
    state.package_advances = [2, 0.0]

    assert "已启动" in console.ControlWindow._start_worker()

    assert state.android_ready_at == 88
    assert state.package_started_at == 88
    assert state.clock.now == 91
    assert sum("packages" in call.args[0] for call in state.run.call_args_list) == 2
    state.popen.assert_called_once()


def test_package_response_at_deadline_does_not_launch_game(offline_startup):
    state = offline_startup
    state.vm_status = 0, "running"
    state.package_results = [(1, "package manager is starting")] * 3 + [
        (0, f"package:{console.PACKAGE}"),
    ]
    state.package_advances = [5]

    with pytest.raises(RuntimeError, match="Android 游戏包列表尚未就绪"):
        console.ControlWindow._start_worker()

    assert state.package_results == [(0, f"package:{console.PACKAGE}")]
    assert state.clock.now == state.package_started_at + 20
    state.popen.assert_not_called()
    assert not any("monkey" in call.args[0] for call in state.run.call_args_list)


@pytest.mark.parametrize("package_name", [f"{console.PACKAGE}.clone", f"prefix.{console.PACKAGE}"])
def test_similar_package_name_does_not_launch_game(offline_startup, package_name):
    state = offline_startup
    state.vm_status = 0, "running"
    state.package_results = [(0, f"package:{package_name}")]

    with pytest.raises(RuntimeError, match="未找到腾讯版"):
        console.ControlWindow._start_worker()

    assert state.clock.now == state.package_started_at + 20
    state.popen.assert_not_called()
    assert not any("monkey" in call.args[0] for call in state.run.call_args_list)


def test_package_query_diagnostics_do_not_count_as_a_valid_scan(offline_startup):
    state = offline_startup
    state.vm_status = 0, "running"
    state.package_results = [(0, f"Error: package manager is restarting\npackage:{console.PACKAGE}")]

    with pytest.raises(RuntimeError, match="Android 游戏包列表尚未就绪"):
        console.ControlWindow._start_worker()

    assert state.clock.now == state.package_started_at + 20
    state.popen.assert_not_called()
    assert not any("monkey" in call.args[0] for call in state.run.call_args_list)


def test_running_vm_does_not_launch_another_gui(offline_startup):
    state = offline_startup
    state.vm_status = 0, "running"

    assert "已启动" in console.ControlWindow._start_worker()

    state.popen.assert_called_once()
    assert state.popen.call_args.args[0][:2] == [str(console.PYTHON), str(console.WATCHDOG)]
    assert not any("listvms" in call.args[0] for call in state.run.call_args_list)
