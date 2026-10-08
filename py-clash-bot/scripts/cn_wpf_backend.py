"""UTF-8 JSONL console bridge for the native WPF client; no Tk window is created."""

# Operational messages intentionally keep native Chinese punctuation.
# ruff: noqa: RUF001, PLC0415

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import sqlite3
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import time_ns

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psutil

from pyclashbot.utils.battle_history import BattleHistory, summarize
from pyclashbot.utils.cn_error_report import ErrorReporter, _safe, list_error_reports
from pyclashbot.utils.persistence import atomic_write_json
from pyclashbot.utils.process_ownership import ExclusiveFileLock, read_process_state, verified_process
from pyclashbot.utils.runtime_config import RESOURCE_ROOT
from pyclashbot.utils.shop_daily_history import ShopDailyHistoryStore
from scripts.stop_cn_1v1 import stop_bot

COMMANDS = frozenset({"snapshot", "start", "stop", "shop_daily", "reports", "shutdown"})
MAX_REQUEST_BYTES = 64 * 1024
SHANGHAI = timezone(timedelta(hours=8))


def updated_at():
    return datetime.now(SHANGHAI).isoformat(timespec="seconds")


def _empty_scope(strategy):
    return {
        "strategy": strategy,
        "total": summarize([]),
        "recent": summarize([]),
        "session": summarize([]),
        "latest_session": None,
        "records": [],
        "recent_results": [],
        "versions": [],
        "malformed_lines": 0,
        "conflicts": 0,
        "first_at": None,
        "last_at": None,
    }


def _safe_bot_tail(path, maximum_lines=80):
    try:
        with path.open("rb") as stream:
            size = stream.seek(0, os.SEEK_END)
            offset = max(0, size - 64 * 1024)
            stream.seek(offset)
            lines = stream.read(64 * 1024).splitlines()
        if offset and lines:
            lines = lines[1:]
        decoded = []
        for raw in lines[-maximum_lines:]:
            try:
                line = raw.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                # Historic watchdog files include redirected CP936 child
                # stderr alongside UTF-8 watchdog rows. Decode each complete
                # line independently; a whole-file fallback corrupts good UTF-8.
                line = None
                if path.name == "cn-watchdog.log":
                    try:
                        line = raw.decode("gb18030", errors="strict")
                    except UnicodeDecodeError:
                        pass
                if line is None:
                    line = raw.decode("utf-8", errors="replace") + " [编码待确认：原始日志字节仍保留]"
            decoded.append(_safe(line))
        return decoded
    except OSError:
        return []


