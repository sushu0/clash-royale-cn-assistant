"""Durable local JSON publication and recoverable, validated snapshots."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".tmp-{uuid.uuid4().hex[:12]}")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(15):
            try:
                temporary.replace(path)
                return
            except PermissionError:
                if attempt == 14:
                    raise
                time.sleep(0.03)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_json(
    path: Path, value: Any, *, backup: bool = False, validator: Callable[[Any], bool] | None = None
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if backup and path.is_file():
        # Only retain syntactically valid old data. Never overwrite a valid backup
        # with a half-written or manually damaged primary snapshot.
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        else:
            if validator is None or validator(old):
                atomic_write_json(path.with_suffix(path.suffix + ".bak"), old)
    temporary = path.with_name(f".tmp-{uuid.uuid4().hex[:12]}")
    try:
        with temporary.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(15):
            try:
                temporary.replace(path)
                return
            except PermissionError:
                if attempt == 14:
                    raise
                time.sleep(0.03)
    finally:
        if temporary.exists():
            temporary.unlink()


def read_validated_json(path: Path, validator: Callable[[Any], bool], *, default: Any = None) -> Any:
    """Try a valid primary, then its last valid backup; preserve damaged files."""
    path = Path(path)
    if not path.exists() and not path.with_suffix(path.suffix + ".bak").exists():
        return default
    for candidate in (path, path.with_suffix(path.suffix + ".bak")):
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
            if validator(data):
                return data
        except (OSError, ValueError, TypeError):
            continue
    raise ValueError(f"No valid primary or backup snapshot: {path}")


def append_jsonl_once(path: Path, row: dict, *, key: str = "event_id") -> bool:
    """Commit a result once under the caller's exclusive device/process lock."""
    identity = row.get(key)
    if not isinstance(identity, str) or not identity:
        raise ValueError("A durable event requires a stable identity")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        with path.open("rb") as stream:
            for raw in stream:
                try:
                    existing = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    continue
                if isinstance(existing, dict) and existing.get(key) == identity:
                    if not raw.endswith(b"\n"):
                        with path.open("ab") as repair:
                            repair.write(b"\n")
                            repair.flush()
                            os.fsync(repair.fileno())
                    return False
    with path.open("ab") as stream:
        # Preserve an interrupted final row as a malformed complete line so the
        # next valid result cannot become glued to it and disappear from history.
        if stream.tell():
            with path.open("rb") as reader:
                reader.seek(-1, os.SEEK_END)
                if reader.read(1) != b"\n":
                    stream.write(b"\n")
        stream.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())
    return True
