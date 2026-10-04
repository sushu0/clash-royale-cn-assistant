"""Stop only the verified old bot after this cycle completes, for GUI update."""
import json
import subprocess
import time
from pathlib import Path

import psutil

root = Path(r"D:\codex\CodexWork\clash")
work = root / "work" / "error-history-20261004"
old_exe = root / "outputs" / "desktop-app-20261004" / "ClashAssistant.exe"
pid_path = root / "work" / "bot-processes.json"
trace = root / "outputs" / "cn-random-mastery.jsonl"
state = json.loads(pid_path.read_text(encoding="utf-8"))
session = json.loads((root / "outputs" / "random-mastery-live-status.json").read_text(encoding="utf-8"))["session"]
offset = trace.stat().st_size
deadline = time.monotonic() + 240
partial = b""
while time.monotonic() < deadline:
    for component in ("watchdog", "runner"):
        process = psutil.Process(state[f"{component}_pid"])
        if not process.is_running() or abs(process.create_time() - state[f"{component}_created_at"]) >= .01:
            raise RuntimeError("Bot identity changed before the update boundary")
        if Path(process.exe()).resolve() != old_exe.resolve():
            raise RuntimeError("Unexpected bot executable")
    with trace.open("rb") as stream:
        stream.seek(offset)
        chunk = stream.read(128 * 1024)
        offset = stream.tell()
    lines = (partial + chunk).split(b"\n")
    partial = lines.pop()
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("event") == "cycle_complete" and event.get("session") == session:
            result = subprocess.run(
                [str(old_exe), "--component", "stop_cn_1v1.py", "--pid-file", str(pid_path)],
                cwd=old_exe.parent, capture_output=True, timeout=30, check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            record = {"cycle_boundary": event, "stop_exit_code": result.returncode, "old_pid_state": state}
            (work / "update-boundary.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"stopped_at": event.get("time"), "completed_battle": event.get("battle"), "exit_code": result.returncode}), flush=True)
            raise SystemExit(result.returncode)
    time.sleep(.4)
raise SystemExit("No completed cycle was observed within 4 minutes; nothing was stopped")
