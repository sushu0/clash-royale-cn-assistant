"""Share edition: every writable file belongs to this installation's data folder."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2]
RESOURCE_ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else SOURCE_ROOT

def distribution_data_root() -> Path:
    return (RESOURCE_ROOT.parent / "data").resolve()

def data_path_allowed(path) -> bool:
    return Path(path).resolve().is_relative_to(distribution_data_root())

def install_unicode_image_io() -> None:
    """Use Python file I/O for Windows Unicode image paths, preserving BGR decoding."""
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    if getattr(cv2, "_pyclashbot_unicode_io_installed", False):
        return
    original_imread = cv2.imread
    original_imwrite = cv2.imwrite

    def unicode_imread(filename, flags=cv2.IMREAD_COLOR):
        file_path = os.fspath(filename)
        if not isinstance(file_path, str) or file_path.isascii():
            return original_imread(filename, flags)
        try:
            encoded = np.frombuffer(Path(file_path).read_bytes(), dtype=np.uint8)
            if encoded.size == 0:
                return None
            return cv2.imdecode(encoded, flags)
        except (OSError, ValueError, cv2.error):
            return None

    def unicode_imwrite(filename, img, params=None):
        file_path = os.fspath(filename)
        if not isinstance(file_path, str) or file_path.isascii():
            return original_imwrite(filename, img) if params is None else original_imwrite(filename, img, params)
        path = Path(file_path)
        ok, encoded = cv2.imencode(path.suffix, img, [] if params is None else params)
        if not ok:
            return False
        try:
            path.write_bytes(encoded.tobytes())
        except (OSError, ValueError):
            return False
        return True

    cv2.imread = unicode_imread
    cv2.imwrite = unicode_imwrite
    cv2._pyclashbot_unicode_io_installed = True

@dataclass(frozen=True)
class RuntimeConfig:
    data_root: Path
    python: Path
    adb: Path
    memuc: Path
    serial: str = "127.0.0.1:21503"
    vm_index: int = 0

def load_runtime_config() -> RuntimeConfig:
    default = distribution_data_root()
    root = Path(os.environ.get("PYCLASHBOT_DATA_ROOT", str(default))).expanduser().resolve()
    if root != default:
        raise ValueError("分享版数据必须保存到当前安装目录的 data 文件夹")
    path = root / "work" / "runtime-config.json"
    values = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if not isinstance(values, dict):
        raise ValueError("Runtime configuration must be an object")
    serial = str(values.get("serial", "127.0.0.1:21503"))
    if not re.fullmatch(r"127\.0\.0\.1:[0-9]{1,5}", serial) or not 1 <= int(serial.rsplit(":", 1)[1]) <= 65535:
        raise ValueError("只支持本机模拟器的 127.0.0.1:端口")
    if values.get("vm_index", 0) != 0:
        raise ValueError("当前版本只支持 MEmu 的 0 号实例")
    return RuntimeConfig(
        root,
        Path(sys.executable),
        Path(os.environ.get("PYCLASHBOT_ADB", values.get("adb", RESOURCE_ROOT.parent / "tools" / "adb.exe"))),
        Path(os.environ.get("PYCLASHBOT_MEMUC", values.get("memuc", RESOURCE_ROOT.parent / "tools" / "memuc.exe"))),
        serial, 0,
    )

def component_command(python: Path, script: Path, *arguments: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [str(python), "--component", script.name, *arguments]
    return [str(python), str(script), *arguments]

def resource_path(relative: str) -> Path:
    return RESOURCE_ROOT / relative

def source_path(relative: str) -> Path:
    return RESOURCE_ROOT / "source" / relative if getattr(sys, "frozen", False) else SOURCE_ROOT / relative

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
