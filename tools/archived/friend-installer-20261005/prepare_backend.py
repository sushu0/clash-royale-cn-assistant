"""Prepare an isolated distributable from the verified running frozen backend."""

from __future__ import annotations

import hashlib
import json
import py_compile
import shutil
from pathlib import Path
from zipfile import ZipFile

TASK = Path(__file__).resolve().parent
BACKEND = TASK / "stage" / "backend"
SOURCE = BACKEND / "source" / "pyclashbot"

RUNTIME_SOURCE = '''"""Share edition: every writable file belongs to this installation's data folder."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2]
RESOURCE_ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else SOURCE_ROOT.parent

def distribution_data_root() -> Path:
    return (RESOURCE_ROOT.parent / "data").resolve()

def data_path_allowed(path) -> bool:
    return Path(path).resolve().is_relative_to(distribution_data_root())

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
    import re
    if not re.fullmatch(r"127\\.0\\.0\\.1:[0-9]{1,5}", serial) or not 1 <= int(serial.rsplit(":", 1)[1]) <= 65535:
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
'''


def replace_exact(path: Path, before: str, after: str) -> None:
    text = path.read_text(encoding="utf-8")
    if before not in text:
        raise ValueError(f"Expected source anchor is missing: {path.name}")
    path.write_text(text.replace(before, after), encoding="utf-8", newline="\n")


def update_frozen_entry() -> None:
    """cx_Freeze starts the entry in library.zip, separately from scripts/*.pyc."""
    library = BACKEND / "lib" / "library.zip"
    entry_pyc = TASK / "backend-entry.pyc"
    py_compile.compile(str(BACKEND / "scripts" / "cn_wpf_backend.py"), cfile=str(entry_pyc),
                       dfile="share-source/scripts/cn_wpf_backend.py", doraise=True)
    backup = TASK / "original-backend-library.zip"
    if not backup.exists():
        shutil.copy2(library, backup)
    temporary = TASK / "updated-backend-library.zip"
    with ZipFile(library) as src, ZipFile(temporary, "w") as dst:
        expected = "__main__clashbackend.pyc"
        if expected not in src.namelist():
            raise ValueError("Frozen entry is missing")
        for info in src.infolist():
            dst.writestr(info, entry_pyc.read_bytes() if info.filename == expected else src.read(info.filename))
    shutil.copy2(temporary, library)


