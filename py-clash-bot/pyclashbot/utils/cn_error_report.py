"""Bounded, replay-safe local evidence for a paused Chinese-client robot.

Only bot-owned state and explicitly allowlisted bot logs are inspected. No
environment, command lines, browser/session data, or credential stores are read.
ADB is used exclusively for ``exec-out screencap -p``; no game input is sent.
"""

# Native Chinese report text intentionally retains full-width punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import stat
import subprocess
import threading
from concurrent.futures import Future
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psutil
from PIL import Image

from pyclashbot.utils.persistence import atomic_write_bytes, atomic_write_json
from pyclashbot.utils.process_ownership import ExclusiveFileLock, OwnershipError

BOT_LOG_NAMES = frozenset(
    {
        "cn-battles-live.log",
        "cn-watchdog.log",
        "cn-random-mastery.jsonl",
        "cn-mastery-rewards.jsonl",
        "cn-567-strategy.jsonl",
        "cn-hog-strategy.jsonl",
    }
)
MAX_STATE_BYTES = 256 * 1024
MAX_LOG_BYTES = 64 * 1024
MAX_PNG_BYTES = 12 * 1024 * 1024
MAX_CATALOG_REPORT_BYTES = 4 * 1024 * 1024
SHANGHAI = timezone(timedelta(hours=8))
SECRET_KEY = re.compile(
    r"(?:password|passwd|secret|token|cookie|authorization|api[_-]?key|private[_-]?key|verification[_-]?code)", re.I
)
SECRET_VALUE = re.compile(
    r"""(?i)(\b(?:password|passwd|secret|token|cookie|authorization|api[_-]?key|private[_-]?key|verification[_-]?code)\s*[:=]\s*)("[^"]*"|'[^']*'|[^\s,;]+)"""
)
BEARER = re.compile(r"(?i)\bBearer\s+[^\s,;]+")
PRIVATE_HEADER = re.compile(r"(?im)(\b(?:cookie|authorization)\s*:\s*)[^\r\n]*")


def _safe(value):
    if isinstance(value, dict):
        return {str(key): "[已脱敏]" if SECRET_KEY.search(str(key)) else _safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe(item) for item in value]
    if isinstance(value, str):
        return BEARER.sub("Bearer [已脱敏]", PRIVATE_HEADER.sub(r"\1[已脱敏]", SECRET_VALUE.sub(r"\1[已脱敏]", value)))
    return value


def _read_snapshot(path):
    if path is None:
        return {}, None
    try:
        with Path(path).open("rb") as stream:
            data = stream.read(MAX_STATE_BYTES + 1)
        if len(data) > MAX_STATE_BYTES:
            raise ValueError("状态文件超过 256 KiB 采集上限")
        parsed = json.loads(data)
        if not isinstance(parsed, dict):
            raise ValueError("状态文件不是 JSON 对象")
        return _safe(parsed), None
    except (OSError, ValueError, UnicodeDecodeError) as error:
        return {}, _safe(str(error))


def _log_tail(path):
    try:
        with path.open("rb") as stream:
            size = stream.seek(0, os.SEEK_END)
            offset = max(0, size - MAX_LOG_BYTES)
            stream.seek(offset)
            raw = stream.read(MAX_LOG_BYTES)
        lines = raw.decode("utf-8", errors="replace").splitlines()
        if offset and lines:
            lines = lines[1:]  # Discard a partial first line from the bounded tail.
        sanitized = []
        for line in lines[-120:]:
            try:
                parsed = json.loads(line)
            except ValueError:
                sanitized.append(_safe(line))
            else:
                sanitized.append(json.dumps(_safe(parsed), ensure_ascii=False))
        return {"path": str(path), "lines": sanitized, "error": None}
    except OSError as error:
        return {"path": str(path), "lines": [], "error": _safe(str(error))}


def _identity(state):
    rows = {}
    for component in ("watchdog", "runner"):
        pid = state.get(f"{component}_pid")
        expected_created = state.get(f"{component}_created_at")
        row = {"recorded_pid": pid, "recorded_created_at": expected_created, "alive": False, "identity_matches": False}
        if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0:
            try:
                process = psutil.Process(pid)
                created = process.create_time()
                row.update(
                    alive=process.is_running(),
                    actual_created_at=created,
                    executable=process.exe(),
                    identity_matches=isinstance(expected_created, (int, float))
                    and not isinstance(expected_created, bool)
                    and abs(created - expected_created) < 0.01,
                )
            except psutil.Error as error:
                row["error"] = type(error).__name__
        rows[component] = row
    return rows


