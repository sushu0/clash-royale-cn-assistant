"""Observe one real cycle and its next battle without controlling the UI."""

from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(r"D:\codex\CodexWork\clash")
WORK = ROOT / "work/startup-resume-repair-20261005"
SESSION = "20261005-005107"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main():
    start = time.monotonic()
    samples = []
    last_key = None
    while time.monotonic() - start < 420:
        live = read(ROOT / "outputs/random-mastery-live-status.json")
        assert live.get("session") == SESSION, "Another session replaced the requested run"
        key = (live.get("state"), live.get("completed"), live.get("closed_loops"), live.get("generated_decks"))
        if key != last_key:
            row = {name: live.get(name) for name in ("updated_at", "session", "state", "pid", "completed",
                                                   "closed_loops", "generated_decks", "cards_confirmed", "last_event")}
            samples.append(row)
            last_key = key
            (WORK / "live-monitor.json").write_text(json.dumps({"samples": samples}, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(row, ensure_ascii=False), flush=True)
        if live["state"] in ("paused", "stopped"):
            raise RuntimeError(f"Requested run stopped: {live.get('last_event')}")
        if live.get("closed_loops", 0) >= 1263 and live.get("generated_decks", 0) >= 1275 and live["state"] == "battle":
            record = {"status": "PASS_COMPLETED_CYCLE_AND_NEXT_BATTLE", "samples": samples, "last_live": live,
                      "elapsed_seconds": time.monotonic() - start, "robot_stop_requested": False}
            (WORK / "live-monitor.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            print(record["status"], flush=True)
            return
        time.sleep(2)
    raise TimeoutError("One cycle and next battle did not complete within the observation budget")


if __name__ == "__main__":
    main()
