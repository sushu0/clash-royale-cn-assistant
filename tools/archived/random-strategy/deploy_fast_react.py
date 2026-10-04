"""Switch the verified task runner while preserving the logged-in Android process."""
import importlib.util
import json
import time
from pathlib import Path

import psutil
from pyclashbot.bot.random_deck_strategy import STRATEGY_VERSION

ROOT = Path(r"D:\codex\CodexWork\clash")
path = ROOT / "py-clash-bot/scripts/cn_bot_control.py"
spec = importlib.util.spec_from_file_location("fast_react_console", path)
console = importlib.util.module_from_spec(spec)
spec.loader.exec_module(console)
report = {"started_at": time.strftime("%Y-%m-%d %H:%M:%S"), "before": console.read_random_status()}
old = json.loads(console.PID_FILE.read_text(encoding="utf-8"))
for key, script in (("watchdog_pid", "watch_cn_1v1.py"), ("runner_pid", "run_cn_1v1.py")):
    assert script in " ".join(psutil.Process(old[key]).cmdline())

def game_pid():
    result = console._run([str(console.ADB), "-s", console.SERIAL, "shell", "pidof", console.PACKAGE])
    assert result.returncode==0 and result.stdout.strip()
    return result.stdout.strip()

report["game_pid_before"] = game_pid()
report["stop_result"] = console.ControlWindow._stop_worker()
assert not any(psutil.pid_exists(old[key]) for key in ("watchdog_pid", "runner_pid"))
checkpoint = json.loads((ROOT / "work/random-mastery/checkpoint.json").read_text(encoding="utf-8"))
report["checkpoint"] = checkpoint
report["start_result"] = console.ControlWindow._start_worker()
for _ in range(20):
    live = console.read_random_status()
    if live.get("pid") != report["before"]["pid"] and live.get("strategy_version")==STRATEGY_VERSION:
        break
    time.sleep(.4)
else:
    raise RuntimeError("New strategy did not publish its status")
report["after"] = live
report["game_pid_after"] = game_pid()
assert report["game_pid_after"]==report["game_pid_before"]
assert live["completed"]>=report["before"]["completed"]
assert live["rewards_received"]>=report["before"]["rewards_received"]
assert live["coins_received"]>=report["before"]["coins_received"]
report["result"]="PASS"
target = ROOT / "outputs/RANDOM_FAST_REACT_DEPLOYMENT.json"
target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"result": "PASS", "game_pid_preserved": report["game_pid_after"],
                  "resumed_pending_battle": checkpoint["pending_battle"], "pid": live["pid"],
                  "file": str(target)}, ensure_ascii=False))