def _pause_datetime(value):
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    return stamp if stamp.tzinfo is not None else stamp.replace(tzinfo=SHANGHAI)


def _catalog_unlinked(path, *, root=None, directory=False):
    """Do not follow a symlink or a Windows junction/reparse-point ancestor."""
    candidate = Path(os.path.abspath(path))
    if root is not None and not candidate.is_relative_to(root):
        return False
    try:
        for component in (candidate, *candidate.parents):
            attributes = component.lstat()
            if stat.S_ISLNK(attributes.st_mode) or getattr(attributes, "st_file_attributes", 0) & getattr(
                stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024
            ):
                return False
        return stat.S_ISDIR(candidate.lstat().st_mode) if directory else stat.S_ISREG(candidate.lstat().st_mode)
    except (OSError, ValueError):
        return False


def _catalog_report_json(path, root):
    if not _catalog_unlinked(path, root=root):
        return None
    try:
        before = path.lstat()
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                return None
            if not _catalog_unlinked(path, root=root):
                return None
            raw = stream.read(MAX_CATALOG_REPORT_BYTES + 1)
        if len(raw) > MAX_CATALOG_REPORT_BYTES:
            return None
        report = json.loads(raw)
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return report if isinstance(report, dict) else None


def _catalog_occurrence(report):
    snapshots = report.get("snapshots")
    snapshots = snapshots if isinstance(snapshots, dict) else {}
    pid_state = snapshots.get("pid_state")
    live_state = snapshots.get("live_state")
    pid_state = pid_state if isinstance(pid_state, dict) else {}
    live_state = live_state if isinstance(live_state, dict) else {}
    for value in (
        report.get("occurred_at"),
        pid_state.get("ended_at"),
        live_state.get("updated_at"),
        report.get("created_at"),
    ):
        timestamp = _pause_datetime(value)
        if timestamp is not None:
            try:
                return value, timestamp.timestamp()
            except (OverflowError, OSError, ValueError):
                continue
    return None, float("-inf")


def list_error_reports(output_dir) -> list[dict]:
    """Read every historical report, newest event first, without modifying it.

    Discovery never depends on ``latest-error-report.json`` or in-memory state.
    Corrupt/oversized JSON and linked directories/JSON files are ignored one at a
    time. Missing or linked Markdown/images are represented by null paths and an
    incomplete marker, so a useful JSON record remains visible. All returned
    resource paths are derived from safe local files, never from report metadata.
    """
    root = Path(os.path.abspath(output_dir))
    if os.name == "nt" and not root.is_relative_to(Path(r"D:\codex")):
        return []
    if not _catalog_unlinked(root, directory=True):
        return []
    try:
        folders = list(root.iterdir())
    except OSError:
        return []
    rows = []
    for folder in folders:
        if folder.name.startswith(".") or not _catalog_unlinked(folder, root=root, directory=True):
            continue
        report_path = folder / "report.json"
        report = _catalog_report_json(report_path, root)
        if report is None:
            continue
        markdown = folder / "report.md"
        image = folder / "game.png"
        has_markdown = _catalog_unlinked(markdown, root=root)
        has_image = _catalog_unlinked(image, root=root)
        screenshot = report.get("screenshot")
        screenshot = screenshot if isinstance(screenshot, dict) else {}
        screenshot_status = screenshot.get("status")
        screenshot_status = screenshot_status if isinstance(screenshot_status, str) else "unknown"
        runtime = report.get("runtime")
        runtime = _safe(runtime) if isinstance(runtime, dict) else {}
        event_id = report.get("event_id")
        has_identity = isinstance(event_id, str) and bool(event_id)
        event_id = event_id if has_identity else folder.name
        created_at = report.get("created_at")
        created_at = created_at if isinstance(created_at, str) else None
        occurred_at, sort_at = _catalog_occurrence(report)
        reason = report.get("reason")
        reason = _safe(reason) if isinstance(reason, str) and reason else "暂停原因未记录"
        pending = screenshot_status in {"pending", "capturing"}
        incomplete = (
            pending
            or not has_identity
            or _pause_datetime(created_at) is None
            or not has_markdown
            or (screenshot_status == "captured" and not has_image)
            or screenshot_status not in {"captured", "failed", "pending", "capturing"}
        )
        rows.append(
            {
                "event_id": event_id,
                "created_at": created_at,
                "occurred_at": occurred_at,
                "reason": reason,
                "report_dir": str(folder),
                "report_md": str(markdown) if has_markdown else None,
                "report_json": str(report_path),
                "game_png": str(image) if has_image and screenshot_status == "captured" else None,
                "screenshot_status": screenshot_status,
                "runtime": runtime,
                "session": runtime.get("session"),
                "pending": pending,
                "incomplete": incomplete,
                "_sort_at": sort_at,
            }
        )
    rows.sort(key=lambda row: (row["_sort_at"], row["created_at"] or "", row["report_dir"]), reverse=True)
    for row in rows:
        row.pop("_sort_at")
    return rows


