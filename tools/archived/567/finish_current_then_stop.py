"""One-time version handoff after the current result is recorded."""
import json
from pathlib import Path
import subprocess
import sys
import time

root = Path(__file__).resolve().parents[2]
deadline = time.monotonic() + 180
while time.monotonic() < deadline:
    lines = (root / "outputs/cn-567-strategy.jsonl").read_text(encoding="utf-8").splitlines()
    rows = []
    for line in lines[-120:]:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    result = next((r for r in rows if r.get("session") == "20260928-122011"
                   and r.get("event") == "battle_end" and r.get("battle") == 1), None)
    if result:
        print("Observed actual result:", result["result"], flush=True)
        subprocess.run([sys.executable, str(root / "py-clash-bot/scripts/stop_cn_1v1.py"),
                        "--pid-file", str(root / "work/bot-processes.json")],
                       cwd=root / "py-clash-bot", timeout=25, check=True)
        break
    time.sleep(1)
else:
    raise SystemExit("Current battle did not finish within bounded handoff window; no stop sent")
