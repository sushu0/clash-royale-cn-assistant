"""Observe a finite repaired bot run without injecting input."""

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import psutil

ROOT = Path(r"D:\codex\CodexWork\clash")
WORK = ROOT / "work/emulator-repair-20261003"
STATUS = ROOT / "outputs/random-mastery-live-status.json"
CHECKPOINT = ROOT / "work/random-mastery/checkpoint.json"
PIDS = ROOT / "work/bot-processes.json"
TRACE = ROOT / "outputs/cn-random-mastery.jsonl"
ADB = Path(r"D:\codex\CodexWork\tool_runtimes\android-platform-tools\platform-tools\adb.exe")


def read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def ours(pid, script):
    try:
        process = psutil.Process(int(pid))
        return process.is_running() and script in " ".join(process.cmdline())
    except (ValueError, TypeError, psutil.Error):
        return False


def main():
    baseline_path = Path(sys.argv[2]) if len(sys.argv) > 2 else WORK / "checkpoint.before.json"
    baseline = read(baseline_path)
    trace_start = int(sys.argv[1]) if len(sys.argv) > 1 else TRACE.stat().st_size
    deadline = time.monotonic() + 720
    observations = []
    signature = None
    started = time.time()
    while time.monotonic() < deadline:
        status, pids = read(STATUS), read(PIDS)
        watchdog = ours(pids.get("watchdog_pid"), "watch_cn_1v1.py")
        runner = ours(pids.get("runner_pid"), "run_cn_1v1.py")
        row = {"time": time.strftime("%Y-%m-%d %H:%M:%S"),
               "state": status.get("state"), "session": status.get("session"),
               "completed": status.get("completed"), "closed_loops": status.get("closed_loops"),
               "cards_confirmed": status.get("cards_confirmed"), "last_event": status.get("last_event"),
               "watchdog_alive": watchdog, "runner_alive": runner,
               "free_memory_mb": round(psutil.virtual_memory().available / 1024**2)}
        observations.append(row)
        current = (row["state"], row["completed"], row["closed_loops"], watchdog, runner)
        if current != signature:
            print(json.dumps(row, ensure_ascii=False), flush=True)
            signature = current
        if not watchdog and not runner:
            break
        time.sleep(10)
    events = []
    with TRACE.open("rb") as stream:
        stream.seek(trace_start)
        for line in stream:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("event") in {"started", "startup_ready", "resume_pending_mastery", "cycle_complete",
                                      "battle_started", "battle_finished", "returned_lobby", "recovery_attempt",
                                      "battle_frame_frozen", "paused", "finite_run_complete", "finite_complete", "stopped"}:
                events.append(event)
    status, pids, checkpoint = read(STATUS), read(PIDS), read(CHECKPOINT)
    finished = [event for event in events if event.get("event") == "battle_finished"]
    result_evidence = []
    for event in finished:
        evidence = event.get("evidence", {})
        path = Path(evidence.get("path", ""))
        result_evidence.append({**evidence, "hash_verified": path.is_file() and
                                hashlib.sha256(path.read_bytes()).hexdigest() == evidence.get("sha256")})
    checks = {
        "two_new_battles": checkpoint.get("completed", 0) - baseline.get("completed", 0) == 2,
        "expected_new_cycles_closed": checkpoint.get("closed_loops", 0) - baseline.get("closed_loops", 0)
        == 2 + int(bool(baseline.get("pending_mastery"))),
        "two_verified_results": len(finished) == 2 and all(item["hash_verified"] for item in result_evidence),
        "actual_plays_confirmed": len(finished) == 2 and all(event.get("cards_confirmed", 0) > 0 for event in finished),
        "finite_watchdog_exit": pids.get("exit_reason") == "finite_run_ended" and pids.get("max_battles") == 2,
        "no_pending_game_or_reward": not any(checkpoint.get(key) for key in ("pending_battle", "pending_mastery", "pending_claim_all")),
        "no_pause": not any(event.get("event") == "paused" for event in events),
        "processes_stopped": not ours(pids.get("watchdog_pid"), "watch_cn_1v1.py") and not ours(pids.get("runner_pid"), "run_cn_1v1.py"),
    }
    report = {"recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"), "timezone": "Asia/Shanghai",
              "elapsed_seconds": round(time.time() - started, 1), "checks": checks,
              "baseline": baseline, "checkpoint": checkpoint, "final_status": status, "processes": pids,
              "observations": observations, "events": events, "results": result_evidence}
    path = WORK / ("post-reboot-two-battles.json" if len(sys.argv) > 2 else "finite-two-battles.json")
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"path": str(path), "checks": checks}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
