"""One portable configuration for source and frozen Chinese-client entrypoints."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2]
RESOURCE_ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else SOURCE_ROOT


@dataclass(frozen=True)
class RuntimeConfig:
    data_root: Path
    python: Path
    adb: Path
    memuc: Path
    serial: str = "127.0.0.1:21503"
    vm_index: int = 0


def load_runtime_config() -> RuntimeConfig:
    explicit = os.environ.get("PYCLASHBOT_DATA_ROOT")
    default = SOURCE_ROOT.parent
    if getattr(sys, "frozen", False) or (os.name == "nt" and not default.is_relative_to(Path(r"D:\codex"))):
        default = Path(r"D:\codex\apps\pyclashbot")
    root = Path(explicit).expanduser().resolve() if explicit else default
    if os.name == "nt" and not root.is_relative_to(Path(r"D:\codex")):
        raise ValueError("PYCLASHBOT_DATA_ROOT must stay under D:\\codex")
    path = Path(os.environ.get("PYCLASHBOT_CONFIG", root / "work" / "runtime-config.json"))
    values = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if not isinstance(values, dict):
        raise ValueError("Runtime configuration must be an object")
    python = (
        Path(sys.executable)
        if getattr(sys, "frozen", False)
        else Path(values.get("python", root / "work" / "venv" / "Scripts" / "python.exe"))
    )
    return RuntimeConfig(
        root,
        python,
        Path(
            os.environ.get(
                "PYCLASHBOT_ADB",
                values.get("adb", r"D:\codex\CodexWork\tool_runtimes\android-platform-tools\platform-tools\adb.exe"),
            )
        ),
        Path(
            os.environ.get(
                "PYCLASHBOT_MEMUC",
                values.get("memuc", root / "work" / "downloads" / "Microvirt" / "MEmu" / "memuc.exe"),
            )
        ),
        str(values.get("serial", "127.0.0.1:21503")),
        int(values.get("vm_index", 0)),
    )


def component_command(python: Path, script: Path, *arguments: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [str(python), "--component", script.name, *arguments]
    return [str(python), str(script), *arguments]


def resource_path(relative: str) -> Path:
    """Resources are copied alongside a frozen executable; source uses the repo."""
    return RESOURCE_ROOT / relative


def source_path(relative: str) -> Path:
    if getattr(sys, "frozen", False):
        return RESOURCE_ROOT / "source" / relative
    return SOURCE_ROOT / relative


def environment_identity() -> dict:
    versions = {}
    for name in ("opencv-python", "numpy", "psutil", "pillow", "ttkbootstrap", "pymemuc"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "unavailable"
    identity = {"python": sys.version.split()[0], "dependencies": versions}
    identity["sha256"] = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return identity
