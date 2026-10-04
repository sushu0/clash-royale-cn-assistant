"""Exclusive input ownership and exact process identity for local bot entrypoints."""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

import psutil

from pyclashbot.utils.runtime_config import load_runtime_config


class OwnershipError(RuntimeError):
    """An existing process already owns this device or watchdog."""


class ExclusiveFileLock:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.stream = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt  # noqa: PLC0415 - Windows-only lock backend

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl  # noqa: PLC0415 - POSIX-only lock backend

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            stream.close()
            raise OwnershipError(f"Another bot process owns {self.path.name}") from error
        self.stream = stream
        return self

    def release(self):
        if self.stream is None:
            return
        try:
            self.stream.seek(0)
            if os.name == "nt":
                import msvcrt  # noqa: PLC0415 - Windows-only lock backend

                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl  # noqa: PLC0415 - POSIX-only lock backend

                fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        finally:
            self.stream.close()
            self.stream = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_args):
        self.release()


def device_lock_path() -> Path:
    # Preserve the existing CN first-byte lock so old and new running versions
    # cannot send input concurrently during a deployment.
    return load_runtime_config().data_root / "work" / "cn-runner.lock"


def process_record(pid: int, script: Path) -> dict:
    return {"pid": pid, "created_at": psutil.Process(pid).create_time(), "script": str(script.resolve())}


def verified_process(
    pid: int, script: Path, created_at: float | None = None, *, trusted_executables=()
) -> psutil.Process | None:
    if (
        not isinstance(created_at, (int, float))
        or isinstance(created_at, bool)
        or not math.isfinite(created_at)
        or created_at <= 0
    ):
        return None
    try:
        process = psutil.Process(int(pid))
        if created_at is not None and abs(process.create_time() - float(created_at)) > 0.01:
            return None
        command = process.cmdline()
        trusted = {
            load_runtime_config().python.resolve(),
            Path(sys.executable).resolve(),
            (Path(sys.base_prefix) / "python.exe").resolve(),
            (Path(sys.base_prefix) / "pythonw.exe").resolve(),
        }
        actual_exe = Path(process.exe()).resolve()
        entry = Path(command[1]) if len(command) > 1 else Path()
        if not entry.is_absolute():
            entry = Path(process.cwd()) / entry
        exact = len(command) > 1 and entry.resolve() == script.resolve() and actual_exe in trusted
        component_executables = {Path(path).resolve() for path in trusted_executables}
        if getattr(sys, "frozen", False):
            component_executables.add(Path(sys.executable).resolve())
        frozen = (
            actual_exe in component_executables
            and len(command) > 2
            and command[1] == "--component"
            and command[2] == script.name
        )
        return process if process.is_running() and (exact or frozen) else None
    except (psutil.Error, ValueError, TypeError, IndexError, OSError):
        return None


def read_process_state(path: Path) -> dict:
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
        return row if isinstance(row, dict) else {}
    except (OSError, ValueError):
        return {}


def stop_requested(pid_file: Path, started_at_ns: int) -> bool:
    """A stop issued after this launch also cancels unpublished/restarting children."""
    value = read_process_state(pid_file.with_suffix(".stop.json")).get("requested_at_ns")
    return isinstance(value, int) and not isinstance(value, bool) and value >= started_at_ns