class BackendBridge:
    """Own the API connection, derived history cache, and serialized controls.

    Creating this object neither starts a robot nor creates a GUI. Source/frozen
    controls reuse the existing readiness and process-identity gates. Read-only
    mode makes acceptance snapshots incapable of changing bot state, the history
    index, or error reports.
    """

    def __init__(self, *, control=None, read_only=False):
        if control is None:
            from scripts import cn_bot_control as control
        self.control = control
        self.read_only = bool(read_only)
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.busy = None
        self._operation = None
        self._start_operation = None
        self._shop_operation = None
        self.shop_path = self.control.OUTPUTS / "shop-daily-latest.json"
        self.shop_daily = read_process_state(self.shop_path)
        self.shop_history = ShopDailyHistoryStore(self.control.TASK_ROOT)
        self.shop_history_error = None
        self._launch_lock = threading.Lock()
        self._stop_unconfirmed = (
            read_process_state(self.control.PID_FILE.with_suffix(".stop.json")).get("confirmed") is False
        )
        self.history_error = None
        self.scopes = {scope: _empty_scope(scope) for scope in ("random", "567", "hog", "all")}
        self.reward_totals = {"rewards": 0, "coins": 0, "unknown_coin_items": 0}
        self._evidence_cache = {}
        self._history_thread = None
        self._report_thread = None
        self._report_future = None
        self._reporter = None

    def initialize(self):
        self._read_existing_history()
        if self.read_only:
            return
        self._initialize_shop_history()
        self._reporter = ErrorReporter(
            self.control.OUTPUTS / "error-reports",
            adb=self.control.ADB,
            serial=self.control.SERIAL,
            pid_file=self.control.PID_FILE,
            state_path=self.control.RANDOM_STATUS,
            log_paths=(self.control.BATTLE_LOG, self.control.WATCHDOG_LOG, self.control.RANDOM_TRACE),
        )
        self._history_thread = threading.Thread(target=self._history_loop, name="wpf-history", daemon=True)
        self._report_thread = threading.Thread(target=self._report_loop, name="wpf-pause-evidence", daemon=True)
        self._history_thread.start()
        self._report_thread.start()

    def _initialize_shop_history(self):
        """Recover old receipts once; never replay their game actions."""
        try:
            imported = self.shop_history.import_results()
            if imported["errors"]:
                raise ValueError("; ".join(imported["errors"]))
            for report in sorted(self.control.OUTPUTS.glob("wpf-desktop-shop-daily-*/ACCEPTANCE.json")):
                self.shop_history.import_verified_acceptance(report)
        except (OSError, ValueError, RuntimeError) as error:
            self.shop_history_error = _safe(str(error))
            logging.warning("Daily shop history recovery needs review: %s", self.shop_history_error)

    def _shop_display(self, latest):
        """Old WPF clients show today's totals through their existing fields."""
        display = copy.deepcopy(latest)
        try:
            today = self.shop_history.snapshot()
        except (OSError, ValueError, RuntimeError) as error:
            message = _safe(str(error))
            display.update(counter_scope="latest_run", statistics_error=message)
            display["message"] = "今日累计统计暂时无法读取，当前显示最近一次操作结果：" + message
            return display, None, message
        fields = ("free_claimed", "gold_purchased", "gems_skipped", "gold_spent")
        display.update({key: today[key] for key in fields})
        display.update(counter_scope="today", date=today["date"], daily_items=today["items"])
        display.setdefault(
            "state", "completed" if len(today["items"]) == 6 else "partial" if today["items"] else "idle"
        )
        message = (
            f"今日累计（{today['date']}）：免费 {today['free_claimed']} 件，"
            f"金币商品 {today['gold_purchased']} 件，花费 {today['gold_spent']:,} 金币，"
            f"跳过宝石商品 {today['gems_skipped']} 件。"
        )
        if latest.get("message"):
            message += " 最近一次操作：" + str(latest["message"])
        display["message"] = message
        return display, today, self.shop_history_error

    def _read_existing_history(self):
        path = self.control.HISTORY_DB
        if not path.is_file():
            return
        history = BattleHistory.__new__(BattleHistory)
        history.database = path.resolve()
        history._manifest_cache = {}
        history._evidence_cache = self._evidence_cache
        try:
            history.connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.15)
            history.connection.row_factory = sqlite3.Row
            try:
                scopes = {scope: history.snapshot(scope) for scope in self.scopes}
                rewards = history.reward_snapshot()
            finally:
                history.close()
        except (OSError, ValueError, sqlite3.Error) as error:
            with self.lock:
                self.history_error = _safe(str(error))
        else:
            with self.lock:
                self.scopes, self.reward_totals = scopes, rewards
                self.history_error = None

    def _history_loop(self):
        history = None
        try:
            while not self.stop_event.is_set():
                try:
                    if history is None:
                        history = BattleHistory(self.control.HISTORY_DB)
                    backlog = False
                    for scope in ("567", "hog"):
                        backlog |= history.ingest(
                            self.control.OUTPUTS / f"cn-{scope}-strategy.jsonl", scope, max_bytes=512_000
                        )
                    backlog |= history.ingest(self.control.RANDOM_TRACE, "random", max_bytes=512_000)
                    backlog |= history.ingest(self.control.REWARDS_TRACE, "rewards", max_bytes=512_000)
                    if not backlog:
                        scopes = {scope: history.snapshot(scope) for scope in self.scopes}
                        rewards = history.reward_snapshot()
                        with self.lock:
                            self.scopes, self.reward_totals = scopes, rewards
                            self.history_error = None
                except (OSError, ValueError, sqlite3.Error) as error:
                    with self.lock:
                        self.history_error = _safe(str(error))
                    logging.error("WPF history index update failed; retrying: %s", _safe(str(error)))
                    if history is not None:
                        try:
                            history.close()
                        except sqlite3.Error:
                            pass
                        history = None
                    self.stop_event.wait(1)
                    continue
                self.stop_event.wait(0.01 if backlog else 1)
        finally:
            if history is not None:
                history.close()

    def _report_loop(self):
        reporter = self._reporter
        assert reporter is not None  # initialize() sets this before starting the report thread.
        while not self.stop_event.is_set():
            try:
                if self._state_and_owner()[0] == "paused":
                    self._report_future = reporter.capture_pause()
            except (OSError, ValueError, RuntimeError) as error:
                logging.error("WPF pause evidence failed: %s", _safe(str(error)))
            self.stop_event.wait(2)

    def _state_and_owner(self):
        state = self.control.bot_state()
        if state in {"running", "starting"}:
            return state, None
        # An installed old desktop runner can remain alive during the WPF
        # cutover. Verify its exact identity before presenting or stopping it.
        known = {
            (self.control.OUTPUTS / "desktop-app-20261004" / "ClashAssistant.exe").resolve(),
            (self.control.OUTPUTS / "wpf-desktop-20261004" / "backend" / "ClashBackend.exe").resolve(),
        }
        outputs = self.control.OUTPUTS.resolve()
        known.update(
            path.resolve()
            for path in outputs.glob("wpf-desktop-*/backend/ClashBackend.exe")
            if path.resolve().is_relative_to(outputs)
        )
        record = read_process_state(self.control.PID_FILE)
        pending = read_process_state(self.control.PID_FILE.with_suffix(".pending.json"))
        pending_owner = verified_process(
            pending.get("watchdog_pid"),
            RESOURCE_ROOT / "scripts/watch_cn_1v1.py",
            pending.get("watchdog_created_at"),
            trusted_executables=known,
        )
        if pending_owner is not None:
            return "starting", Path(pending_owner.exe()).resolve()
        for role in ("runner", "watchdog"):
            pid, created = record.get(f"{role}_pid"), record.get(f"{role}_created_at")
            if (
                not isinstance(pid, int)
                or isinstance(pid, bool)
                or not isinstance(created, (int, float))
                or isinstance(created, bool)
            ):
                continue
            try:
                process = psutil.Process(pid)
                executable = Path(process.exe()).resolve()
                if (
                    executable not in known
                    or not abs(process.create_time() - created) < 0.01
                    or not process.is_running()
                ):
                    continue
                command = process.cmdline()
                expected = "run_cn_1v1.py" if role == "runner" else "watch_cn_1v1.py"
                if len(command) > 2 and command[1] == "--component" and command[2] == expected:
                    return "running" if role == "runner" else "starting", executable
            except (psutil.Error, OSError, ValueError, TypeError):
                continue
        return state, None

    def _stop_existing_owner(self, executable):
        stop_bot(self.control.PID_FILE, trusted_executables=(executable,))
        return "机器人已停止；MEmu 和游戏保持打开。"

    def snapshot(self):
        if self.read_only:
            self._read_existing_history()
        state, owner = self._state_and_owner()
        live = self.control.read_random_status()
        with self.lock:
            busy = self.busy
            scopes = copy.deepcopy(self.scopes)
            rewards = dict(self.reward_totals)
            history_error = self.history_error
            shop_daily = copy.deepcopy(self.shop_daily)
        shop_display, shop_today, shop_history_error = self._shop_display(shop_daily)
        if busy == "start" and state in {"stopped", "paused"}:
            state = "starting"
        elif (
            busy == "stop"
            or self._stop_unconfirmed
            or read_process_state(self.control.PID_FILE.with_suffix(".stop.json")).get("confirmed") is False
        ):
            state = "stopping"
        future = self._report_future
        return {
            "state": state,
            "selected_strategy": self.control.selected_strategy(),
            "updated_at": updated_at(),
            "live": _safe(live),
            "scopes": _safe(scopes),
            "reward_totals": rewards,
            "reports": list_error_reports(self.control.OUTPUTS / "error-reports"),
            "recent_events": sorted(
                _safe_bot_tail(self.control.BATTLE_LOG) + _safe_bot_tail(self.control.WATCHDOG_LOG)
            )[-120:],
            "runtime": {
                "data_root": str(self.control.TASK_ROOT),
                "adb": str(self.control.ADB),
                "memuc": str(self.control.MEMUC),
                "serial": self.control.SERIAL,
                "python": str(self.control.PYTHON),
                "vm_index": self.control.RUNTIME.vm_index,
                "active_owner_executable": str(owner) if owner else None,
            },
            "busy": busy,
            "shopDaily": _safe(shop_display),
            "shopDailyLastRun": _safe(shop_daily),
            "shopDailyToday": _safe(shop_today),
            "shop_daily_history_error": shop_history_error,
            "history_error": history_error,
            "error_report_pending": future is not None and not future.done(),
            "bridge_pid": os.getpid(),
            "frozen": bool(getattr(sys, "frozen", False)),
        }

    def prepare_control(self, command):
        """Reserve in input order so a queued Start cannot outlive a later Stop."""
        if self.read_only:
            raise RuntimeError("只读后台连接不能启动或停止机器人")
        with self.lock:
            if command in {"start", "shop_daily"} and (
                self._stop_unconfirmed
                or read_process_state(self.control.PID_FILE.with_suffix(".stop.json")).get("confirmed") is False
            ):
                raise RuntimeError("上次停止尚未确认，请先重试停止任务")
            if self.busy == "stop":
                raise RuntimeError("任务正在停止，请等待停止完成")
            if command in {"start", "shop_daily"} and (
                self.busy or self._start_operation is not None or self._shop_operation is not None
            ):
                raise RuntimeError("当前操作尚未完成，请等待当前操作结束")
            if command == "shop_daily":
                if self._state_and_owner()[0] not in {"stopped", "paused"}:
                    raise RuntimeError("请先停止对战任务，再购买每日精选")
                if (self.control.TASK_ROOT / "work" / "random-mastery" / "DRAIN").exists():
                    raise RuntimeError("停止或导航校准请求尚未处理，暂不能购买每日精选")
            operation = {"command": command, "cancel": threading.Event(), "done": threading.Event()}
            if command == "stop" and self._start_operation is not None:
                self._start_operation["cancel"].set()
                operation["cancelled_start"] = self._start_operation
            if command == "start":
                self._start_operation = operation
            if command == "shop_daily":
                self._shop_operation = operation
            if command == "stop" and self._shop_operation is not None:
                self._shop_operation["cancel"].set()
                operation["cancelled_shop"] = self._shop_operation
            self._operation, self.busy = operation, command
            return operation

    def _mark_stop_confirmation(self, confirmed):
        path = self.control.PID_FILE.with_suffix(".stop.json")
        request = read_process_state(path)
        atomic_write_json(path, {"requested_at_ns": time_ns(), **request, "confirmed": bool(confirmed)})

    def _publish_shop(self, result):
        value = {**result, "updated_at": updated_at()}
        atomic_write_json(self.shop_path, value)
        with self.lock:
            self.shop_daily = copy.deepcopy(value)
        try:
            self.shop_history.observe(value)
        except (OSError, ValueError, RuntimeError) as error:
            self.shop_history_error = _safe(str(error))
            logging.warning("Daily shop receipt history needs review: %s", self.shop_history_error)

    def _run_shop_daily(self, operation):
        self._publish_shop(
            {
                "state": "running",
                "status": "正在检查每日精选",
                "message": "正在确认模拟器操作权限。",
                "free_claimed": 0,
                "gold_purchased": 0,
                "gems_skipped": 0,
                "gold_spent": 0,
                "items": [],
            }
        )
        try:
            return self._execute_shop_daily(operation)
        except Exception as error:
            with self.lock:
                progress = copy.deepcopy(self.shop_daily)
            cancelled = operation["cancel"].is_set()
            progress.update(
                state="cancelled" if cancelled else "failed",
                status="每日精选购买已取消" if cancelled else "每日精选购买已停止",
                message="每日精选购买已取消。" if cancelled else _safe(str(error)),
            )
            self._publish_shop(progress)
            raise

    def _execute_shop_daily(self, operation):
        from pyclashbot.bot.cn_1v1_loop import TimedAdbController, _LogAdapter
        from pyclashbot.bot.cn_shop_daily_state import run_shop_daily

        if operation["cancel"].is_set():
            raise RuntimeError("每日精选购买已取消")
        # Use the exact same physical lock as source and frozen battle runners.
        # Checking the displayed state alone cannot fence another desktop client.
        with ExclusiveFileLock(self.control.PID_FILE.parent / "cn-runner.lock"):
            if self._state_and_owner()[0] not in {"stopped", "paused"}:
                raise RuntimeError("对战任务仍在运行，已取消每日精选购买")
            evidence = self.control.OUTPUTS / "shop-daily" / datetime.now(SHANGHAI).strftime("%Y%m%d-%H%M%S-%f")
            evidence.mkdir(parents=True, exist_ok=False)
            progress: dict[str, object] = {
                "state": "running",
                "status": "正在检查每日精选",
                "message": "正在连接游戏并识别商品。",
                "free_claimed": 0,
                "gold_purchased": 0,
                "gems_skipped": 0,
                "gold_spent": 0,
                "items": [],
                "evidence_dir": str(evidence),
            }
            self._publish_shop(progress)
            try:
                logger = _LogAdapter(logging.getLogger("shop-daily"))
                TimedAdbController.adb_path = str(self.control.ADB)
                emulator = TimedAdbController(logger, device_serial=self.control.SERIAL)

                def publish(result):
                    progress.update(result)
                    self._publish_shop(progress)

                result = run_shop_daily(
                    emulator, logger, cancel_event=operation["cancel"], on_update=publish, evidence_dir=evidence
                )
                progress.update(result)
                self._publish_shop(progress)
                atomic_write_json(evidence / "result.json", progress)
                return {"state": self._state_and_owner()[0], "message": progress["message"], "shopDaily": progress}
            except Exception as error:
                progress.update(state="failed", status="每日精选购买已停止", message=_safe(str(error)))
                self._publish_shop(progress)
                atomic_write_json(evidence / "result.json", progress)
                raise

    def command(self, command, *, operation=None):
        if command == "snapshot":
            return self.snapshot()
        if command == "reports":
            return {"reports": list_error_reports(self.control.OUTPUTS / "error-reports"), "updated_at": updated_at()}
        if command == "shutdown":
            return {
                "state": self._state_and_owner()[0],
                "message": "后台连接已关闭，机器人状态未改变。",
                "shutdown": True,
            }
        if command not in {"start", "stop", "shop_daily"}:
            raise ValueError("Unknown backend command")
        operation = operation or self.prepare_control(command)
        try:
            if command == "shop_daily":
                return self._run_shop_daily(operation)
            if command == "start" and operation["cancel"].is_set():
                raise RuntimeError("启动已取消：用户已停止任务")
            state, owner = self._state_and_owner()
            if command == "start" and state in {"running", "starting"}:
                return {"state": state, "message": "机器人已在运行，保留当前对战。"}
            if command == "start":

                def registered_watchdog(process):
                    try:
                        operation["watchdog_identity"] = (process.pid, psutil.Process(process.pid).create_time())
                    except psutil.NoSuchProcess:
                        pass  # A failed child can exit before metadata inspection.
                    else:
                        atomic_write_json(
                            self.control.PID_FILE.with_suffix(".pending.json"),
                            {"watchdog_pid": process.pid, "watchdog_created_at": operation["watchdog_identity"][1]},
                        )

                message = self.control.ControlWindow._start_worker(
                    cancel_event=operation["cancel"],
                    launch_lock=self._launch_lock,
                    on_watchdog_started=registered_watchdog,
                )
                if operation["cancel"].is_set():
                    raise RuntimeError("启动已取消：用户已停止任务")
            else:
                cancelled_start = operation.get("cancelled_start")
                cancelled_shop = operation.get("cancelled_shop")
                if cancelled_shop is not None and not cancelled_shop["done"].wait(35):
                    raise RuntimeError("每日精选取消尚未完成，停止状态未确认，请重试停止")
                with self._launch_lock:
                    pending_watchdog = (cancelled_start or {}).get("watchdog_identity")
                    if pending_watchdog is not None:
                        stop_bot(
                            self.control.PID_FILE,
                            pending_watchdog=pending_watchdog,
                            trusted_executables=(owner,) if owner is not None else (),
                        )
                        message = "机器人已停止；MEmu 和游戏保持打开。"
                    else:
                        message = (
                            "每日精选购买已停止；MEmu 和游戏保持打开。"
                            if cancelled_shop is not None
                            else (
                                self._stop_existing_owner(owner)
                                if owner is not None
                                else self.control.ControlWindow._stop_worker()
                            )
                        )
                if cancelled_start is not None and not cancelled_start["done"].wait(2):
                    raise RuntimeError("启动取消尚未完成，停止状态未确认，请重试停止")
                self._mark_stop_confirmation(True)
                with self.lock:
                    self._stop_unconfirmed = False
            return {"state": self._state_and_owner()[0], "message": message}
        except Exception:
            unconfirmed = command == "stop"
            with self.lock:
                stop_owns_cleanup = (
                    self._operation is not None
                    and self._operation.get("command") == "stop"
                    and self._operation.get("cancelled_start") is operation
                )
            if command == "start" and operation.get("watchdog_identity") is not None and not stop_owns_cleanup:
                try:
                    with self._launch_lock:
                        stop_bot(self.control.PID_FILE, pending_watchdog=operation["watchdog_identity"])
                except Exception:
                    unconfirmed = True
                    logging.exception("Unable to stop a failed startup watchdog")
            if unconfirmed:
                with self.lock:
                    self._stop_unconfirmed = True
                try:
                    self._mark_stop_confirmation(False)
                except OSError:
                    logging.exception("Unable to persist unconfirmed stop")
            raise
        finally:
            with self.lock:
                operation["done"].set()
                if self._start_operation is operation:
                    self._start_operation = None
                if self._shop_operation is operation:
                    self._shop_operation = None
                if self._operation is operation:
                    self._operation, self.busy = None, None

    def close(self):
        self.stop_event.set()
        self.cancel_pending_start()
        for worker in (self._history_thread, self._report_thread):
            if worker is not None:
                worker.join(timeout=1)

    def cancel_pending_start(self):
        with self.lock:
            if self._start_operation is not None:
                self._start_operation["cancel"].set()
            if self._shop_operation is not None:
                self._shop_operation["cancel"].set()


