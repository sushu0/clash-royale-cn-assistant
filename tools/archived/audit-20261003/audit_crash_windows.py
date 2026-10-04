"""Fault injection against synthetic runners; no emulator construction or input."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from unittest.mock import Mock

import numpy as np

ROOT = Path(r"D:\codex\CodexWork\clash")
sys.path.insert(0, str(ROOT / "py-clash-bot"))
from pyclashbot.bot.cn_random_mastery_loop import RandomMasteryLoop
from pyclashbot.bot.worker import WorkerProcess


def main():
    reports = {}
    runner = RandomMasteryLoop.__new__(RandomMasteryLoop)
    runner.pending_battle = True
    runner.pending_mastery = False
    runner.completed = 0
    runner.cards_confirmed = runner.card_attempts = 1
    runner.consecutive = 0
    runner.generated = 1
    runner.active_battle = 1
    runner.logger = logging.getLogger("synthetic-crash-test")
    runner.work = ROOT / "work" / "audit-20261003" / "synthetic"
    runner.vision = Mock()
    runner.vision.classify.return_value = ("result", None)
    runner.vision.outcome.return_value = "胜利"
    runner._frame = lambda: np.zeros((633, 419, 3), dtype=np.uint8)
    events = []
    saved_checkpoint = {}
    runner._event = lambda event, **_values: events.append(event)
    runner._battle_frame_stalled = lambda *_args: False

    def checkpoint():
        saved_checkpoint.update(completed=runner.completed,
                                pending_battle=runner.pending_battle,
                                pending_mastery=runner.pending_mastery)

    def synthetic_save(name, _frame):
        if name == "result":
            raise OSError("Synthetic interruption after checkpoint, before result publication")
        return {}

    runner._checkpoint = checkpoint
    runner._save = synthetic_save
    try:
        runner._battle(resumed=True)
    except OSError as error:
        reports["result_publication_gap"] = {
            "checkpoint": saved_checkpoint, "events": events,
            "has_finished_event": "battle_finished" in events,
            "exception": str(error),
        }

    # Use actual worker state-loop logic with a synthetic state function.
    import pyclashbot.bot.worker as worker_module

    original_tree = worker_module.state_tree
    counts = {"calls": 0, "restarts": 0}
    stop = Mock()
    stop.is_set.side_effect = lambda: counts["calls"] >= 14

    def synthetic_tree(_emulator, _logger, state, *_args):
        counts["calls"] += 1
        if state == "restart":
            return "start"
        counts["restarts"] += 1
        return "restart"

    worker = WorkerProcess.__new__(WorkerProcess)
    worker.shutdown_event = stop
    worker_module.state_tree = synthetic_tree
    try:
        worker._run_bot_loop(None, {}, Mock())
    finally:
        worker_module.state_tree = original_tree
    reports["restart_budget_reset"] = counts
    destination = ROOT / "work" / "audit-20261003" / "crash-window-evidence.json"
    destination.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(reports, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
