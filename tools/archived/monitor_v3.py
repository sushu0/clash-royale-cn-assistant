"""Stop only this existing CN bot after a bounded real battle validation."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("session")
parser.add_argument("--battles", type=int, default=10)
args = parser.parse_args()
trace = ROOT / "outputs/cn-hog-strategy.jsonl"
deadline = time.monotonic() + 50 * 60
position = 0
ends = []
seen = set()
while time.monotonic() < deadline:
    with trace.open("r", encoding="utf-8") as stream:
        stream.seek(position)
        while True:
            start = stream.tell()
            line = stream.readline()
            if not line:
                position = start
                break
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                position = start
                break
            if event.get("session") != args.session:
                continue
            if event.get("event") == "battle_end" and event.get("battle") not in seen:
                seen.add(event["battle"])
                if event.get("attempts", 0) > 0:
                    ends.append(event)
                    print(json.dumps({k:event[k] for k in ("battle","result","confirmed","attempts","time")},ensure_ascii=False),flush=True)
    if len(ends) >= args.battles:
        break
    time.sleep(2)
completed_target = len(ends) >= args.battles
print(f"Stopping validation bot: completed={len(ends)}, target_reached={completed_target}", flush=True)
result = subprocess.run([sys.executable, str(ROOT / "py-clash-bot/scripts/stop_cn_1v1.py"),
                         "--pid-file", str(ROOT / "work/bot-processes.json")],cwd=ROOT / "py-clash-bot")
(ROOT / "work" / f"{args.session}-monitor.json").write_text(
    json.dumps({"session":args.session,"target":args.battles,"completed":len(ends),
                "target_reached":completed_target,"stop_exit_code":result.returncode,"ends":ends},
               ensure_ascii=False,indent=2),encoding="utf-8")
sys.exit(result.returncode)
