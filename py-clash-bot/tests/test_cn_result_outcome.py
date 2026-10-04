"""Real Tencent result frames where confetti obscures title templates."""

import unittest
from pathlib import Path

import cv2
import numpy as np

from pyclashbot.bot.cn_1v1_loop import ChineseVision

FIXTURES = Path(__file__).parent / "fixtures" / "cn_results"


class ChineseResultOutcomeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vision = ChineseVision()

    def test_real_wins_and_losses_including_confetti_unknowns(self):
        expected = {
            "win_two_one_confetti.png": "胜利",
            "win_two_zero.png": "胜利",
            "loss_with_blue_crown.png": "失败",
            "loss_unknown_three_crowns.png": "失败",
            "loss_unknown_two_crowns.png": "失败",
        }
        for filename, outcome in expected.items():
            with self.subTest(filename=filename):
                frame = cv2.imread(str(FIXTURES / filename))
                assert frame is not None and frame.size > 0, f"Cannot decode result fixture: {FIXTURES / filename}"
                self.assertEqual(self.vision.classify(frame)[0], "result")
                self.assertEqual(self.vision.outcome(frame), outcome)

    def test_no_crowns_is_unknown(self):
        frame = np.zeros((633, 419, 3), dtype=np.uint8)
        self.assertEqual(self.vision.outcome(frame), "未知")


if __name__ == "__main__":
    unittest.main()
