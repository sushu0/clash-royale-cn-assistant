"""Read-only acceptance of the newly frozen log decoder; never starts a bot."""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(r"D:\codex\CodexWork\clash")
WORK = ROOT / "work" / "ui-polish-20261004"
DRAIN = ROOT / "work" / "random-mastery" / "DRAIN"
PID_FILE = ROOT / "work" / "bot-processes.json"
BACKEND = WORK / "backend-stage" / "ClashBackend.exe"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    before = {str(path): digest(path) for path in (DRAIN, PID_FILE)}
    requests = "\n".join(json.dumps({"id": command, "command": command}) for command in ("snapshot", "shutdown")) + "\n"
    with (WORK / "staged-backend-stderr.log").open("w", encoding="utf-8") as errors:
        result = subprocess.run(
            [str(BACKEND), "--data-root", str(ROOT), "--read-only"],
            input=requests, text=True, encoding="utf-8", stdout=subprocess.PIPE,
            stderr=errors, cwd=ROOT, timeout=90, creationflags=subprocess.CREATE_NO_WINDOW,
            check=True,
        )
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(responses) == 2 and all(row["ok"] for row in responses), responses
    snapshot = responses[0]["data"]
    events = snapshot["recent_events"]
    assert snapshot["state"] == "stopped"
    assert len(snapshot["reports"]) == 2
    assert not any("\ufffd" in line for line in events)
    assert not any("编码待确认" in line for line in events)
    assert any("随机卡组" in line for line in events)
    after = {str(path): digest(path) for path in (DRAIN, PID_FILE)}
    assert before == after
    record = {
        "status": "PASS", "verified_at": datetime.now().isoformat(),
        "backend_path": str(BACKEND), "backend_sha256": digest(BACKEND),
        "commands": ["snapshot", "shutdown"], "read_only": True,
        "state": snapshot["state"], "reports": len(snapshot["reports"]),
        "metrics": snapshot["scopes"]["random"]["total"],
        "recent_event_lines": len(events), "replacement_characters": 0,
        "unconfirmed_encoding_rows": 0, "drain_and_pid_file_hashes": after,
    }
    (WORK / "staged-backend-acceptance.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
