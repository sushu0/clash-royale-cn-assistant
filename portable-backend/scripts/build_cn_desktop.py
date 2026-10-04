"""Build the portable Chinese desktop application without touching old builds.

Use the project's verified Python 3.12 build environment, for example:
python scripts/build_cn_desktop.py build_exe
PYCLASHBOT_DESKTOP_OUTPUT and PYCLASHBOT_DESKTOP_WORK may override D-drive paths.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from cx_Freeze import Executable, setup

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT.parent
OUTPUT = Path(os.environ.get("PYCLASHBOT_DESKTOP_OUTPUT", DATA_ROOT / "outputs" / "desktop-app-20261004")).resolve()
WORK = Path(os.environ.get("PYCLASHBOT_DESKTOP_WORK", DATA_ROOT / "work" / "desktop-app-20261004")).resolve()
VERSION = "2026.10.4"

for target in (OUTPUT, WORK):
    if not target.is_relative_to(Path(r"D:\codex")):
        raise ValueError("Desktop build output and work must stay under D:\\codex")
WORK.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
runtime_config = WORK / "desktop-runtime.json"
runtime_config.write_text(
    json.dumps({"data_root": str(DATA_ROOT), "app_id": "Codex.ClashAssistant.Desktop.2026"}, indent=2) + "\n",
    encoding="utf-8",
)
# Keep desktop metadata independent of the source pyproject's placeholder
# version; setuptools reads configuration relative to its working directory.
os.chdir(WORK)

setup(
    name="ClashAssistant",
    version=VERSION,
    description="Clash Royale Desktop Assistant",
    executables=[
        Executable(
            script=ROOT / "scripts" / "cn_desktop_entry.py",
            base="Win32GUI",
            target_name="ClashAssistant.exe",
            icon=ROOT / "assets" / "clash-desktop.ico",
            copyright="Clash Assistant desktop edition",
            uac_admin=False,
        )
    ],
    options={
        "build": {"build_base": str(WORK / "intermediates")},
        "build_exe": {
            "build_exe": str(OUTPUT),
            "excludes": [
                "test",
                "setuptools",
                "scripts.setup_msi",
                "scripts.setup_macos",
                "scripts.build_cn_desktop",
                "scripts.create_cn_desktop_icon",
            ],
            "packages": ["pyclashbot", "scripts", "ttkbootstrap", "tkinter"],
            "include_files": [
                (ROOT / "assets", "assets"),
                (runtime_config, "desktop-runtime.json"),
                (ROOT / "pyclashbot" / "detection" / "reference_images", "pyclashbot/detection/reference_images"),
                (ROOT / "pyclashbot" / "__version__", "pyclashbot/__version__"),
                (ROOT / "scripts", "scripts"),
                (ROOT / "pyclashbot", "source/pyclashbot"),
            ],
            "include_msvcr": True,
        },
    },
)
