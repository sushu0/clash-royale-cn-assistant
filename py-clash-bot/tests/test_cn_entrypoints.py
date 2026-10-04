"""Direct source entrypoints work without making any emulator or GUI input."""

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("name", ["start_cn_bot.py", "run_cn_1v1.py", "watch_cn_1v1.py", "stop_cn_1v1.py"])
def test_direct_script_help_from_another_directory(name, tmp_path):
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(repo / "scripts" / name), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout
