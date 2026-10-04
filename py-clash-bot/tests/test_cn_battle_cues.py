"""Replay real Tencent frames for missed labels and confusing red artwork."""

import unittest
from pathlib import Path

import cv2
import numpy as np

from pyclashbot.detection.cn_battle_cues import _gold_level_plaques, read_cn_battle_cues

FIXTURES = Path(__file__).parent / "fixtures" / "cn_battle_cues"


def load_frame(name) -> np.ndarray:
    path = FIXTURES / name
    frame = cv2.imread(str(path))
    assert frame is not None and frame.size > 0, f"Cannot decode battle fixture: {path}"
    return frame


def cues(name):
    return read_cn_battle_cues(load_frame(name))


def close_to(points, target, tolerance=3):
    return any(abs(x - target[0]) <= tolerance and abs(y - target[1]) <= tolerance for x, y in points)


def test_dark_health_trough_and_merged_deep_labels_are_detected():
    points = cues("deep_tank_cluster.png")["enemies"]
    # One 27x10 plaque+trough and two plaques joined into a 47x22 component.
    for target in ((280, 391), (219, 416), (239, 422)):
        assert close_to(points, target)


def test_touching_swarm_labels_do_not_collapse_to_one_pressure_marker():
    points = cues("split_swarm.png")["enemies"]
    for target in ((93, 364), (108, 343), (122, 336), (295, 339), (308, 330)):
        assert close_to(points, target)


def test_red_balloon_highlight_is_not_an_extra_level_plaque():
    points = cues("balloon_highlight.png")["enemies"]
    assert close_to(points, (323, 297))
    assert close_to(points, (353, 304))
    # This red/white body patch passes square-border geometry but not numerals.
    assert not close_to(points, (325, 305), tolerance=3)


def test_empty_lanes_and_friendly_tower_trim_stay_clear():
    for name in ("empty_lanes.png", "own_tower_trim.png"):
        assert cues(name)["enemies"] == []


def test_flat_colors_are_not_numeral_plaques():
    for color in ((0, 0, 0), (255, 255, 255), (0, 0, 255)):
        frame = np.full((633, 419, 3), color, dtype=np.uint8)
        assert read_cn_battle_cues(frame)["enemies"] == []


def test_wrong_frame_shape_remains_unknown():
    result = read_cn_battle_cues(np.zeros((480, 320, 3), dtype=np.uint8))
    assert result["enemies"] == []
    assert result["elixir"] is None
    assert result["enemy_towers"] == {"left": None, "right": None}


