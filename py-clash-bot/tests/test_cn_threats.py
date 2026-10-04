"""Limited threat templates: independent positives and hard abstentions."""

import unittest
from pathlib import Path

import cv2
import numpy as np

from pyclashbot.detection.cn_battle_cues import read_cn_battle_cues
from pyclashbot.detection.cn_threats import read_cn_threats

FIXTURES = Path(__file__).parent / "fixtures" / "cn_threats"


def frame(name):
    return cv2.imread(str(FIXTURES / name))


def detect(name):
    image = frame(name)
    return read_cn_threats(image, read_cn_battle_cues(image)["enemies"])


class ChineseThreatTests(unittest.TestCase):
    def test_early_balloon_heldout_91_uses_full_chain_without_clamping(self):
        result = read_cn_battle_cues(frame("early_balloon_crossing_heldout.png"))
        early = [r for r in result["threats"] if r.get("origin") == "early_air"]
        self.assertTrue(early)
        self.assertTrue(any((r["x"], r["y"]) == (119, 232) for r in early))
        self.assertIn((119, 232), result["enemies"])
        self.assertTrue(all(r["confidence"] >= 0.78 and r["label_confidence"] >= 0.75 for r in early))

    def test_early_balloon_other_non_source_pushes(self):
        for name in ("early_balloon_first_push_heldout.png", "early_balloon_second_push_heldout.png"):
            with self.subTest(name=name):
                result = read_cn_battle_cues(frame(name))
                early = [r for r in result["threats"] if r.get("origin") == "early_air"]
                self.assertTrue(early)
                self.assertTrue(all(r["kind"] == "air" and r["template_id"] == "air_balloon_envelope" for r in early))
                self.assertTrue(all((r["x"], r["y"]) in result["enemies"] for r in early))

    def test_early_balloon_requires_red_numerals_not_just_hull(self):
        image = frame("early_balloon_crossing_heldout.png")
        # Remove only bright numeral pixels above the hull; keep the hull itself.
        label = image[211:219, 114:124]
        hsv = cv2.cvtColor(label, cv2.COLOR_BGR2HSV)
        white = (hsv[:, :, 1] <= 90) & (hsv[:, :, 2] >= 190)
        label[white] = (38, 10, 100)
        self.assertFalse(any(r.get("origin") == "early_air" for r in read_cn_battle_cues(image)["threats"]))

    def test_early_pass_does_not_admit_untyped_ground_or_decorations(self):
        for name in (
            "ordinary_single.png",
            "ground_swarm.png",
            "empty_and_friendly.png",
            "red_single_highlight.png",
            "royal_giant_source.png",
        ):
            with self.subTest(name=name):
                self.assertFalse(
                    any(r.get("origin") == "early_air" for r in read_cn_battle_cues(frame(name))["threats"])
                )

    def test_early_pass_is_opt_in_for_direct_threat_reader(self):
        image = frame("early_balloon_crossing_heldout.png")
        self.assertEqual(read_cn_threats(image, []), [])
        self.assertTrue(read_cn_threats(image, [], include_early_air=True))

    def test_red_balloon_envelope_source_is_separate_from_other_time_frames(self):
        result = detect("balloon_envelope_source.png")
        self.assertTrue(any(r["template_id"] == "air_balloon_envelope" and r["confidence"] > 0.99 for r in result))

    def test_red_balloon_envelope_other_times_use_complete_cues_chain(self):
        for name in (
            "balloon_envelope_approaching.png",
            "balloon_envelope_under_damage.png",
            "balloon_envelope_second_push.png",
        ):
            with self.subTest(name=name):
                result = read_cn_battle_cues(frame(name))["threats"]
                balloon = [r for r in result if r["template_id"] == "air_balloon_envelope"]
                self.assertTrue(balloon)
                self.assertTrue(
                    all(r["kind"] == "air" and r["confidence"] >= 0.78 and r["red_fraction"] >= 0.60 for r in balloon)
                )

    def test_red_balloon_envelope_unfamiliar_angle_remains_unknown(self):
        self.assertFalse(
            any(r["template_id"] == "air_balloon_envelope" for r in detect("balloon_envelope_unknown_angle.png"))
        )

    def test_royal_giant_source_and_recoil_are_separate_calibration_frames(self):
        for name in ("royal_giant_source.png", "royal_giant_recoil_source.png"):
            with self.subTest(name=name):
                result = detect(name)
                self.assertTrue(
                    any(r["template_id"] == "rush_royal_giant_head" and r["kind"] == "rush" for r in result)
                )

    def test_royal_giant_other_times_work_through_automatic_enemy_markers(self):
        for name in ("royal_giant_independent_fire.png", "royal_giant_independent_after.png"):
            with self.subTest(name=name):
                result = read_cn_battle_cues(frame(name))["threats"]
                royal = [r for r in result if r["template_id"] == "rush_royal_giant_head"]
                self.assertTrue(royal)
                self.assertTrue(all(r["confidence"] >= 0.88 and (r["x"], r["y"]) == (292, 278) for r in royal))

    def test_royal_giant_muzzle_flash_pose_can_remain_unknown(self):
        self.assertFalse(
            any(r["template_id"] == "rush_royal_giant_head" for r in detect("royal_giant_independent_later.png"))
        )

    def test_source_self_match_is_recorded_separately(self):
        result = detect("air_source.png")
        self.assertTrue(any(r["template_id"] == "air_skeleton_barrel_top" and r["confidence"] > 0.99 for r in result))

    def test_two_independent_sessions_recognize_the_limited_air_subtype(self):
        for name in ("air_independent_bridge.png", "air_independent_deep.png"):
            with self.subTest(name=name):
                result = detect(name)
                self.assertTrue(result)
                self.assertTrue(
                    all(r["kind"] == "air" and r["template_id"] == "air_skeleton_barrel_top" for r in result)
                )
                self.assertTrue(all(r["confidence"] >= 0.74 and r["red_fraction"] >= 0.55 for r in result))
                self.assertTrue(all(len(r["source_sha256"]) == 64 for r in result))

    def test_low_similarity_air_pose_is_unknown(self):
        self.assertEqual(detect("air_unknown_pose.png"), [])

    def test_ordinary_unit_swarm_red_highlight_and_empty_board_are_unknown(self):
        for name in ("ordinary_single.png", "ground_swarm.png", "empty_and_friendly.png", "red_single_highlight.png"):
            with self.subTest(name=name):
                self.assertEqual(detect(name), [])

    def test_friendly_blue_label_is_not_an_enemy_anchor(self):
        self.assertEqual(read_cn_threats(frame("air_source.png"), [(111, 266)]), [])

    def test_no_anchor_or_bad_frame_is_unknown(self):
        self.assertEqual(read_cn_threats(frame("air_source.png"), []), [])
        self.assertEqual(read_cn_threats(np.zeros((100, 100, 3), np.uint8), [(50, 50)]), [])

    def test_grayscale_shape_cannot_replace_red_color_evidence(self):
        image = frame("air_source.png")
        gray = cv2.cvtColor(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
        self.assertEqual(read_cn_threats(gray, [(323, 297)]), [])


if __name__ == "__main__":
    unittest.main()
