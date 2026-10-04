"""Persist installed-source, button-invocation and continuing real-run evidence."""

from __future__ import annotations

import hashlib
import json
import marshal
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import CodeType

import psutil

ROOT = Path(r"D:\codex\CodexWork\clash")
WORK = ROOT / "work/startup-resume-repair-20261005"
SESSION = "20261005-005107"
BACKEND = ROOT / "outputs/wpf-desktop-stop-repair-20261004/backend"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def normalized(code):
    return code.replace(co_filename="<source>", co_consts=tuple(
        normalized(value) if isinstance(value, CodeType) else value for value in code.co_consts))


def main():
    source = ROOT / "py-clash-bot/pyclashbot/bot/cn_random_mastery_loop.py"
    mirror = BACKEND / "source/pyclashbot/bot/cn_random_mastery_loop.py"
    bytecode = BACKEND / "lib/pyclashbot/bot/cn_random_mastery_loop.pyc"
    assert digest(source) == digest(mirror) == "90AF73DCA68C5C6E578F66DF795BF2724389499C242211858355368103A3531D"
    assert normalized(marshal.loads(bytecode.read_bytes()[16:])) == normalized(
        compile(source.read_bytes(), str(source), "exec", dont_inherit=True, optimize=0))
    installation = read(WORK / "runtime-installation.json")
    monitor = read(WORK / "live-monitor.json")
    assert monitor["status"] == "PASS_COMPLETED_CYCLE_AND_NEXT_BATTLE"
    live = read(ROOT / "outputs/random-mastery-live-status.json")
    frontend = read(ROOT / "work/wpf-desktop/frontend-state.json")
    processes = read(ROOT / "work/bot-processes.json")
    assert frontend["state"] == "running" and frontend["pid"] == 19368
    assert live["session"] == SESSION and live["state"] not in ("paused", "stopped")
    assert live["completed"] >= 1263 and live["closed_loops"] >= 1263
    identities = []
    for role, component in (("watchdog", "watch_cn_1v1.py"), ("runner", "run_cn_1v1.py")):
        process = psutil.Process(processes[f"{role}_pid"])
        assert abs(process.create_time() - processes[f"{role}_created_at"]) < 0.01
        assert Path(process.exe()).resolve() == (BACKEND / "ClashBackend.exe").resolve()
        command = process.cmdline()
        assert command[1:3] == ["--component", component]
        assert "--max-battles" not in command
        identities.append({"role": role, "pid": process.pid, "created_at": process.create_time(),
                           "executable": process.exe(), "component": component,
                           "configured_max_battles": 0, "running": process.is_running()})
    receipts = [read(path) for path in WORK.glob("start-task-invoke-*.json")]
    assert len(receipts) == 1 and receipts[0]["status"] == "PASS_INVOKE_ISSUED"
    assert receipts[0]["invoke_issued"] and not receipts[0]["mouse_keyboard_input"]
    assert not receipts[0]["foreground_activation_requested"]
    session_work = ROOT / "work/random-mastery" / SESSION
    archives = list(session_work.glob("unresolved-battle-*.json"))
    assert len(archives) == 1
    archive = read(archives[0])
    assert archive["counts_as_completed"] is False
    assert archive["checkpoint_before"] == read(WORK / "before/checkpoint.json")
    assert len(archive["observations"]) == 2
    for observation in archive["observations"]:
        assert digest(Path(observation["path"])) == observation["sha256"].upper()
    result = read(session_work / "battle-1263.json")
    assert result["cards_confirmed"] == result["card_attempts"] == 7
    assert digest(Path(result["evidence"]["path"])) == result["evidence"]["sha256"].upper()
    validation = read(WORK / "startup-resume-source-validation.json")
    assert validation["offline_regression"]["passed"] == 250
    record = {
        "status": "PASS_REPAIRED_AND_INFINITE_BATTLES_RUNNING",
        "verified_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "cause": "A timed-out match left pending_battle set; later manual starts rejected the verified idle lobby.",
        "repair": "Two independent logged-in idle-lobby observations preserve the unresolved attempt before releasing its checkpoint.",
        "installation": installation, "button_invocation": receipts[0], "session": SESSION,
        "frontend_restarted": False, "computer_use": False, "robot_left_running": True,
        "manual_checkpoint_rewrite": False, "old_result_outbox_backup": str(WORK / "before/pending-result.json"),
        "unresolved_attempt_archive": str(archives[0]), "unresolved_attempt_counts_as_completed": False,
        "source_sha256": digest(source), "runtime_bytecode_sha256": digest(bytecode),
        "compiled_code_equals_tested_source": True,
        "validation": {"offline_tests_passed": 250, "new_regression_cases": 27,
                       "independent_review_regressions_passed": 62,
                       "python_compile_ruff_and_format": "PASS", "source_results": str(WORK / "startup-resume-source-validation.json")},
        "real_runtime": {"completed_battle_1263": result, "closed_cycle_1263": True,
                         "next_battle_1264_entered": True, "monitor": str(WORK / "live-monitor.json"),
                         "latest_live": live, "frontend": frontend, "process_identities": identities,
                         "game_screenshot": str(WORK / "screens/running.png")},
        "rollback": {"source": str(WORK / "before/cn_random_mastery_loop.before-resume-agent.py"),
                     "runtime": [row["rollback_file"] for row in installation["changes"]],
                     "method": "Stop the bot first, then restore only the archived source and runtime module files."},
        "limit": "This acceptance observes a completed cycle and automatic entry into the next battle; continued indefinite uptime is not asserted.",
    }
    target = ROOT / "outputs/STARTUP_RESUME_ACCEPTANCE_20261005.json"
    target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": record["status"], "report": str(target), "session": SESSION,
                      "latest_state": live["state"], "completed": live["completed"],
                      "closed_loops": live["closed_loops"], "robot_left_running": True}))


if __name__ == "__main__":
    main()