def _pause_reason(reason, state, live, logs):
    if reason:
        return _safe(str(reason))
    # Authoritative current-state causes must beat any log history, including
    # deliberately injected acceptance faults and an unrelated older session.
    current_reason = state.get("reason") or live.get("reason")
    if current_reason:
        return _safe(str(current_reason))
    session = state.get("session") or live.get("session")
    for log in logs:
        if Path(log["path"]).name != "cn-random-mastery.jsonl":
            continue
        for line in reversed(log["lines"]):
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if (
                isinstance(event, dict)
                and event.get("event") == "paused"
                and session
                and event.get("session") == session
                and event.get("reason")
            ):
                return _safe(str(event["reason"]))
    paused_at = next(
        (
            stamp
            for value in (state.get("ended_at"), state.get("updated_at"), live.get("updated_at"))
            if (stamp := _pause_datetime(value)) is not None
        ),
        None,
    )
    # Text logs have no session ID. Consult them only when their timestamp
    # matches the current terminal pause; never recycle a historic failure.
    if paused_at is not None:
        for log in logs:
            for line in reversed(log["lines"]):
                if "恢复失败，运行器已停止:" not in line:
                    continue
                logged_at = _pause_datetime(line[:19])
                if logged_at is not None and abs((logged_at - paused_at).total_seconds()) <= 3:
                    return line.split("恢复失败，运行器已停止:", 1)[1].strip()
    return _safe(str(state.get("exit_reason") or "机器人进入暂停状态；日志中未找到更具体的原因"))


def _report_markdown(report):
    screenshot = report["screenshot"]
    lines = [
        "# 机器人暂停错误报告",
        "",
        f"- 采集时间：{report['created_at']}",
        f"- 事件 ID：{report['event_id']}",
        f"- 暂停原因：{report['reason']}",
        f"- 会话：{report['runtime'].get('session') or '未提供'}",
        f"- 策略：{report['runtime'].get('strategy') or '未提供'}",
        f"- 阶段：{report['runtime'].get('phase') or '未提供'}",
        f"- 截图：{screenshot['status']}",
        "",
        "采集范围仅包括机器人专属日志与状态快照；未读取环境变量、命令行、Cookie、密码或密钥。",
        "状态快照与日志中的敏感字段会脱敏；本报告没有发送游戏点击，也没有尝试自动恢复机器人。",
        "",
    ]
    if screenshot["status"] == "captured":
        lines.extend(["![暂停时的游戏画面](game.png)", ""])
    else:
        lines.extend([f"截图失败原因：{screenshot.get('error')}", ""])
    for title, data in (
        ("运行状态", report["runtime"]),
        ("PID 身份", report["process_identity"]),
        ("原始状态快照（敏感字段已脱敏）", report["snapshots"]),
        ("状态文件读取问题", report["snapshot_errors"]),
    ):
        lines.extend([f"## {title}", "", "```json", json.dumps(data, ensure_ascii=False, indent=2), "```", ""])
    for log in report["logs"]:
        lines.extend([f"## 日志末尾：{Path(log['path']).name}", ""])
        if log["error"]:
            lines.extend([f"读取失败：{log['error']}", ""])
        lines.extend(["```text", *log["lines"], "```", ""])
    return "\n".join(lines)


