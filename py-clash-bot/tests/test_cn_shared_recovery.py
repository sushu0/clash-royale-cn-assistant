"""Offline guards for shared strategy reconnect and interrupted-session recovery."""

import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from pyclashbot.bot import cn_1v1_loop as loop_module
from pyclashbot.bot.cn_1v1_loop import ChineseOneVOneLoop, RecoveryExhausted


@pytest.fixture
def runner(tmp_path, monkeypatch):
    installation = tmp_path / "MEmu"
    installation.mkdir()
    memuc = installation / "memuc.exe"
    memuc.touch()
    (installation / "MEmu.exe").touch()
    value = ChineseOneVOneLoop.__new__(ChineseOneVOneLoop)
    value.memu_path = memuc
    value.vm_index = 0
    value.serial = "127.0.0.1:21503"
    value.logger = Mock()
    value.device = SimpleNamespace(adb=Mock(return_value=subprocess.CompletedProcess([], 1, stdout="offline")))
    value.host_run = Mock(return_value=subprocess.CompletedProcess([], 0, stdout="Running"))
    value.host_launch = Mock()
    monkeypatch.setattr(loop_module.subprocess, "run", value.host_run)
    monkeypatch.setattr(loop_module.subprocess, "Popen", value.host_launch)
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(loop_module.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(loop_module.time, "sleep", lambda seconds: setattr(clock, "now", clock.now + seconds))
    return value


def test_online_device_does_not_query_or_launch_vm(runner):
    runner.device.adb.return_value = subprocess.CompletedProcess([], 0, stdout="device")
    runner._reconnect()
    runner.host_run.assert_not_called()
    runner.host_launch.assert_not_called()


def test_running_vm_only_reconnects_adb_without_memuc_start_or_gui(runner):
    runner._reconnect()
    assert [call.args[0] for call in runner.host_run.call_args_list] == [
        [str(runner.memu_path), "isvmrunning", "-i", "0"],
    ]
    runner.host_launch.assert_not_called()
    runner.device.adb.assert_any_call(f"connect {runner.serial}", timeout=20)


def stopped_vm(runner, output="0,MEmu,0,0,0,0\n", returncode=0):
    runner.host_run.side_effect = [
        subprocess.CompletedProcess([], 0, stdout="NotRunning"),
        subprocess.CompletedProcess([], returncode, stdout=output),
    ]


def test_stopped_unique_vm_zero_uses_same_installation_gui_without_arguments(runner):
    stopped_vm(runner)
    runner.device.adb.side_effect = [
        subprocess.CompletedProcess([], 1, stdout="offline"),
        subprocess.CompletedProcess([], 0, stdout="device"),
    ]
    runner._reconnect()
    runner.host_launch.assert_called_once_with(
        [str(runner.memu_path.with_name("MEmu.exe"))],
        cwd=runner.memu_path.parent,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert all("start" not in call.args[0] for call in runner.host_run.call_args_list)


@pytest.mark.parametrize(
    ("returncode", "output"),
    [
        (0, "0,MEmu,0,0,0,0\n1,Other,0,0,0,0\n"),
        (0, "1,Other,0,0,0,0\n"),
        (0, ""),
        (0, "0\n"),
        (1, "0,MEmu,0,0,0,0\n"),
    ],
)
def test_stopped_ambiguous_or_multiple_vms_never_launch(runner, returncode, output):
    stopped_vm(runner, output, returncode)
    with pytest.raises(RecoveryExhausted, match="唯一的 0 号"):
        runner._reconnect()
    runner.host_launch.assert_not_called()
    assert runner.device.adb.call_count == 1


def test_nonzero_vm_index_is_refused_before_host_control(runner):
    runner.vm_index = 1
    with pytest.raises(RecoveryExhausted, match="本任务的 0 号"):
        runner._reconnect()
    runner.host_run.assert_not_called()
    runner.host_launch.assert_not_called()


@pytest.mark.parametrize(("returncode", "output"), [(1, "NotRunning"), (0, "unknown"), (0, "")])
def test_unconfirmed_vm_state_cannot_trigger_launch(runner, returncode, output):
    runner.host_run.return_value = subprocess.CompletedProcess([], returncode, stdout=output)
    with pytest.raises(RecoveryExhausted, match="无法确认模拟器运行状态"):
        runner._reconnect()
    runner.host_launch.assert_not_called()
    assert runner.host_run.call_count == 1


def test_vm_query_timeout_is_terminal_and_never_launches(runner):
    runner.host_run.side_effect = subprocess.TimeoutExpired("isvmrunning", 15)
    with pytest.raises(RecoveryExhausted, match="状态查询或启动失败"):
        runner._reconnect()
    runner.host_launch.assert_not_called()


def test_stopped_vm_adb_readiness_has_ninety_second_limit(runner):
    stopped_vm(runner)
    with pytest.raises(RecoveryExhausted, match="90秒内 ADB 未就绪"):
        runner._reconnect()
    runner.host_launch.assert_called_once()
    assert runner.device.adb.call_count == 91
    assert all("start" not in call.args[0] for call in runner.host_run.call_args_list)


@pytest.mark.parametrize("strategy", ["567", "hog"])
def test_interrupted_dialog_uses_existing_recovery_without_any_relogin_tap(runner, strategy):
    runner.strategy_name = strategy
    runner.vision = SimpleNamespace(classify=lambda _: ("connection_interrupted", None))
    runner._recover = Mock()
    runner._tap = Mock()
    runner._step(np.zeros((633, 419, 3), np.uint8))
    runner._recover.assert_called_once_with("已确认连接中断及重新登录提示")
    runner._tap.assert_not_called()


def test_interrupted_dialog_existing_recovery_limit_stays_terminal(runner):
    runner.vision = SimpleNamespace(classify=lambda _: ("connection_interrupted", None))
    runner.recovery_attempts = 3
    runner._trace = Mock()
    runner._tap = Mock()
    with pytest.raises(RecoveryExhausted):
        runner._step(np.zeros((633, 419, 3), np.uint8))
    runner.device.adb.assert_not_called()
    runner.host_run.assert_not_called()
    runner.host_launch.assert_not_called()
    runner._tap.assert_not_called()
