"""Portable Windows shell with the existing safe child-component dispatcher."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_ID = "Codex.ClashAssistant.Desktop.2026"


def configure_desktop_runtime() -> None:
    resource_root = (
        Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    )
    config_path = resource_root / "desktop-runtime.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file() else {}
    data_root = Path(os.environ.get("PYCLASHBOT_DATA_ROOT", config.get("data_root", resource_root.parent / "data"))).resolve()
    from pyclashbot.utils.runtime_config import distribution_data_root  # noqa: PLC0415
    if data_root != distribution_data_root():
        raise ValueError("分享版数据必须保存到当前安装目录的 data 文件夹")
    os.environ.setdefault("PYCLASHBOT_DATA_ROOT", str(data_root))
    runtime_dir = data_root / "work" / "desktop-app-runtime"
    temp_dir = runtime_dir / "temp"
    cache_dir = runtime_dir / "cache"
    temp_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = str(temp_dir)
    os.environ["TMP"] = str(temp_dir)
    os.environ.setdefault("PYTHONPYCACHEPREFIX", str(cache_dir / "pycache"))
    from pyclashbot.utils.runtime_config import install_unicode_image_io  # noqa: PLC0415

    install_unicode_image_io()
    if not getattr(sys, "frozen", False):
        sys.path.insert(0, str(resource_root))


def main():
    configure_desktop_runtime()
    # Components share the established dispatch path; they never create the GUI.
    from scripts.cn_windows_entry import main as entry  # noqa: PLC0415

    entry()


if __name__ == "__main__":
    main()
