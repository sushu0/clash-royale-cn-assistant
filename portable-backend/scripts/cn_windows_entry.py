"""Frozen Windows CN console and its explicitly dispatched child components."""

# Load only the selected component; child processes must not initialize a GUI.
# ruff: noqa: PLC0415

from __future__ import annotations

import json
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--component":
        component = sys.argv[2]
        sys.argv = [sys.argv[0], *sys.argv[3:]]
        if component == "run_cn_1v1.py":
            from scripts.run_cn_1v1 import main as entry
        elif component == "watch_cn_1v1.py":
            from scripts.watch_cn_1v1 import main as entry
        elif component == "stop_cn_1v1.py":
            from scripts.stop_cn_1v1 import main as entry
        else:
            raise SystemExit("Unknown bot component")
        entry()
        return
    if "--self-check" in sys.argv:
        from pyclashbot.bot.cn_1v1_loop import ChineseVision
        from pyclashbot.detection.cn_random_hand import _calibrated_samples
        from pyclashbot.detection.cn_threats import threat_template_health
        from pyclashbot.utils.runtime_config import environment_identity, load_runtime_config, resource_path

        ChineseVision()
        samples = _calibrated_samples()
        health = threat_template_health(include_567=True)
        if health["status"] != "healthy" or not resource_path("scripts/ocr_cn_footer.ps1").is_file():
            raise SystemExit("Packaged resources are incomplete")
        result = {
            "status": "ok",
            "hand_samples": len(samples),
            "templates": health,
            "environment": environment_identity(),
            "data_root": str(load_runtime_config().data_root),
        }
        # A windowed frozen exe has no console. A caller may request a result
        # file to verify the artifact without creating a UI or sending input.
        if "--self-check-output" in sys.argv:
            from pyclashbot.utils.persistence import atomic_write_json

            atomic_write_json(Path(sys.argv[sys.argv.index("--self-check-output") + 1]), result)
        elif sys.stdout is not None:
            print(json.dumps(result, ensure_ascii=False))
        return
    from scripts.cn_bot_control import main as entry

    entry()


if __name__ == "__main__":
    main()
