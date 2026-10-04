"""Stop the recorded project runner only after a completed game cycle boundary."""
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(r"D:\codex\CodexWork\clash")
REPO = ROOT / "py-clash-bot"
WORK = ROOT / "work"
CHECKPOINT = WORK / "random-mastery" / "checkpoint.json"
AUDIT = WORK / "repair-20261003"
python = WORK / "venv" / "Scripts" / "python.exe"
before = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
deadline = time.monotonic() + 420
while time.monotonic() < deadline:
    try:
        checkpoint = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
        if (checkpoint.get("completed", 0) >= before.get("completed", 0)
                and not checkpoint.get("pending_battle") and not checkpoint.get("pending_mastery")
                and not checkpoint.get("pending_claim_all")):
            (AUDIT / "checkpoint-before-switch.json").write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")
            result = subprocess.run([str(python), "scripts/stop_cn_1v1.py", "--pid-file", str(WORK / "bot-processes.json")],
                                    cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=30,
                                    check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            record = {"boundary": checkpoint, "stop_exit": result.returncode,
                      "stdout": result.stdout, "stderr": result.stderr,
                      "at": time.strftime("%Y-%m-%d %H:%M:%S")}
            (AUDIT / "live-switch.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(record, ensure_ascii=False))
            raise SystemExit(result.returncode)
    except (OSError, ValueError):
        pass
    time.sleep(.15)
raise SystemExit("No completed cycle boundary appeared before the switch deadline")
