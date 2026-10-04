"""Bounded evidence, frozen clock and reward-context regression checks."""

import hashlib
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from pyclashbot.bot.cn_1v1_loop import ChineseOneVOneLoop, ChineseVision
from pyclashbot.bot.coords import CN_BATTLE_CLOCK_ROI, CN_REWARD_BACKGROUND_ROI


def load_frame(path: Path) -> np.ndarray:
    frame = cv2.imread(str(path))
    assert frame is not None and frame.size > 0, f"Cannot decode observation fixture: {path}"
    return frame


class TestLoopObservation(unittest.TestCase):
    def clock_loop(self):
        loop = ChineseOneVOneLoop.__new__(ChineseOneVOneLoop)
        loop.clock_mask = None
        loop.clock_changed_at = 0
        return loop

    def test_clock_stall_requires_full_45_seconds(self):
        loop = self.clock_loop()
        frame = np.zeros((633, 419, 3), np.uint8)
        self.assertFalse(loop._clock_stalled(frame, 10))
        self.assertFalse(loop._clock_stalled(frame, 54.9))
        self.assertTrue(loop._clock_stalled(frame, 55))

    def test_changed_clock_resets_stall_but_other_animation_does_not(self):
        loop = self.clock_loop()
        frame = np.zeros((633, 419, 3), np.uint8)
        loop._clock_stalled(frame, 0)
        frame[100:200, 20:200] = 255
        self.assertTrue(loop._clock_stalled(frame, 46))
        x, y, _, _ = CN_BATTLE_CLOCK_ROI
        frame[y : y + 8, x : x + 8] = 255
        self.assertFalse(loop._clock_stalled(frame, 47))
        self.assertFalse(loop._clock_stalled(frame, 91.9))
        self.assertTrue(loop._clock_stalled(frame, 92))

    def test_recent_evidence_is_bounded_and_overwrites_are_detectable(self):
        with tempfile.TemporaryDirectory(prefix="loop-evidence-test-") as directory:
            loop = self.clock_loop()
            loop.validation_dir = Path(directory)
            loop.evidence_counts = {}
            first = loop._save_evidence("observe", np.zeros((12, 12, 3), np.uint8))
            for n in range(1, 83):
                loop._save_evidence("observe", np.full((12, 12, 3), n, np.uint8))
            self.assertEqual(len(list(Path(directory).glob("*.png"))), 80)
            self.assertNotEqual(first["sha256"], hashlib.sha256(Path(first["path"]).read_bytes()).hexdigest())

    def test_all_hundred_results_remain_available_for_winrate_verification(self):
        with tempfile.TemporaryDirectory(prefix="result-evidence-test-") as directory:
            loop = self.clock_loop()
            loop.validation_dir = Path(directory)
            loop.evidence_counts = {}
            records = [loop._save_evidence("result", np.full((12, 12, 3), n, np.uint8)) for n in range(100)]
            self.assertEqual(len({record["path"] for record in records}), 100)
            for record in records:
                self.assertEqual(record["sha256"], hashlib.sha256(Path(record["path"]).read_bytes()).hexdigest())

    def test_reward_continuation_requires_floor_and_blue_background(self):
        vision = ChineseVision.__new__(ChineseVision)
        vision.find = Mock(return_value=object())
        frame = np.zeros((633, 419, 3), np.uint8)
        x1, y1, x2, y2 = CN_REWARD_BACKGROUND_ROI
        frame[y1:y2, x1:x2] = (140, 55, 15)
        self.assertTrue(vision.reward_continuation(frame))
        vision.find.return_value = None
        self.assertFalse(vision.reward_continuation(frame))
        vision.find.return_value = object()
        frame[y1:y2, x1:x2] = (20, 120, 40)
        self.assertFalse(vision.reward_continuation(frame))

    def test_actual_purple_reveal_is_recognized_without_prior_context(self):
        frame = load_frame(Path(__file__).parent / "fixtures/cn_rewards/purple_reveal.png")
        vision = ChineseVision()
        self.assertEqual(vision.classify(frame)[0], "reward")
        self.assertTrue(vision.reward_continuation(frame))

    def test_actual_puzzle_reveal_continues_but_plain_blue_does_not(self):
        frame = load_frame(Path(__file__).parent / "fixtures/cn_rewards/blue_puzzle_reveal.png")
        vision = ChineseVision()
        self.assertEqual(vision.classify(frame)[0], "reward")
        self.assertTrue(vision.reward_continuation(frame))
        flat = np.full((633, 419, 3), (140, 55, 15), np.uint8)
        self.assertFalse(vision.reward_continuation(flat))

    def test_legendary_puzzle_uses_title_and_unlocked_independent_of_sky_color(self):
        frame = load_frame(Path(__file__).parent / "fixtures/cn_rewards/legendary_puzzle_reveal.png")
        vision = ChineseVision()
        self.assertEqual(vision.classify(frame)[0], "reward")
        self.assertTrue(vision.reward_continuation(frame))

    def make_step_loop(self, pending):
        loop = self.clock_loop()
        loop.vision = Mock()
        loop.vision.classify.return_value = ("unknown", None)
        loop.vision.reward_continuation.return_value = True
        loop.vision.four_star_reward.return_value = False
        loop.reward_pending = pending
        loop.reward_taps = 0
        loop.four_star_reward_seen = False
        loop.last_reward_tap_at = 100.0
        loop.last_four_star_tap_at = 0.0
        loop.last_unknown_evidence = 100
        loop.state_since = 100
        loop.state = "lobby"
        loop.battle_confirmations = 0
        loop.completed = 99
        loop.logger = logging.getLogger("loop-test")
        loop._tap = Mock()
        loop._trace = Mock()
        loop._save_evidence = Mock(return_value={})
        return loop

    @patch("pyclashbot.bot.cn_1v1_loop.time.sleep")
    @patch("pyclashbot.bot.cn_1v1_loop.time.monotonic", return_value=101)
    def test_unknown_blue_page_is_not_clicked_without_reward_context(self, *_):
        loop = self.make_step_loop(False)
        loop._step(np.zeros((633, 419, 3), np.uint8))
        loop._tap.assert_not_called()
        loop.vision.reward_continuation.assert_not_called()

    @patch("pyclashbot.bot.cn_1v1_loop.time.sleep")
    @patch("pyclashbot.bot.cn_1v1_loop.time.monotonic", return_value=101)
    def test_recognized_reward_sequence_can_continue_without_star(self, *_):
        loop = self.make_step_loop(True)
        loop._step(np.zeros((633, 419, 3), np.uint8))
        loop._tap.assert_called_once()
        self.assertEqual(loop.reward_taps, 1)

    def test_four_star_reveal_needs_existing_reward_context_and_throttles_taps(self):
        folder = Path(__file__).parent / "fixtures/cn_rewards"
        vision = ChineseVision()
        for name in ("four_star_chest.png", "four_star_card.png"):
            frame = load_frame(folder / name)
            with self.subTest(name=name):
                self.assertEqual(vision.classify(frame)[0], "unknown")
                self.assertTrue(vision.four_star_reward(frame))
                self.assertTrue(vision.reward_continuation(frame))

        frame = load_frame(folder / "four_star_chest.png")
        with (
            patch("pyclashbot.bot.cn_1v1_loop.time.monotonic", return_value=101),
            patch("pyclashbot.bot.cn_1v1_loop.time.sleep"),
        ):
            loop = self.make_step_loop(False)
            loop.vision = vision
            loop._step(frame)
            loop._tap.assert_not_called()
            loop = self.make_step_loop(True)
            loop.reward_taps = 3
            loop.vision = vision
            loop._step(frame)
            loop._tap.assert_called_once()
            self.assertEqual(loop.reward_taps, 4)
            self.assertTrue(loop.four_star_reward_seen)
        with patch("pyclashbot.bot.cn_1v1_loop.time.monotonic", return_value=104):
            loop._step(frame)
            loop._tap.assert_called_once()  # no second tap during the same reveal animation
        with (
            patch("pyclashbot.bot.cn_1v1_loop.time.monotonic", return_value=107),
            patch("pyclashbot.bot.cn_1v1_loop.time.sleep"),
        ):
            loop._step(frame)
            self.assertEqual(loop._tap.call_count, 2)

    def test_rainbow_flip_waits_briefly_and_then_recovers_if_stuck(self):
        frame = load_frame(Path(__file__).parent / "fixtures/cn_rewards/rainbow_reward_transition.png")
        vision = ChineseVision()
        self.assertEqual(vision.classify(frame)[0], "unknown")
        self.assertFalse(vision.four_star_reward(frame))
        loop = self.make_step_loop(True)
        loop.vision = vision
        loop.reward_taps = 5
        loop.last_reward_tap_at = 100.0
        loop._recover = Mock()
        with patch("pyclashbot.bot.cn_1v1_loop.time.monotonic", return_value=120):
            loop._step(frame)
            loop._tap.assert_not_called()
            loop._recover.assert_not_called()
        with patch("pyclashbot.bot.cn_1v1_loop.time.monotonic", return_value=146):
            loop._step(frame)
            loop._recover.assert_called_once()

    def test_four_star_palette_does_not_match_normal_battle_or_other_rewards(self):
        vision = ChineseVision()
        folder = Path(__file__).parent / "fixtures"
        for path in (
            folder / "cn_battle_cues/empty_lanes.png",
            folder / "cn_rewards/purple_reveal.png",
            folder / "cn_rewards/rainbow_reward_transition.png",
        ):
            with self.subTest(path=path.name):
                self.assertFalse(vision.four_star_reward(load_frame(path)))


if __name__ == "__main__":
    unittest.main()
