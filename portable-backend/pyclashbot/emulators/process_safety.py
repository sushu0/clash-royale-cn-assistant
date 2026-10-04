"""Small, identity-checked process operations for emulator lifecycle adapters."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import psutil


def normalized_executable(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    created: float
    executable: str
    parent_pid: int


def installed_processes(executables: set[str]) -> list[ProcessIdentity]:
    """Snapshot only exact installed executable paths; names alone confer no ownership."""
    allowed = {normalized_executable(path) for path in executables}
    records = []
    for proc in psutil.process_iter(attrs=["pid", "exe", "create_time", "ppid"]):
        try:
            info = proc.info
            executable = normalized_executable(info["exe"]) if info.get("exe") else ""
            if executable not in allowed or info.get("create_time") is None:
                continue
            records.append(ProcessIdentity(info["pid"], info["create_time"], executable, info["ppid"]))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
            continue
    return records


def stop_processes(records: list[ProcessIdentity], timeout: float) -> bool:
    """Terminate a snapshot, checking path and birth time again to reject reused PIDs."""
    deadline = time.monotonic() + timeout
    survivors = []
    # Descendants are stopped before their parents. Do not ask the OS to kill an
    # unsnapshotted tree: a child may belong to a different VM or be a shared ADB.
    parents = {record.parent_pid for record in records}
    ordered = sorted(records, key=lambda record: record.pid in parents)
    for record in ordered:
        if time.monotonic() >= deadline:
            return False
        try:
            proc = psutil.Process(record.pid)
            if proc.create_time() != record.created or normalized_executable(proc.exe()) != record.executable:
                continue
            proc.kill()
            survivors.append(proc)
        except psutil.NoSuchProcess:
            continue
        except (psutil.AccessDenied, psutil.ZombieProcess, OSError):
            return False
    for proc in survivors:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        try:
            proc.wait(timeout=remaining)
        except psutil.NoSuchProcess:
            continue
        except (psutil.TimeoutExpired, psutil.AccessDenied):
            return False
    return True


def instance_processes(executable: str, internal_name: str) -> list[ProcessIdentity]:
    """Match a known installation and an exact instance argument, never a window title."""
    matches = []
    for record in installed_processes({executable}):
        try:
            proc = psutil.Process(record.pid)
            if proc.create_time() != record.created or normalized_executable(proc.exe()) != record.executable:
                continue
            args = proc.cmdline()
            for index, arg in enumerate(args):
                if arg == f"--instance={internal_name}" or (
                    arg == "--instance" and index + 1 < len(args) and args[index + 1] == internal_name
                ):
                    matches.append(record)
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
            continue
    return matches
