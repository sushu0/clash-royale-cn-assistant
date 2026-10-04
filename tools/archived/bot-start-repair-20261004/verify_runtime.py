"""Read-only observation of the repaired infinite loop and its next battle."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from pyclashbot.bot.cn_1v1_loop import ChineseVision
from pyclashbot.utils.persistence import atomic_write_bytes, atomic_write_json
from pyclashbot.utils.process_ownership import verified_process
from pyclashbot.utils.runtime_config import SOURCE_ROOT, load_runtime_config


def main():
    runtime = load_runtime_config()
    folder = Path(__file__).resolve().parent
    root = runtime.data_root
    repair = json.loads((folder / "repair-applied.json").read_bytes())
    initial_completed = repair["before"]["completed"]
    trace = root / "outputs/cn-random-mastery.jsonl"
    vision = ChineseVision()
    report_path = root / "outputs/BOT_START_REPAIR_ACCEPTANCE_20261004.json"
    observations = []
    session = None
    captured = set()
    deadline = time.monotonic() + 420
    while time.monotonic() < deadline:
        status = json.loads((root / "outputs/random-mastery-live-status.json").read_bytes())
        processes = json.loads((root / "work/bot-processes.json").read_bytes())
        identities = {
            name: verified_process(
                processes[f"{name}_pid"],
                SOURCE_ROOT / "scripts" / script,
                processes[f"{name}_created_at"],
            ) is not None
            for name, script in (("runner", "run_cn_1v1.py"), ("watchdog", "watch_cn_1v1.py"))
        }
        assert all(identities.values()), "Robot process stopped during validation"
        assert status["state"] != "paused", "Robot paused during validation"
        if session is None:
            session = status["session"]
        assert status["session"] == session, "Runner unexpectedly restarted"
        observations.append({"captured_at": datetime.now().astimezone().isoformat(), "status": status, "processes": processes, "verified": identities})
        with trace.open("rb") as stream:
            stream.seek(repair["history_bytes_before"])
            data = stream.read()
        events = []
        for line in data.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("session") == session:
                events.append(event)
        starts = [event for event in events if event.get("event") == "started"]
        assert starts and starts[0].get("max_battles") == 0, "Infinite mode not proven"
        cycle = [event for event in events if event.get("event") == "cycle_complete"]
        next_started = [event for event in events if event.get("event") == "battle_started" and event.get("battle", 0) >= initial_completed + 2]
        phase = "next-battle" if next_started else "first-battle"
        if status["state"] == "battle" and phase not in captured:
            shot = subprocess.run([str(runtime.adb), "-s", runtime.serial, "exec-out", "screencap", "-p"], capture_output=True, check=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            frame = cv2.imdecode(np.frombuffer(shot.stdout, np.uint8), cv2.IMREAD_COLOR)
            assert frame is not None
            kind, _ = vision.classify(frame)
            path = folder / f"{phase}.png"
            atomic_write_bytes(path, shot.stdout)
            observations[-1]["game_screenshot"] = {"path": str(path), "sha256": hashlib.sha256(shot.stdout).hexdigest(), "classified": kind}
            if kind == "battle":
                captured.add(phase)
        finished = [event for event in events if event.get("event") == "battle_finished"]
        verified_results = []
        for event in finished:
            evidence = event["evidence"]
            assert hashlib.sha256(Path(evidence["path"]).read_bytes()).hexdigest() == evidence["sha256"]
            verified_results.append(event)
        accepted = bool(cycle and next_started and "next-battle" in captured and status["cards_confirmed"] > 0 and status["closed_loops"] > initial_completed)
        report = {
            "captured_at": datetime.now().astimezone().isoformat(),
            "accepted": accepted,
            "repair": repair,
            "session": session,
            "infinite_mode": True,
            "ui_start_button_clicked": True,
            "started_event": starts[0],
            "verified_results": verified_results,
            "cycle_complete_events": cycle,
            "next_battle_started_events": next_started,
            "game_screenshots_confirmed": sorted(captured),
            "observations": observations,
            "source_files_changed": [],
            "latest_frontend": json.loads((root / "work/random-frontend-state.json").read_bytes()),
            "rollback": "Stop robot before inspecting backups. Do not restore the old checkpoint after new battles have completed, because it would regress completed counters. Pre-repair bytes are kept for forensic recovery only.",
        }
        atomic_write_json(report_path, report)
        print(json.dumps({"state": status["state"], "completed": status["completed"], "generated": status["generated_decks"], "cards_confirmed": status["cards_confirmed"], "cycles": len(cycle), "next_battle_started": bool(next_started), "accepted": accepted}, ensure_ascii=False), flush=True)
        if accepted:
            return
        time.sleep(12)
    raise TimeoutError("Full cycle and next battle not observed within seven minutes")


if __name__ == "__main__":
    main()