def serve(bridge, input_stream, output_stream):
    """Allow fast reads during a long readiness check; serialize input owners."""
    output_lock = threading.Lock()
    controls = ThreadPoolExecutor(max_workers=2, thread_name_prefix="wpf-control")

    def emit(identity, ok, data=None, error=None):
        response = {"id": identity, "ok": bool(ok), "data": _safe(data), "error": _safe(error)}
        with output_lock:
            output_stream.write(json.dumps(response, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
            output_stream.flush()

    def execute(identity, command, operation=None):
        try:
            data = bridge.command(command, operation=operation)
        except Exception as error:
            emit(identity, False, error=str(error))
        else:
            emit(identity, True, data=data)

    try:
        while True:
            line = input_stream.readline(MAX_REQUEST_BYTES + 1)
            if not line:
                break
            identity = None
            try:
                if len(line.encode("utf-8")) > MAX_REQUEST_BYTES:
                    if not line.endswith("\n"):
                        while not line.endswith("\n"):
                            line = input_stream.readline(MAX_REQUEST_BYTES + 1)
                            if not line:
                                break
                    raise ValueError("Backend request exceeds 64 KiB")
                request = json.loads(line)
                if not isinstance(request, dict) or set(request) - {"id", "command"}:
                    raise ValueError("Backend requests require only id and command")
                identity = request.get("id")
                if not isinstance(identity, str) or not identity or len(identity) > 128:
                    raise ValueError("Backend request id must be a nonempty string up to 128 characters")
                command = request.get("command")
                if not isinstance(command, str) or command not in COMMANDS:
                    raise ValueError("Unknown backend command")
            except (ValueError, TypeError) as error:
                emit(identity, False, error=str(error))
                continue
            if command in {"start", "stop", "shop_daily"}:
                try:
                    operation = bridge.prepare_control(command)
                except RuntimeError as error:
                    emit(identity, False, error=str(error))
                else:
                    controls.submit(execute, identity, command, operation)
            elif command == "shutdown":
                bridge.cancel_pending_start()
                controls.shutdown(wait=True)
                execute(identity, command)
                break
            else:
                execute(identity, command)
    finally:
        bridge.cancel_pending_start()
        controls.shutdown(wait=True)
        bridge.close()


def main():
    from scripts.cn_desktop_entry import configure_desktop_runtime

    if "--data-root" in sys.argv:
        position = sys.argv.index("--data-root")
        if position + 1 >= len(sys.argv):
            raise SystemExit("--data-root requires a D:\\codex directory")
        root = Path(sys.argv[position + 1]).resolve()
        if not root.is_relative_to(Path(r"D:\codex")):
            raise SystemExit("--data-root must stay under D:\\codex")
        os.environ["PYCLASHBOT_DATA_ROOT"] = str(root)
    configure_desktop_runtime()
    # Child components also redirect their StreamHandler into watchdog logs.
    # Configure before dispatch so newly written child rows use UTF-8 too.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) > 2 and sys.argv[1] == "--component":
        from scripts.cn_windows_entry import main as component_entry

        component_entry()
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--read-only", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
    bridge = BackendBridge(read_only=args.read_only)
    bridge.initialize()
    serve(bridge, sys.stdin, sys.stdout)


if __name__ == "__main__":
    main()
