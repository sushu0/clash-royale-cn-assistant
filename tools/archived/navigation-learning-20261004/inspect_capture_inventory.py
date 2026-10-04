"""Read-only inventory of navigation captures and implementation evidence.

This records saved files only. It does not prove page recognition, transitions,
complete button coverage, or future daily-popup handling, and sends no game input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from datetime import datetime
from pathlib import Path


STORAGE_ROOT = Path(r"D:\codex")
DEFAULT_TASK = Path(__file__).resolve().parent
DEFAULT_WORKSPACE = DEFAULT_TASK.parents[1]
SOURCE_RELATIVES = (
    "pyclashbot/bot/coords.py",
    "pyclashbot/bot/cn_1v1_loop.py",
    "pyclashbot/bot/cn_random_mastery_loop.py",
    "pyclashbot/detection/cn_daily_gift.py",
    "pyclashbot/detection/cn_page_navigation.py",
    "scripts/build_cn_desktop.py",
    "scripts/cn_windows_entry.py",
    "scripts/cn_desktop_entry.py",
    "scripts/cn_bot_control.py",
    "scripts/watch_cn_1v1.py",
    "scripts/install_cn_desktop_shortcut.ps1",
)


def under_storage(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(STORAGE_ROOT.resolve()):
        raise ValueError(f"Path must stay under {STORAGE_ROOT}: {resolved}")
    return resolved


def metadata(path: Path) -> dict:
    row: dict = {"path": str(path.resolve()), "exists": path.is_file()}
    if not row["exists"]:
        return row
    stat = path.stat()
    row.update(
        bytes=stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    return row


def png_metadata(path: Path) -> dict:
    row = metadata(path)
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        row["error"] = "Missing PNG signature or IHDR header"
        return row
    width, height = struct.unpack(">II", header[16:24])
    row.update(width=width, height=height, fixed_resolution_matches=(width, height) == (419, 633))
    return row


def inventory(workspace: Path, task: Path) -> dict:
    pages = task / "pages"
    backup = task / "backup"
    captures = [png_metadata(path) for path in sorted(pages.glob("*.png"))] if pages.is_dir() else []
    backup_files = [metadata(path) for path in sorted(backup.rglob("*")) if path.is_file()] if backup.is_dir() else []
    source_files = [metadata(workspace / "py-clash-bot" / relative) for relative in SOURCE_RELATIVES]
    return {
        "schema": "navigation-capture-inventory-v1",
        "generated_at": datetime.now().astimezone().isoformat(),
        "workspace": str(workspace),
        "task_directory": str(task),
        "game_input_sent": False,
        "captures_directory_exists": pages.is_dir(),
        "capture_count": len(captures),
        "captures": captures,
        "backup_files": backup_files,
        "source_files": source_files,
        "coverage": {
            "status": "unverified",
            "buttons_total": None,
            "buttons_visited": None,
            "page_recognition_tested": False,
            "return_to_classic_1v1_tested": False,
            "frozen_deployment_tested": False,
            "continuous_battle_resumed": False,
            "limitation": "Captured files are evidence of saved images only; transitions and full UI coverage need a separately observed record.",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--task-directory", type=Path, default=DEFAULT_TASK)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    workspace = under_storage(args.workspace)
    task = under_storage(args.task_directory)
    result = inventory(workspace, task)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = under_storage(args.output)
        if not output.is_relative_to(task):
            raise ValueError("Inventory output must stay inside its task directory")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        print(json.dumps({"output": str(output), "capture_count": result["capture_count"], "coverage": "unverified"}))
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
