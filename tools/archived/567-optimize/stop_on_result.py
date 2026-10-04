"""Stop this task's bot at a newly observed result, not an already reopened game."""
import json
from pathlib import Path
import subprocess
import sys
import time

root = Path(__file__).resolve().parents[2]
status = json.loads((root / "outputs/567-live-status.json").read_text(encoding="utf-8"))
session = status["session"]
target = status["completed"]+1
deadline = time.monotonic()+360
while time.monotonic() < deadline:
    rows = []
    for line in (root / "outputs/cn-567-strategy.jsonl").read_text(encoding="utf-8").splitlines()[-150:]:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("session") == session:
            rows.append(row)
    starts = [r["battle"] for r in rows if r["event"] == "battle_start"]
    target = max(target, max(starts, default=target))
    end = next((r for r in reversed(rows) if r["event"] == "battle_end" and r["battle"] == target), None)
    if end:
        subprocess.run([sys.executable, str(root / "py-clash-bot/scripts/stop_cn_1v1.py"),
                        "--pid-file", str(root / "work/bot-processes.json")],
                       cwd=root / "py-clash-bot", timeout=25, check=True)
        (root / "work/567-optimize/baseline-stop.json").write_text(json.dumps(end, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Stopped after", session, target, end["result"], flush=True)
        break
    time.sleep(.25)
else:
    raise SystemExit("No completed result within bounded handoff window; bot not stopped")