def main() -> None:
    if not BACKEND.is_relative_to(Path(r"D:\codex")):
        raise ValueError("Local build must remain under D:\\codex")
    original = TASK.parents[1] / "outputs" / "wpf-desktop-stop-repair-20261004" / "backend"
    shutil.copytree(original, BACKEND, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    runtime = SOURCE / "utils" / "runtime_config.py"
    runtime.write_text(RUNTIME_SOURCE, encoding="utf-8", newline="\n")
    entry = BACKEND / "scripts" / "cn_desktop_entry.py"
    replace_exact(entry, '    if not data_root.is_relative_to(STORAGE_ROOT):\n        raise ValueError("Desktop data must stay under D:\\\\codex")',
                  '    from pyclashbot.utils.runtime_config import distribution_data_root\n    if data_root != distribution_data_root():\n        raise ValueError("分享版数据必须保存到当前安装目录的 data 文件夹")')
    replace_exact(entry, 'config.get("data_root", resource_root.parent)',
                  'config.get("data_root", resource_root.parent / "data")')
    replace_exact(entry, 'STORAGE_ROOT = Path(r"D:\\codex")\n', '')
    bridge = BACKEND / "scripts" / "cn_wpf_backend.py"
    replace_exact(bridge, '        if not root.is_relative_to(Path(r"D:\\codex")):\n            raise SystemExit("--data-root must stay under D:\\\\codex")',
                  '        from pyclashbot.utils.runtime_config import distribution_data_root\n        if root != distribution_data_root():\n            raise SystemExit("分享版数据必须保存到当前安装目录的 data 文件夹")')
    replace_exact(bridge, '--data-root requires a D:\\\\codex directory', '--data-root requires the installation data directory')
    replace_exact(bridge, '    configure_desktop_runtime()\n',
                  '    configure_desktop_runtime()\n    if "--self-check" in sys.argv:\n        from scripts.cn_windows_entry import main as self_check_entry\n        self_check_entry()\n        return\n')
    report = SOURCE / "utils" / "cn_error_report.py"
    replace_exact(report, 'from pyclashbot.utils.persistence import atomic_write_bytes, atomic_write_json',
                  'from pyclashbot.utils.runtime_config import data_path_allowed\nfrom pyclashbot.utils.persistence import atomic_write_bytes, atomic_write_json')
    replace_exact(report, 'not root.is_relative_to(Path(r"D:\\codex"))', 'not data_path_allowed(root)')
    replace_exact(report, 'not self.output_dir.is_relative_to(Path(r"D:\\codex"))', 'not data_path_allowed(self.output_dir)')
    replace_exact(report, '错误报告必须保存到 D:\\\\codex', '错误报告必须保存到当前安装目录的 data 文件夹')
    controller = BACKEND / "scripts" / "cn_bot_control.py"
    replace_exact(controller, 'return value if value in ("random", "567", "hog") else "567"',
                  'return value if value in ("random", "567", "hog") else "random"')
    replace_exact(controller, '    except OSError:\n        return "567"', '    except OSError:\n        return "random"')
    replace_exact(BACKEND / "scripts" / "watch_cn_1v1.py", 'if selection.is_file() else "567"', 'if selection.is_file() else "random"')
    replace_exact(BACKEND / "scripts" / "run_cn_1v1.py", 'choices=("567", "hog", "random"), default="567"',
                  'choices=("567", "hog", "random"), default="random"')
    # JSON uses a portable relative root, resolved by the entry before use.
    (BACKEND / "desktop-runtime.json").write_text('{"app_id":"ClashAssistant.Share.2026"}\n', encoding="utf-8")
    compiled = []
    for path in sorted(SOURCE.rglob("*.py")):
        relative = path.relative_to(SOURCE)
        target = BACKEND / "lib" / "pyclashbot" / relative.with_suffix(".pyc")
        target.parent.mkdir(parents=True, exist_ok=True)
        py_compile.compile(str(path), cfile=str(target), dfile=f"share-source/pyclashbot/{relative.as_posix()}", doraise=True)
        compiled.append(relative.as_posix())
    for path in sorted((BACKEND / "scripts").glob("*.py")):
        target = BACKEND / "lib" / "scripts" / path.with_suffix(".pyc").name
        target.parent.mkdir(parents=True, exist_ok=True)
        py_compile.compile(str(path), cfile=str(target), dfile=f"share-source/scripts/{path.name}", doraise=True)
        compiled.append(f"scripts/{path.name}")
    update_frozen_entry()
    tools = TASK / "stage" / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    adb_source = Path(r"D:\codex\CodexWork\tool_runtimes\android-platform-tools\platform-tools")
    for name in ("adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll", "libwinpthread-1.dll", "NOTICE.txt", "source.properties"):
        shutil.copy2(adb_source / name, tools / name)
    result = {
        "backend_origin": "outputs/wpf-desktop-stop-repair-20261004/backend",
        "edition": "Windows x64 friend distribution",
        "compiled_source_files": len(compiled),
        "modified_source_files": ["utils/runtime_config.py", "utils/cn_error_report.py", "scripts/cn_desktop_entry.py", "scripts/cn_wpf_backend.py", "scripts/cn_bot_control.py", "scripts/watch_cn_1v1.py", "scripts/run_cn_1v1.py"],
        "battle_core_sha256": hashlib.sha256((SOURCE / "bot" / "cn_random_mastery_loop.py").read_bytes()).hexdigest(),
        "personal_data_included": False,
    }
    (TASK / "backend-preparation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
