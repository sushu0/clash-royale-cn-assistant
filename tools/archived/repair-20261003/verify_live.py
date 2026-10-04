"""Read the current runner, preserve matching result evidence, and save acceptance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

import psutil


ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent
OUTPUT = ROOT / "outputs" / "BOT_RECOVERY_ACCEPTANCE_20261003.json"
SOURCE_FILES = (
    "pyclashbot/bot/cn_random_mastery_loop.py",
    "pyclashbot/bot/coords.py",
    "pyclashbot/bot/cn_1v1_loop.py",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def process_record(pid: int, script: str) -> dict:
    try:
        process = psutil.Process(pid)
        command = process.cmdline()
        return {"pid": pid, "alive": process.is_running(),
                "verified_script": any(script in arg for arg in command),
                "command": command, "children": [p.pid for p in process.children(recursive=True)]}
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return {"pid": pid, "alive": False, "verified_script": False}


def main() -> None:
    status = json.loads((ROOT / "outputs/random-mastery-live-status.json").read_text(encoding="utf-8"))
    pids = json.loads((ROOT / "work/bot-processes.json").read_text(encoding="utf-8"))
    session = status["session"]
    events = []
    with (ROOT / "outputs/cn-random-mastery.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("session") == session:
                events.append(event)
    finished = [e for e in events if e["event"] == "battle_finished"]
    cycles = [e for e in events if e["event"] == "cycle_complete" and not e.get("resumed")]
    starts = [e for e in events if e["event"] == "battle_started"]
    opened = next(e for e in events if e["event"] == "started")
    watchdog = process_record(pids["watchdog_pid"], "watch_cn_1v1.py")
    runner = process_record(pids["runner_pid"], "run_cn_1v1.py")
    evidence = []
    for event in finished:
        item = event["evidence"]
        source = Path(item["path"])
        saved = WORK / f"verified-result-{session}-{event['finished_battle']}.png"
        if not saved.exists() and source.exists() and digest(source) == item["sha256"]:
            saved.write_bytes(source.read_bytes())
        evidence.append({"battle": event["finished_battle"], "outcome": event["outcome"],
                         "card_attempts": event["card_attempts"], "cards_confirmed": event["cards_confirmed"],
                         "time": event["time"], "saved_path": str(saved), "sha256": item["sha256"],
                         "hash_verified": saved.exists() and digest(saved) == item["sha256"]})
    checks = {
        "watchdog_alive": watchdog["alive"] and watchdog["verified_script"],
        "runner_alive": runner["alive"] and runner["verified_script"],
        "actual_runner_matches_status": status["pid"] in [runner["pid"], *runner.get("children", [])],
        "unlimited_requested": opened.get("max_battles") == 0,
        "new_policy_loaded": opened.get("policy") == "random-mastery-fast-react-v18-recovery-20261003",
        "original_mastery_checkpoint_closed": any(e["event"] == "cycle_complete" and e.get("resumed") and e.get("completed_battle") == 752 for e in events),
        "two_new_battles_finished": len(finished) >= 2,
        "two_new_cycles_closed": len(cycles) >= 2,
        "completed_matches_have_verified_plays": len(finished) >= 2 and all(e["cards_confirmed"] > 0 for e in finished),
        "next_battle_started": bool(finished and starts and starts[-1]["battle"] > finished[-1]["finished_battle"]),
        "next_battle_has_verified_plays": status["state"] == "battle" and status["cards_confirmed"] > 0,
        "result_images_preserved": len(evidence) >= 2 and all(e["hash_verified"] for e in evidence),
        "not_paused": status["state"] not in ("paused", "stopped"),
        "no_session_pause": not any(e["event"] == "paused" for e in events),
    }
    report = {
        "verified_at": time.strftime("%Y-%m-%d %H:%M:%S"), "timezone": "Asia/Shanghai",
        "result": "PASS" if all(checks.values()) else "MONITORING", "session": session,
        "checks": checks, "status": status, "processes": {"watchdog": watchdog, "runner": runner},
        "results": evidence, "cycles": cycles, "latest_battle_started": starts[-1] if starts else None,
        "recovery_events": [e for e in events if e["event"] in (
            "startup_ready", "resume_pending_mastery", "collection_return_to_deck", "lobby_return_to_deck", "late_post_battle_reward")],
        "source_sha256": {str(ROOT / "py-clash-bot" / name): digest(ROOT / "py-clash-bot" / name)
                          for name in SOURCE_FILES},
        "added_files": [str(ROOT / "py-clash-bot" / name) for name in (
            "pyclashbot/detection/reference_images/cn_minimal/reward_chest_unopened.png",
            "tests/test_cn_navigation_recovery.py", "tests/fixtures/cn_rewards/soft_floor_chest.png")],
        "baseline": {"completed": 752, "generated": 759, "closed_loops": 751, "claim_all_batches": 107},
        "rollback": {str(ROOT / "py-clash-bot" / name): {"backup": str(WORK / Path(name).name),
                       "backup_sha256": digest(WORK / Path(name).name)} for name in SOURCE_FILES},
        "validation": {"pytest": next((line for line in reversed((WORK / "tests.log").read_text(encoding="utf-8-sig").splitlines()) if "passed" in line), "pending"),
                       "test_log": str(WORK / "tests.log"), "py_compile_log": str(WORK / "py-compile.log")},
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"result": report["result"], "session": session, "status": status["state"],
                      "completed": status["completed"], "closed_loops": status["closed_loops"],
                      "cards": [status["cards_confirmed"], status["card_attempts"]], "results": evidence,
                      "checks": checks}, ensure_ascii=False))


if __name__ == "__main__":
    main()