class ChineseBattleCuesTests(unittest.TestCase):
    def test_dark_body_candidates_use_real_plaque_anchors_and_abstain_on_air_and_army(self):
        left_before = cues("dark_ground_left_before.png")["dark_ground_candidates"]
        left_after = cues("dark_ground_left_after.png")["dark_ground_candidates"]
        right_before = cues("dark_ground_right_before.png")["dark_ground_candidates"]
        right_after = cues("dark_ground_right_after.png")["dark_ground_candidates"]
        self.assertTrue(any(abs(c["x"] - 129) <= 7 and c["dark_pixels"] >= 330 for c in left_before))
        self.assertTrue(any(abs(c["x"] - 112) <= 7 and c["dark_pixels"] >= 400 for c in left_after))
        self.assertTrue(any(abs(c["x"] - 290) <= 7 and c["dark_pixels"] >= 330 for c in right_before))
        self.assertTrue(any(abs(c["x"] - 296) <= 7 and c["dark_pixels"] >= 400 for c in right_after))
        self.assertEqual(cues("dark_ground_skeleton_army.png")["dark_ground_candidates"], [])
        self.assertEqual(cues("dark_ground_balloon.png")["dark_ground_candidates"], [])

    def test_real_friendly_tower_bar_reports_actual_damage(self):
        full = cues("own_tower_full.png")
        hit = cues("own_tower_hit.png")
        self.assertGreaterEqual(full["own_tower_fill"]["right"], 0.95)
        self.assertGreaterEqual(hit["own_tower_fill"]["right"], 0.65)
        self.assertLessEqual(hit["own_tower_fill"]["right"], 0.70)
        self.assertGreater(full["own_tower_fill"]["right"] - hit["own_tower_fill"]["right"], 0.20)

    def test_real_shifted_friendly_bars_remain_readable(self):
        two_up = cues("own_tower_shifted_2_full.png")
        two_up_hit = cues("own_tower_shifted_2_hit.png")
        three_up = cues("own_tower_shifted_3_skin.png")
        for sample in (two_up, three_up):
            self.assertGreaterEqual(sample["own_tower_fill"]["left"], 0.95)
            self.assertGreaterEqual(sample["own_tower_fill"]["right"], 0.94)
        self.assertLess(two_up_hit["own_tower_fill"]["right"], 0.90)
        self.assertGreater(two_up["own_tower_fill"]["right"] - two_up_hit["own_tower_fill"]["right"], 0.10)

    def test_real_skin_without_top_trough_uses_three_stable_rows(self):
        full = cues("own_tower_no_top_trough_full.png")
        hit = cues("own_tower_no_top_trough_hit.png")
        self.assertGreater(full["own_tower_fill"]["left"], 0.95)
        self.assertGreater(full["own_tower_fill"]["right"], 0.95)
        self.assertLess(hit["own_tower_fill"]["left"], 0.27)
        self.assertGreater(full["own_tower_fill"]["left"] - hit["own_tower_fill"]["left"], 0.65)

    def test_real_high_princess_skin_bar_tracks_damage(self):
        full = cues("own_tower_high_skin_full.png")
        hit = cues("own_tower_high_skin_hit.png")
        self.assertGreater(full["own_tower_fill"]["right"], 0.95)
        self.assertGreater(hit["own_tower_fill"]["right"], 0.45)
        self.assertLess(hit["own_tower_fill"]["right"], 0.55)

    def test_destroyed_friendly_towers_do_not_gain_invented_health(self):
        self.assertEqual(cues("own_tower_both_destroyed.png")["own_tower_fill"], {"left": None, "right": None})

    def test_real_hit_flash_does_not_halve_visible_tower_health(self):
        flashing = cues("tower_damage_flash.png")
        self.assertIs(flashing["enemy_towers"]["left"], True)
        self.assertIs(flashing["enemy_towers"]["right"], True)
        self.assertEqual(flashing["enemy_tower_fill"], {"left": None, "right": None})

    def test_frozen_seven_unit_bridge_group_stays_far_until_it_crosses(self):
        observation = cues("bridge_cluster_before.png")
        self.assertFalse(any(y >= 300 for _, y in observation["enemies"]))
        left = [(x, y) for x, y in observation["far_warnings"] if x < 209]
        self.assertGreaterEqual(len(left), 5)
        self.assertGreaterEqual(max(y for _, y in left), 245)

    def test_real_low_tower_bar_is_read_as_fill_not_exact_hp(self):
        observation = cues("low_tower_437.png")
        self.assertIs(observation["enemy_towers"]["right"], True)
        self.assertGreaterEqual(observation["enemy_tower_fill"]["right"], 0.08)
        self.assertLessEqual(observation["enemy_tower_fill"]["right"], 0.13)
        self.assertIsNone(observation["enemy_tower_fill"]["left"])

    def test_real_126_hp_tower_is_visible_and_within_one_spell_band(self):
        observation = cues("low_tower_126.png")
        self.assertIs(observation["enemy_towers"]["left"], True)
        self.assertGreater(observation["enemy_tower_fill"]["left"], 0)
        self.assertLessEqual(observation["enemy_tower_fill"]["left"], 0.04)

    def test_far_warning_sees_real_bridge_approach_without_inventing_pressure(self):
        observation = cues("far_warning_before_attack.png")
        self.assertEqual(observation["enemies"], [])
        self.assertTrue(close_to(observation["far_warnings"], (289, 204)))
        self.assertTrue(close_to(observation["far_warnings"], (319, 220)))
        self.assertEqual(cues("empty_lanes.png")["far_warnings"], [])

    def test_gold_hostile_style_other_time_not_only_source_match(self):
        points = cues("gold_enemy_other_time.png")["enemies"]
        for target in ((102, 361), (128, 390), (139, 330), (150, 360)):
            self.assertTrue(close_to(points, target))

    def test_gold_hostile_style_other_battle(self):
        points = cues("gold_enemy_other_battle.png")["enemies"]
        self.assertGreaterEqual(len(points), 5)
        self.assertTrue(close_to(points, (137, 342)))

    def test_gold_sources_preserve_old_pressure_and_add_deep_enemies(self):
        points = cues("gold_enemy_source16.png")["enemies"]
        self.assertIn((311, 256), points)
        for target in ((121, 355), (155, 333), (156, 382), (270, 380)):
            self.assertTrue(close_to(points, target))
        # Ambiguous 13 marker near mixed troops is not a positive training label.
        self.assertFalse(close_to(points, (333, 383), tolerance=4))

    def test_friendly_skeletons_and_tower_gold_badges_stay_clear(self):
        self.assertEqual(cues("gold_friendly_and_towers.png")["enemies"], [])

    def test_gold_digits_on_blue_background_are_not_hostile(self):
        image = load_frame("gold_enemy_source16.png")
        glyph = image[334:344, 117:126].copy()
        hsv = cv2.cvtColor(glyph, cv2.COLOR_BGR2HSV)
        red = ((hsv[:, :, 0] <= 9) | (hsv[:, :, 0] >= 166)) & (hsv[:, :, 1] >= 120) & (hsv[:, :, 2] >= 60)
        glyph[red] = (210, 110, 10)
        blank = np.full((633, 419, 3), (180, 195, 210), dtype=np.uint8)
        blank[330:340, 200:209] = glyph
        self.assertEqual(_gold_level_plaques(blank, cv2.cvtColor(blank, cv2.COLOR_BGR2HSV)), [])

    def test_gold_effects_and_highlights_are_not_gold_level_labels(self):
        for name in ("balloon_highlight.png", "own_tower_trim.png", "empty_lanes.png"):
            image = load_frame(name)
            self.assertEqual(_gold_level_plaques(image, cv2.cvtColor(image, cv2.COLOR_BGR2HSV)), [])

    def test_repaired_friendly_tower_trim_does_not_add_a_second_enemy(self):
        points = cues("friendly_tower_trim_false_tag.png")["enemies"]
        self.assertTrue(close_to(points, (301, 317)))
        self.assertFalse(close_to(points, (314, 381)))

    def test_real_enemies_at_the_friendly_tower_are_not_masked_out(self):
        points = cues("real_enemies_at_friendly_tower.png")["enemies"]
        for target in ((99, 371), (110, 372), (133, 371)):
            self.assertTrue(close_to(points, target))

    test_dark_health_trough_and_merged_deep_labels = staticmethod(
        test_dark_health_trough_and_merged_deep_labels_are_detected
    )
    test_touching_swarm_labels = staticmethod(test_touching_swarm_labels_do_not_collapse_to_one_pressure_marker)
    test_balloon_highlight = staticmethod(test_red_balloon_highlight_is_not_an_extra_level_plaque)
    test_empty_and_friendly_tower_trim = staticmethod(test_empty_lanes_and_friendly_tower_trim_stay_clear)
    test_flat_colors = staticmethod(test_flat_colors_are_not_numeral_plaques)
    test_wrong_shape = staticmethod(test_wrong_frame_shape_remains_unknown)


if __name__ == "__main__":
    unittest.main()
