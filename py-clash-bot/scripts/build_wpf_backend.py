"""Freeze the existing Python controls into a JSONL console backend for WPF."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from cx_Freeze import Executable, setup

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT.parent
OUTPUT = Path(
    os.environ.get("PYCLASHBOT_WPF_BACKEND_OUTPUT", DATA_ROOT / "outputs" / "wpf-desktop-20261004" / "backend")
).resolve()
WORK = Path(
    os.environ.get("PYCLASHBOT_WPF_BACKEND_WORK", DATA_ROOT / "work" / "wpf-rewrite-20261004" / "backend-build")
).resolve()
for target in (OUTPUT, WORK):
    if not target.is_relative_to(Path(r"D:\codex")):
        raise ValueError("WPF backend output and work must stay under D:\\codex")
WORK.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
runtime_config = WORK / "desktop-runtime.json"
runtime_config.write_text(
    json.dumps({"data_root": str(DATA_ROOT), "app_id": "Codex.ClashAssistant.Wpf.2026"}, indent=2) + "\n",
    encoding="utf-8",
)
os.chdir(WORK)

setup(
    name="ClashBackend",
    version="2026.10.4",
    description="Clash Royale WPF JSONL backend",
    executables=[
        Executable(
            script=ROOT / "scripts" / "cn_wpf_backend.py",
            base="Console",
            target_name="ClashBackend.exe",
            icon=ROOT / "assets" / "clash-desktop.ico",
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
                "scripts.build_wpf_backend",
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
