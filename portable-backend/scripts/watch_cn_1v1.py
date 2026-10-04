"""Keep the focused Tencent 1v1 runner alive in the current Windows session."""

# Native Chinese operational messages intentionally retain full-width punctuation.
# ruff: noqa: RUF001

import argparse
import ctypes
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil

from pyclashbot.utils.cn_error_report import BOT_LOG_NAMES, capture_pause_report
from pyclashbot.utils.persistence import atomic_write_json
from pyclashbot.utils.process_ownership import (
    ExclusiveFileLock,
    OwnershipError,
    process_record,
    read_process_state,
    stop_requested,
    verified_process,
)
from pyclashbot.utils.runtime_config import RESOURCE_ROOT, component_command, load_runtime_config

REPO = RESOURCE_ROOT
RUNNER = REPO / "scripts" / "run_cn_1v1.py"
RESTART_DELAY_SECONDS = 10
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def _report_pause(args, state):
    """The runner has stopped; collect evidence without restarting or clicking."""
    outputs = Path(args.log).resolve().parent
    trace_name = "cn-random-mastery.jsonl" if args.strategy == "random" else f"cn-{args.strategy}-strategy.jsonl"
    paths = (Path(args.log), Path(args.watchdog_log), outputs / trace_name)
    try:
        report = capture_pause_report(
            output_dir=outputs / "error-reports",
            adb=args.adb,
            serial=args.serial,
            pid_file=Path(args.pid_file),
            state_path=outputs
            / ("random-mastery-live-status.json" if args.strategy == "random" else "567-live-status.json"),
            log_paths=tuple(path for path in paths if path.name in BOT_LOG_NAMES),
            state=state,
        )
        logging.info("暂停错误报告已保存：%s", report)
    except (OSError, ValueError, RuntimeError) as error:
        # Diagnostics must never change process/device ownership or respawn a
        # paused runner just because a report could not be written.
        logging.error("暂停错误报告无法保存：%s", error)


def _cleanup_failed_spawn(process):
    """A metadata failure must not leave the just-created input owner orphaned."""
    children = []
    try:
        parent = psutil.Process(process.pid)
        for child in parent.children(recursive=True):
            owned = verified_process(child.pid, RUNNER, child.create_time())
            if owned is not None:
                children.append(owned)
    except psutil.Error:
        pass
    for child in children:
        try:
            child.terminate()
        except psutil.NoSuchProcess:
            pass
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _publish_user_stop(pid_file):
    atomic_write_json(
        pid_file,
        {**read_process_state(pid_file), "phase": "stopped", "exit_reason": "user_stopped"},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--memuc", required=True)
    parser.add_argument("--vm-index", type=int, default=0)
    parser.add_argument("--log", required=True)
    parser.add_argument("--watchdog-log", required=True)
    parser.add_argument("--pid-file", required=True)
    parser.add_argument("--max-battles", type=int, default=0)
    parser.add_argument("--started-at-ns", type=int, default=time.time_ns())
    selection = load_runtime_config().data_root / "work" / "bot-selected-strategy.txt"
    default_strategy = selection.read_text(encoding="utf-8").strip() if selection.is_file() else "567"
    parser.add_argument("--strategy", choices=("567", "hog", "random"), default=default_strategy)
    args = parser.parse_args()
    if args.max_battles < 0:
        parser.error("--max-battles must be nonnegative")

    watchdog_log = Path(args.watchdog_log)
    watchdog_log.parent.mkdir(parents=True, exist_ok=True)
    pid_file = Path(args.pid_file)
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=watchdog_log,
        encoding="utf-8",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    watchdog_lock = ExclusiveFileLock(pid_file.with_suffix(".lock"))
    try:
        watchdog_lock.acquire()
    except OwnershipError:
        parser.exit(78, "Another watchdog already owns the bot process record.\n")

    try:
        if os.name == "nt":
            previous = ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
            if not previous:
                logging.warning("未能设置运行期间防睡眠状态")

        command = component_command(
            Path(sys.executable),
            RUNNER,
            "--adb",
            args.adb,
            "--serial",
            args.serial,
            "--memuc",
            args.memuc,
            "--vm-index",
            str(args.vm_index),
            "--log",
            args.log,
            "--strategy",
            args.strategy,
        )
        if args.max_battles:
            command.extend(["--max-battles", str(args.max_battles)])
        restarts = 0
        while True:
            if stop_requested(pid_file, args.started_at_ns):
                _publish_user_stop(pid_file)
                logging.info("启动或恢复已被用户停止，不再创建运行器")
                break
            with watchdog_log.open("a", encoding="utf-8") as stream:
                process = subprocess.Popen(
                    command,
                    cwd=REPO,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                try:
                    watchdog_record = process_record(os.getpid(), REPO / "scripts" / "watch_cn_1v1.py")
                    runner_record = process_record(process.pid, RUNNER)
                    state = {
                        "watchdog_pid": os.getpid(),
                        "runner_pid": process.pid,
                        "watchdog_created_at": watchdog_record["created_at"],
                        "runner_created_at": runner_record["created_at"],
                        "strategy": args.strategy,
                        "phase": "running",
                    }
                    atomic_write_json(pid_file, state)
                except (OSError, psutil.Error, ValueError, RuntimeError):
                    _cleanup_failed_spawn(process)
                    raise
                logging.info("运行器已启动 PID=%d", process.pid)
                try:
                    while True:
                        if stop_requested(pid_file, args.started_at_ns):
                            _cleanup_failed_spawn(process)
                            _publish_user_stop(pid_file)
                            logging.info("用户停止任务，不再恢复运行器")
                            return
                        try:
                            return_code = process.wait(timeout=0.25)
                            break
                        except subprocess.TimeoutExpired:
                            continue
                except KeyboardInterrupt:
                    process.terminate()
                    process.wait(timeout=15)
                    logging.info("用户停止运行器")
                    break
                if return_code == 0:
                    logging.info("运行器正常结束，不再自动重启")
                    atomic_write_json(
                        pid_file,
                        {
                            **state,
                            "exit_reason": "finite_run_ended" if args.max_battles else "normal_or_drained",
                            "max_battles": args.max_battles,
                            "phase": "stopped",
                            "ended_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        },
                    )
                    break
                if return_code == 78 or restarts >= 3:
                    logging.error("停止自动恢复: exit=%d，外层已重试=%d；需用户处理异常", return_code, restarts)
                    paused_state = {
                        **state,
                        "exit_reason": "recovery_exhausted",
                        "exit_code": return_code,
                        "restarts": restarts,
                        "phase": "paused",
                        "ended_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    atomic_write_json(pid_file, paused_state)
                    _report_pause(args, paused_state)
                    break
                if args.max_battles:
                    paused_state = {
                        **state,
                        "phase": "paused",
                        "exit_code": return_code,
                        "exit_reason": "finite_run_interrupted",
                    }
                    atomic_write_json(pid_file, paused_state)
                    _report_pause(args, paused_state)
                    break  # Never restart with a fresh quota and exceed a finite validation budget.
                restarts += 1
                logging.warning("运行器退出 code=%d，%d 秒后重启", return_code, RESTART_DELAY_SECONDS)
            restart_deadline = time.monotonic() + RESTART_DELAY_SECONDS
            while time.monotonic() < restart_deadline:
                if stop_requested(pid_file, args.started_at_ns):
                    break
                time.sleep(max(0, min(0.25, restart_deadline - time.monotonic())))

    finally:
        try:
            if os.name == "nt":
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        finally:
            watchdog_lock.release()


if __name__ == "__main__":
    main()
