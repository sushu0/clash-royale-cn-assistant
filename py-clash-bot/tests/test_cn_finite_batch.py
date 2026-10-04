"""A validation batch must end at the lobby without being respawned."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from pyclashbot.bot.cn_1v1_loop import ChineseOneVOneLoop
from scripts import watch_cn_1v1


class TestFiniteBatch(unittest.TestCase):
    def test_does_not_stop_before_lobby_or_before_target(self):
        loop = ChineseOneVOneLoop.__new__(ChineseOneVOneLoop)
        loop.completed = 4
        loop.vision = Mock()
        frame = np.zeros((633, 419, 3), np.uint8)
        self.assertFalse(loop._finish_limited_batch(frame, 5))
        self.assertFalse(loop._finish_limited_batch(frame, 0))
        loop.vision.classify.assert_not_called()
        loop.completed = 5
        for state in ("battle", "result", "reward", "unknown"):
            with self.subTest(state=state):
                loop.vision.classify.return_value = (state, None)
                self.assertFalse(loop._finish_limited_batch(frame, 5))

    def test_target_lobby_records_evidence_and_stops_without_another_tap(self):
        with tempfile.TemporaryDirectory(prefix="finite-batch-test-") as directory:
            loop = ChineseOneVOneLoop.__new__(ChineseOneVOneLoop)
            loop.completed = loop.consecutive = 5
            loop.reward_taps = 4
            loop.reward_pending = True
            loop.logger = Mock()
            loop.vision = Mock()
            loop.vision.classify.return_value = ("lobby", None)
            loop.validation_dir = Path(directory)
            loop._save_evidence = Mock(return_value={"sha256": "test-evidence"})
            loop._trace = Mock()
            loop._tap = Mock()
            self.assertTrue(loop._finish_limited_batch(np.zeros((633, 419, 3), np.uint8), 5))
            loop._tap.assert_not_called()
            self.assertFalse(loop.reward_pending)
            self.assertEqual(loop.state, "stopped")
            result = json.loads((loop.validation_dir / "batch-complete.json").read_text(encoding="utf-8"))
            self.assertEqual(result["event"], "batch_complete")
            self.assertEqual(result["state"], "lobby")
            self.assertEqual(result["battle"], 5)
            self.assertEqual(result["evidence"]["sha256"], "test-evidence")

    def watcher_args(self, directory, limit):
        return [
            "watch_cn_1v1.py",
            "--adb",
            "adb.exe",
            "--serial",
            "test-device",
            "--memuc",
            "memuc.exe",
            "--log",
            str(Path(directory) / "battle.log"),
            "--watchdog-log",
            str(Path(directory) / "watchdog.log"),
            "--pid-file",
            str(Path(directory) / "pids.json"),
            "--max-battles",
            str(limit),
        ]

    @unittest.skipUnless(os.name == "nt", "Windows watchdog lifecycle")
    def test_watchdog_does_not_restart_successful_finite_runner(self):
        with tempfile.TemporaryDirectory(prefix="finite-watch-test-") as directory:
            child = Mock(pid=12345)
            child.wait.return_value = 0
            with (
                patch.object(watch_cn_1v1.sys, "argv", self.watcher_args(directory, 5)),
                patch.object(watch_cn_1v1.subprocess, "Popen", return_value=child) as launch,
                patch.object(watch_cn_1v1.time, "sleep") as sleep,
                patch.object(watch_cn_1v1, "process_record", return_value={"created_at": 1.0}),
                patch.object(watch_cn_1v1.logging, "basicConfig"),
                patch.object(watch_cn_1v1.ctypes.windll.kernel32, "SetThreadExecutionState", return_value=1),  # ty: ignore[unresolved-attribute]  # Windows-only skipped test
            ):
                watch_cn_1v1.main()
            self.assertEqual(launch.call_count, 1)
            self.assertIn("--max-battles", launch.call_args.args[0])
            sleep.assert_not_called()
            state = json.loads((Path(directory) / "pids.json").read_text(encoding="utf-8"))
            self.assertEqual(state["exit_reason"], "finite_run_ended")
            self.assertEqual(state["max_battles"], 5)

    @unittest.skipUnless(os.name == "nt", "Windows watchdog lifecycle")
    def test_normal_stop_and_failed_finite_runner_do_not_respawn_with_fresh_quota(self):
        for limit, exit_code in ((0, 0), (5, 1)):
            with (
                self.subTest(limit=limit, exit_code=exit_code),
                tempfile.TemporaryDirectory(prefix="finite-retry-test-") as directory,
            ):
                child = Mock(pid=12345)
                child.wait.return_value = exit_code
                with (
                    patch.object(watch_cn_1v1.sys, "argv", self.watcher_args(directory, limit)),
                    patch.object(
                        watch_cn_1v1.subprocess, "Popen", side_effect=[child, RuntimeError("second spawn")]
                    ) as launch,
                    patch.object(watch_cn_1v1.time, "sleep") as sleep,
                    patch.object(watch_cn_1v1, "process_record", return_value={"created_at": 1.0}),
                    patch.object(watch_cn_1v1.logging, "basicConfig"),
                    patch.object(watch_cn_1v1, "_report_pause"),  # Diagnostic ADB is independent of runner respawns.
                    patch.object(watch_cn_1v1.ctypes.windll.kernel32, "SetThreadExecutionState", return_value=1),  # ty: ignore[unresolved-attribute]  # Windows-only skipped test
                ):
                    watch_cn_1v1.main()
                self.assertEqual(launch.call_count, 1)
                sleep.assert_not_called()
                state = json.loads((Path(directory) / "pids.json").read_text(encoding="utf-8"))
                self.assertEqual(state["exit_reason"], "normal_or_drained" if limit == 0 else "finite_run_interrupted")


if __name__ == "__main__":
    unittest.main()
