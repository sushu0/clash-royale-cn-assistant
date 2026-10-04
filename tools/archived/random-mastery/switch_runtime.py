"""Exercise the console's real handlers and preserve the current logged-in match."""
import importlib.util
import json
import subprocess
import time
from pathlib import Path

import psutil

ROOT = Path(r"D:\codex\CodexWork\clash")
path = ROOT / "py-clash-bot/scripts/cn_bot_control.py"
spec = importlib.util.spec_from_file_location("runtime_switch_console", path)
console = importlib.util.module_from_spec(spec)
spec.loader.exec_module(console)
report = {"started_at": time.strftime("%Y-%m-%d %H:%M:%S")}
old_state = json.loads(console.PID_FILE.read_text(encoding="utf-8"))
for key, script in (("watchdog_pid", "watch_cn_1v1.py"), ("runner_pid", "run_cn_1v1.py")):
    process = psutil.Process(old_state[key])
    if script not in " ".join(process.cmdline()):
        raise RuntimeError("PID is not owned by this task")
report["old_pids"] = old_state
report["before"] = console.read_random_status()

def game_pid():
    result = console._run([str(console.ADB), "-s", console.SERIAL, "shell", "pidof", console.PACKAGE])
    if result.returncode:
        raise RuntimeError("Logged-in game is not running")
    return result.stdout.strip()

report["game_pid_before"] = game_pid()
report["stop_result"] = console.ControlWindow._stop_worker()
report["stopped_verified"] = all(not psutil.pid_exists(old_state[key]) for key in ("watchdog_pid", "runner_pid"))
if not report["stopped_verified"]:
    raise RuntimeError("Old runner did not stop")
time.sleep(2.5)
report["frontend_stopped"] = json.loads((ROOT / "work/random-frontend-state.json").read_text(encoding="utf-8"))
checkpoint_path = ROOT / "work/random-mastery/checkpoint.json"
checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
rows = [json.loads(line) for line in console.RANDOM_TRACE.read_text(encoding="utf-8").splitlines() if line.strip()]
starts = [row for row in rows if row["event"] in ("match_requested", "battle_started")]
latest = starts[-1]
unfinished = latest["battle"] == checkpoint["completed"] + 1 and not any(
    row["event"] == "battle_finished" and row.get("finished_battle", row["battle"]) == latest["battle"]
    and row["time"] >= latest["time"] for row in rows)
if unfinished:
    proof = next((row for row in reversed(rows) if row["event"] == "deck_generated"
                  and row["battle"] == latest["battle"] and row["generation"] == latest["generation"]
                  and row["changed_slots"] > 0), None)
    if proof is None:
        raise RuntimeError("No verified random deck exists for the pending battle")
    checkpoint["generated"] = latest["generation"]
    checkpoint["pending_battle"] = True
    report["resumed_deck_proof"] = proof
else:
    checkpoint["pending_battle"] = False
checkpoint_path.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")
report["checkpoint"] = checkpoint
report["game_pid_after_stop"] = game_pid()
report["start_result"] = console.ControlWindow._start_worker()
report["game_pid_after_start"] = game_pid()
report["game_preserved"] = report["game_pid_before"] == report["game_pid_after_stop"] == report["game_pid_after_start"]
report["new_pids"] = json.loads(console.PID_FILE.read_text(encoding="utf-8"))
report["same_console_handlers_used"] = True
report["ended_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
target = ROOT / "outputs/RANDOM_CONTROL_RESTART_ACCEPTANCE.json"
target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"stopped_verified": report["stopped_verified"], "game_preserved": report["game_preserved"],
                  "frontend_stop_state": report["frontend_stopped"]["state"], "new_pids": report["new_pids"]}, ensure_ascii=False))