class ErrorReporter:
    """Capture one durable report per pause; background calls return a Future.

    Non-daemon workers finish their bounded screenshot before normal Python exit,
    so closing/traying the UI cannot silently discard a pending report. A shared
    event claim deduplicates independent watchdog and UI reporters.
    """

    def __init__(self, output_dir, *, adb, serial, pid_file=None, state_path=None, log_paths=(), screenshot_timeout=8):
        self.output_dir = Path(output_dir).resolve()
        if os.name == "nt" and not self.output_dir.is_relative_to(Path(r"D:\codex")):
            raise ValueError("错误报告必须保存到 D:\\codex")
        self.adb = Path(adb)
        self.serial = str(serial)
        self.pid_file = Path(pid_file).resolve() if pid_file is not None else None
        self.state_path = Path(state_path).resolve() if state_path is not None else None
        self.log_paths = tuple(Path(path).resolve() for path in log_paths)
        self.screenshot_timeout = float(screenshot_timeout)
        if not 0 < self.screenshot_timeout <= 15:
            raise ValueError("截图超时必须在 0 到 15 秒之间")
        outputs = self.output_dir.parent
        if self.state_path is not None and (
            self.state_path.parent != outputs
            or self.state_path.name not in {"random-mastery-live-status.json", "567-live-status.json"}
        ):
            raise ValueError("只允许采集同一 outputs 目录中的机器人状态")
        for path in self.log_paths:
            if path.parent != outputs or path.name not in BOT_LOG_NAMES:
                raise ValueError("只允许读取同一 outputs 目录下的已知机器人专属日志")
        if self.pid_file is not None and (
            self.pid_file.parent != outputs.parent / "work" or self.pid_file.name != "bot-processes.json"
        ):
            raise ValueError("PID 状态必须位于同一机器人数据目录")
        self.latest_index = self.output_dir / "latest-error-report.json"
        self._futures = {}
        self._guard = threading.Lock()

    def capture_pause(self, state=None, reason="", *, event_id=None, background=True):
        pid_state, pid_error = _read_snapshot(self.pid_file)
        live, live_error = _read_snapshot(self.state_path)
        state = {**pid_state, **_safe(state or {})}
        if state.get("phase") not in {"paused", "error"} and live.get("state") not in {"paused", "error"}:
            raise ValueError("仅在机器人已暂停或发生错误时生成错误报告")
        if event_id is None:
            # A UI may see the runner's pause just before the watchdog publishes
            # phase/exit_reason. Both must identify the same runner lifecycle.
            identity = {
                key: state.get(key)
                for key in ("watchdog_pid", "watchdog_created_at", "runner_pid", "runner_created_at")
            }
            if not any(identity.values()):
                identity = {
                    "session": live.get("session") or state.get("session"),
                    "updated_at": live.get("updated_at") or state.get("updated_at"),
                    "reason": reason or live.get("reason") or state.get("reason"),
                    "phase": state.get("phase") or live.get("state"),
                }
            event_id = json.dumps(identity, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(str(event_id).encode("utf-8")).hexdigest()[:24]
        with self._guard:
            if digest in self._futures:
                return self._futures[digest]
            future = Future()
            self._futures[digest] = future

        def run():
            try:
                result = self._capture(digest, state, live, reason, {"pid_state": pid_error, "live_state": live_error})
            except Exception as error:
                future.set_exception(error)
                logging.getLogger(__name__).error("暂停错误报告保存失败：%s", _safe(str(error)))
                with self._guard:
                    self._futures.pop(digest, None)  # Permit a repaired path to retry.
            else:
                future.set_result(result)

        if background:
            threading.Thread(target=run, name="cn-error-report", daemon=False).start()
        else:
            run()
        return future

    def _capture(self, digest, state, live, reason, snapshot_errors):
        events = self.output_dir / ".events"
        events.mkdir(parents=True, exist_ok=True)
        claim_path = events / f"{digest}.json"
        lock = ExclusiveFileLock(events / f"{digest}.lock")
        try:
            lock.acquire()
        except OwnershipError:
            claim, _ = _read_snapshot(claim_path)
            if claim.get("report_dir"):
                existing = Path(claim["report_dir"]).resolve()
                if existing.parent != self.output_dir:
                    raise ValueError("错误报告事件索引路径无效") from None
                return existing
            raise
        try:
            claim, _ = _read_snapshot(claim_path)
            if claim.get("complete") and claim.get("report_dir"):
                existing = Path(claim["report_dir"]).resolve()
                if existing.parent != self.output_dir:
                    raise ValueError("错误报告事件索引路径无效")
                return existing
            timestamp = datetime.now(SHANGHAI)
            folder = self.output_dir / f"{timestamp:%Y%m%d-%H%M%S-%f}-{digest}"
            if claim.get("report_dir"):
                previous = Path(claim["report_dir"]).resolve()
                if previous.parent != self.output_dir:
                    raise ValueError("错误报告事件索引路径无效")
                folder = previous
            folder.mkdir(parents=True, exist_ok=True)
            atomic_write_json(claim_path, {"event_id": digest, "report_dir": str(folder), "complete": False})
            logs = [_log_tail(path) for path in self.log_paths]
            report = {
                "schema": 1,
                "event_id": digest,
                "created_at": timestamp.isoformat(timespec="seconds"),
                "reason": _pause_reason(reason, state, live, logs),
                "runtime": {
                    "session": live.get("session") or state.get("session"),
                    "strategy": state.get("strategy") or live.get("strategy"),
                    "phase": state.get("phase") or live.get("state"),
                    "runner_state": live.get("state"),
                    "exit_reason": state.get("exit_reason"),
                    "exit_code": state.get("exit_code"),
                    "restarts": state.get("restarts"),
                    "serial": self.serial,
                },
                "process_identity": _identity(state),
                "snapshots": {"pid_state": state, "live_state": live},
                "snapshot_errors": {key: value for key, value in snapshot_errors.items() if value},
                "logs": logs,
                "screenshot": {
                    "status": "pending",
                    "method": "adb exec-out screencap -p",
                    "timeout_seconds": self.screenshot_timeout,
                },
                "game_input_sent": False,
            }
            # Persist the cause before touching ADB; an interrupted screenshot
            # leaves useful diagnostic evidence rather than an empty directory.
            atomic_write_json(folder / "report.json", report)
            atomic_write_bytes(folder / "report.md", _report_markdown(report).encode("utf-8"))
            report["screenshot"] = self._screenshot(folder)
            atomic_write_json(folder / "report.json", report)
            atomic_write_bytes(folder / "report.md", _report_markdown(report).encode("utf-8"))
            index = {
                "schema": 1,
                "event_id": digest,
                "created_at": report["created_at"],
                "reason": report["reason"],
                "report_dir": str(folder),
                "report_md": str(folder / "report.md"),
                "report_json": str(folder / "report.json"),
                "game_png": str(folder / "game.png") if report["screenshot"]["status"] == "captured" else None,
                "screenshot_status": report["screenshot"]["status"],
            }
            atomic_write_json(self.latest_index, index)
            atomic_write_json(claim_path, {"event_id": digest, "report_dir": str(folder), "complete": True})
            return folder
        finally:
            lock.release()

    def _screenshot(self, folder):
        result = {"method": "adb exec-out screencap -p", "timeout_seconds": self.screenshot_timeout}
        try:
            completed = subprocess.run(
                [str(self.adb), "-s", self.serial, "exec-out", "screencap", "-p"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=self.screenshot_timeout,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if completed.returncode:
                detail = _safe(completed.stderr.decode("utf-8", errors="replace")[-2000:])
                raise RuntimeError(f"ADB 截图退出码 {completed.returncode}: {detail}")
            if not completed.stdout.startswith(b"\x89PNG\r\n\x1a\n") or len(completed.stdout) > MAX_PNG_BYTES:
                raise ValueError("ADB 未返回有效大小的 PNG 图片")
            with Image.open(io.BytesIO(completed.stdout)) as picture:
                if picture.format != "PNG":
                    raise ValueError("ADB 图片不是 PNG")
                width, height = picture.size
                picture.verify()
            atomic_write_bytes(folder / "game.png", completed.stdout)
            return {
                **result,
                "status": "captured",
                "width": width,
                "height": height,
                "sha256": hashlib.sha256(completed.stdout).hexdigest(),
                "error": None,
            }
        except (
            OSError,
            ValueError,
            RuntimeError,
            SyntaxError,
            Image.DecompressionBombError,
            subprocess.TimeoutExpired,
        ) as error:
            return {**result, "status": "failed", "error": _safe(str(error)), "path": None}


def capture_pause_report(
    *,
    output_dir,
    adb,
    serial,
    state=None,
    reason="",
    event_id=None,
    pid_file=None,
    state_path=None,
    log_paths=(),
    screenshot_timeout=8,
):
    """Synchronous bounded helper used by the watchdog after input has stopped."""
    reporter = ErrorReporter(
        output_dir,
        adb=adb,
        serial=serial,
        pid_file=pid_file,
        state_path=state_path,
        log_paths=log_paths,
        screenshot_timeout=screenshot_timeout,
    )
    return reporter.capture_pause(state, reason, event_id=event_id, background=False).result()
