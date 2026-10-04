"""Offline behavioral checks for the CN 2.6 rules; no emulator or live I/O."""

from __future__ import annotations

import math
import unittest
from pathlib import Path

import cv2

from pyclashbot.bot.coords import (
    CN_HOG_BACK_POINTS,
    CN_HOG_BRIDGE_MUSKETEER_POINTS,
    CN_HOG_BRIDGE_POINTS,
    CN_HOG_CANNON_POINTS,
    CN_HOG_CENTRAL_MUSKETEER_POINTS,
    CN_HOG_DEEP_KITE_POINTS,
    CN_HOG_DEEP_MUSKETEER_POINTS,
    CN_HOG_DUAL_LANE_MUSKETEER_POINT,
    CN_HOG_FRIENDLY_TOWER_BOXES,
    CN_HOG_MUSKETEER_POINTS,
    CN_HOG_STALL_POINTS,
    CN_HOG_STALL_SAFE_BOUNDS,
    CN_HOG_SUPPORT_POINTS,
)
from pyclashbot.bot.hog_cycle_strategy import COSTS, HogCycleStrategy, HogDecision
from pyclashbot.detection.cn_battle_cues import read_cn_battle_cues


def hand(*cards: str) -> list[dict]:
    return [
        {"slot": slot, "card": card, "available": True, "variant": "elite_ice_golem" if card == "ice_golem" else card}
        for slot, card in enumerate(cards)
    ]


def threat(kind: str, x: int, y: int, confidence: float = 0.96) -> dict:
    return {"kind": kind, "x": x, "y": y, "confidence": confidence}


class TestCnHogStrategy(unittest.TestCase):
    def setUp(self) -> None:
        self.strategy = HogCycleStrategy(started_at=0.0)

    def test_real_tower_damage_breaks_recent_musketeer_wait_for_covered_cannon(self):
        enemy = [(305, 319)]
        cards = hand("musketeer", "cannon", "ice_spirit")
        full = {"left": 1.0, "right": 0.975}
        self.assertIsNone(self.strategy.decide(cards, 6, enemy, 50.0, own_tower_fill=full))
        musketeer = self.decision(self.strategy.decide(cards, 6, enemy, 50.5, own_tower_fill=full), "musketeer")
        self.strategy.record(musketeer, True, 50.5)
        hit = {"left": 1.0, "right": 0.671}
        response = self.decision(
            self.strategy.decide(hand("cannon", "ice_spirit", "log"), 3, [(305, 348)], 54.0, own_tower_fill=hit),
            "cannon",
        )
        self.assertEqual(response.point, CN_HOG_CANNON_POINTS["right"])

    def test_stable_or_unknown_tower_bar_keeps_recent_core_delay(self):
        for next_bar in ({"left": 1.0, "right": 0.975}, {"left": 1.0, "right": None}):
            with self.subTest(next_bar=next_bar):
                self.strategy = HogCycleStrategy(started_at=0)
                old = {"left": 1.0, "right": 0.975}
                self.strategy.decide(
                    hand("musketeer", "cannon", "ice_spirit"), 6, [(305, 319)], 50.0, own_tower_fill=old
                )
                first = self.decision(
                    self.strategy.decide(
                        hand("musketeer", "cannon", "ice_spirit"), 6, [(305, 319)], 50.5, own_tower_fill=old
                    ),
                    "musketeer",
                )
                self.strategy.record(first, True, 50.5)
                response = self.decision(
                    self.strategy.decide(hand("cannon", "ice_spirit"), 3, [(305, 348)], 54.0, own_tower_fill=next_bar),
                    "ice_spirit",
                )
                self.assertNotEqual(response.point, CN_HOG_CANNON_POINTS["right"])

    def test_missing_cannon_and_uncommitted_hog_prepares_central_musketeer(self):
        decision = self.decision(self.strategy.decide(hand("hog", "fireball", "musketeer"), 8, [], 10), "musketeer")
        self.assertEqual(decision.point, CN_HOG_DUAL_LANE_MUSKETEER_POINT)
        self.assertEqual(decision.category, "cycle")

    def test_cannon_in_hand_preserves_verified_spirit_hog_lead(self):
        decision = self.decision(
            self.strategy.decide(hand("hog", "ice_spirit", "musketeer", "cannon"), 8, [], 10), "ice_spirit"
        )
        self.assertIn("冰精灵先手", decision.reason)

    def test_shifted_cannon_covers_real_outer_lane_markers_without_reaching_behind_tower(self):
        left = CN_HOG_CANNON_POINTS["left"]
        right = CN_HOG_CANNON_POINTS["right"]
        self.assertLessEqual(math.dist(left, (100, 324)), 90)  # V5d B5, 03:11:07
        self.assertLessEqual(math.dist(left, (94, 310)), 90)  # V5d B9, 03:22:58
        self.assertGreater(math.dist(right, (340, 380)), 90)  # prior near-tower Cannon waste

    def test_real_seven_marker_bridge_group_uses_ready_fireball_before_crossing(self):
        approaching = [(94, 232), (95, 204), (114, 265), (115, 206), (121, 223), (128, 249), (130, 262)]
        cards = hand("cannon", "fireball", "log", "musketeer")
        self.assertIsNone(self.strategy.decide(cards, 10, [], 150, far_warnings=approaching))
        decision = self.decision(self.strategy.decide(cards, 10, [], 151, far_warnings=approaching), "fireball")
        self.assertEqual(decision.category, "spell")
        self.assertEqual(decision.point[0], 114)
        self.assertGreaterEqual(decision.point[1], 240)

    def test_frozen_five_marker_bridge_push_places_cannon_before_fireball(self):
        # Pilot 06 B2 at 04:12:26: a late Cannon went down after the group
        # had already reached our left Princess Tower.
        approaching = [(75, 235), (88, 243), (93, 231), (103, 269), (108, 249)]
        cards = hand("ice_golem", "fireball", "cannon", "musketeer")
        self.assertIsNone(self.strategy.decide(cards, 6, [], 10, far_warnings=approaching))
        decision = self.decision(self.strategy.decide(cards, 6, [], 11, far_warnings=approaching), "cannon")
        self.assertEqual(decision.point, CN_HOG_CANNON_POINTS["left"])
        self.assertEqual(decision.category, "defense")

    def test_three_bridge_markers_put_ice_spirit_in_threatened_lane(self):
        # Pilot 06 B3 cycled Ice Spirit behind the opposite tower while four
        # enemy units crossed the right bridge.
        approaching = [(289, 201), (292, 269), (312, 269)]
        cards = hand("log", "ice_golem", "ice_spirit", "fireball")
        self.assertIsNone(self.strategy.decide(cards, 6, [], 10, far_warnings=approaching))
        decision = self.decision(self.strategy.decide(cards, 6, [], 11, far_warnings=approaching), "ice_spirit")
        self.assertEqual(decision.point, CN_HOG_STALL_POINTS["right"])
        self.assertEqual(decision.category, "defense")

    def test_three_heavy_bridge_markers_use_available_cannon_before_spirit(self):
        # Pilot 07 B7: Cannon was in hand at five elixir, but the old gate
        # spent Ice Spirit first and let the heavy counterpush reach our tower.
        approaching = [(100, 254), (104, 269), (108, 249)]
        cards = hand("fireball", "ice_spirit", "cannon", "log")
        self.assertIsNone(self.strategy.decide(cards, 5, [], 10, far_warnings=approaching))
        decision = self.decision(self.strategy.decide(cards, 5, [], 11, far_warnings=approaching), "cannon")
        self.assertEqual(decision.point, CN_HOG_CANNON_POINTS["left"])
        self.assertEqual(decision.elixir - COSTS[decision.card], 2)

    def test_frozen_skeleton_army_fireball_leads_actual_impact_position(self):
        # Pilot 07 B2: y227 missed; the next frozen frame has the army around
        # y300 while the projectile is still in flight.
        approaching = [
            (90, 226),
            (96, 206),
            (105, 240),
            (106, 225),
            (108, 197),
            (110, 214),
            (121, 222),
            (121, 238),
            (122, 192),
            (123, 206),
            (134, 231),
            (134, 246),
            (135, 217),
            (138, 189),
            (138, 203),
        ]
        cards = hand("cannon", "musketeer", "fireball", "ice_golem")
        self.assertIsNone(self.strategy.decide(cards, 6, [], 10, far_warnings=approaching))
        decision = self.decision(self.strategy.decide(cards, 6, [], 11, far_warnings=approaching), "fireball")
        self.assertEqual(decision.point, (119, 281))
        self.assertLess(math.dist(decision.point, (110, 300)), 25)

    def test_small_or_scattered_far_markers_do_not_authorize_untargeted_fireball(self):
        cards = hand("cannon", "fireball", "log", "musketeer")
        far = [(90, 210), (130, 240), (310, 250)]
        self.strategy.decide(cards, 10, [], 150, far_warnings=far)
        decision = self.strategy.decide(cards, 10, [], 151, far_warnings=far)
        self.assertTrue(decision is None or decision.card != "fireball")

    def test_eight_elixir_ice_spirit_can_lead_hog_and_leave_three(self):
        lead = self.decision(self.strategy.decide(hand("hog", "ice_spirit", "cannon"), 8, [], 10), "ice_spirit")
        self.assertEqual(lead.category, "attack")
        self.assertEqual(lead.point, CN_HOG_SUPPORT_POINTS["left"])
        self.strategy.record(lead, True, 10)
        self.assertTrue(self.strategy.pending_hog_is_spirit)
        hog = self.decision(self.strategy.decide(hand("hog", "cannon", "log"), 7, [], 12), "hog")
        self.assertIn("冰精灵前置", hog.reason)
        self.assertEqual(hog.elixir - COSTS[hog.card], 3)
        self.strategy.record(hog, True, 12)
        self.assertFalse(self.strategy.pending_hog_is_spirit)
        self.assertEqual(self.strategy.supported_hog_at, 12)
        next_play = self.strategy.decide(hand("ice_spirit"), 4, [], 14)
        self.assertTrue(next_play is None or next_play.category != "attack")

    def test_failed_spirit_lead_does_not_promise_hog_followup(self):
        lead = self.decision(self.strategy.decide(hand("hog", "ice_spirit"), 8, [], 10), "ice_spirit")
        self.strategy.record(lead, False, 10)
        self.assertEqual(self.strategy.pending_hog_until, 0)
        self.assertFalse(self.strategy.pending_hog_is_spirit)

    def test_seven_elixir_hog_does_not_wait_for_spirit_lead(self):
        decision = self.decision(self.strategy.decide(hand("hog", "ice_spirit"), 7, [], 10), "hog")
        self.assertEqual(decision.elixir - COSTS[decision.card], 3)

    def test_real_437_hp_bar_holds_one_frame_then_targets_tower_with_fireball(self):
        tower_state = {"left": False, "right": True}
        visible_fill = {"left": None, "right": 0.10}
        cards = hand("log", "cannon", "musketeer", "fireball")
        self.assertIsNone(self.strategy.decide(cards, 10, [], 150, tower_state, enemy_tower_fill=visible_fill))
        decision = self.decision(
            self.strategy.decide(cards, 10, [], 151, tower_state, enemy_tower_fill=visible_fill), "fireball"
        )
        self.assertEqual(decision.point, (303, 130))
        self.assertEqual(decision.category, "spell")

    def test_low_health_ui_must_be_real_and_unobscured_before_spell(self):
        cards = hand("log", "cannon", "musketeer", "fireball")
        for towers, fill in (
            ({"left": None, "right": True}, {"right": 0.10}),
            ({"left": False, "right": False}, {"right": 0.10}),
            ({"left": False, "right": True}, {"right": None}),
            ({"left": False, "right": True}, {"right": 0.8}),
        ):
            with self.subTest(towers=towers, fill=fill):
                self.strategy = HogCycleStrategy(started_at=0)
                result = self.strategy.decide(cards, 10, [], 150, towers, enemy_tower_fill=fill)
                self.assertTrue(result is None or result.card != "fireball")

    def test_live_pressure_still_preempts_low_tower_spell(self):
        towers = {"left": False, "right": True}
        fill = {"left": None, "right": 0.10}
        warning = [(305, 390), (300, 380)]
        cards = hand("fireball", "cannon", "musketeer", "log")
        self.strategy.decide(cards, 10, warning, 150, towers, enemy_tower_fill=fill)
        result = self.decision(
            self.strategy.decide(cards, 10, warning, 151, towers, enemy_tower_fill=fill), "musketeer"
        )
        self.assertNotEqual(result.point, (303, 130))

    def test_two_far_labels_reserve_defense_before_uncommitted_hog(self) -> None:
        upcoming = [(289, 204), (319, 220)]  # frozen frame before V5a pilot B1's 51-second loss
        cards = hand("hog", "cannon", "fireball", "log")
        self.assertIsNone(self.strategy.decide(cards, 6, [], 10, far_warnings=upcoming))
        self.assertIsNone(self.strategy.decide(cards, 6, [], 11, far_warnings=upcoming))
        decision = self.decision(self.strategy.decide(cards, 8, [], 12, far_warnings=upcoming), "hog")
        self.assertEqual(decision.elixir - COSTS[decision.card], 4)

    def test_far_warning_prepares_ranged_output_on_observed_lane(self) -> None:
        upcoming = [(289, 204), (319, 220)]
        cards = hand("musketeer", "hog", "cannon", "log")
        self.assertIsNone(self.strategy.decide(cards, 8, [], 10, far_warnings=upcoming))
        decision = self.decision(self.strategy.decide(cards, 8, [], 11, far_warnings=upcoming), "musketeer")
        self.assertEqual(decision.lane, "right")
        self.assertEqual(decision.category, "defense")
        self.assertEqual(decision.point, CN_HOG_MUSKETEER_POINTS["right"])

    def test_far_warning_does_not_cancel_confirmed_ice_golem_hog_pair(self) -> None:
        lead = self.decision(self.strategy.decide(hand("ice_golem", "hog"), 9, [], 10), "ice_golem")
        self.strategy.record(lead, True, 10)
        incoming = [(289, 204), (319, 220)]
        follow = self.decision(self.strategy.decide(hand("hog", "log"), 7, [], 12, far_warnings=incoming), "hog")
        self.assertEqual(follow.point, lead.point)

    def test_one_far_label_blocks_unsafe_hog_until_four_elixir_remains(self) -> None:
        warning = [(324, 210)]  # pilot 06 B4, opposite-lane rush before tower loss
        self.assertIsNone(self.strategy.decide(hand("hog", "cannon", "log"), 6, [], 10, far_warnings=warning))
        decision = self.decision(
            self.strategy.decide(hand("hog", "cannon", "log"), 8, [], 11, far_warnings=warning), "hog"
        )
        self.assertEqual(decision.elixir - COSTS[decision.card], 4)

    def decision(self, value: HogDecision | None, card: str) -> HogDecision:
        self.assertIsNotNone(value)
        assert value is not None
        self.assertEqual(value.card, card)
        return value

    def defend(
        self,
        cards: list[dict],
        enemies: list[tuple[int, int]],
        elixir: int = 10,
        now: float = 20.0,
        threats: list[dict] | None = None,
    ) -> HogDecision | None:
        self.strategy.decide(cards, elixir, enemies, now - 0.5, threats=threats)
        return self.strategy.decide(cards, elixir, enemies, now, threats=threats)

    def test_single_elixir_phase_does_not_attack_below_defense_reserve(self) -> None:
        for elixir in range(6):
            with self.subTest(elixir=elixir):
                self.assertIsNone(self.strategy.decide(hand("hog"), elixir, [], 10.0))

    def test_safe_bridge_hog_preserves_three_in_either_elixir_phase(self) -> None:
        early = self.decision(self.strategy.decide(hand("hog"), 7, [], 10.0), "hog")
        self.assertEqual(early.point, CN_HOG_BRIDGE_POINTS["left"])
        self.assertEqual(early.elixir - COSTS[early.card], 3)
        self.assertIsNone(self.strategy.decide(hand("hog"), 6, [], 130.0))
        late = self.decision(self.strategy.decide(hand("hog"), 7, [], 130.0), "hog")
        self.assertEqual(late.elixir - COSTS[late.card], 3)

    def test_first_unguarded_hog_waits_for_opening_defense_reserve(self) -> None:
        self.assertIsNone(self.strategy.decide(hand("hog"), 7, [], 2.0))
        first = self.decision(self.strategy.decide(hand("hog"), 9, [], 3.0), "hog")
        self.assertEqual(first.elixir - COSTS[first.card], 5)
        self.strategy = HogCycleStrategy(started_at=0.0)
        self.strategy.categories["defense"] = 1
        later = self.decision(self.strategy.decide(hand("hog"), 7, [], 3.0), "hog")
        self.assertEqual(later.elixir - COSTS[later.card], 3)

    def test_unreadable_fourth_opening_card_does_not_trigger_blind_hog(self) -> None:
        cards = hand("musketeer", "hog", "log")
        cards.append({"slot": 3, "card": None, "available": False, "variant": None})
        self.assertIsNone(self.strategy.decide(cards, 10, [], 2.0))

    def test_seven_near_tower_small_markers_use_log_before_fireball(self) -> None:
        # Pilot 08 B3: seven level plaques surrounded the right Princess Tower.
        swarm = [(285, 366), (288, 381), (305, 356), (310, 375), (324, 359), (327, 388), (332, 375)]
        response = self.decision(
            self.defend(
                hand("musketeer", "cannon", "log", "fireball"),
                swarm,
                elixir=6,
            ),
            "log",
        )
        self.assertEqual(response.category, "spell")
        self.assertEqual(response.elixir - COSTS[response.card], 4)

    def test_frozen_deep_king_pressure_uses_ready_fireball_before_cheap_delay(self) -> None:
        # Pilot 08 B10 had 167 King HP, three central enemies and a ready
        # Fireball, but the old rules spent Ice Spirit instead.
        enemies = [(191, 390), (220, 335), (252, 357)]
        cards = hand("ice_spirit", "ice_golem", "fireball", "hog")
        response = self.decision(self.defend(cards, enemies, elixir=4), "fireball")
        self.assertEqual(response.point, (221, 381))
        self.assertIn("国王塔", response.reason)

    def test_real_126_hp_tower_overrides_princess_defense_with_lethal_fireball(self) -> None:
        image = Path(__file__).parent / "fixtures" / "cn_battle_cues" / "low_tower_126.png"
        frame = cv2.imread(str(image))
        assert frame is not None, "Missing test fixture"
        cues = read_cn_battle_cues(frame)
        cards = hand("log", "hog", "musketeer", "fireball")
        response = self.decision(
            self.strategy.decide(
                cards,
                cues["elixir"],
                cues["enemies"],
                10.0,
                enemy_towers=cues["enemy_towers"],
                enemy_tower_fill=cues["enemy_tower_fill"],
                own_tower_fill=cues["own_tower_fill"],
            ),
            "fireball",
        )
        self.assertEqual(response.point, (115, 130))
        self.assertIn("立即收塔", response.reason)

    def test_deep_king_crisis_takes_precedence_over_one_spell_enemy_tower(self) -> None:
        cards = hand("ice_spirit", "ice_golem", "fireball", "hog")
        enemies = [(191, 390), (220, 335), (252, 357)]
        response = self.decision(
            self.strategy.decide(
                cards,
                4,
                enemies,
                10.0,
                enemy_towers={"left": True, "right": True},
                enemy_tower_fill={"left": 0.025, "right": 1.0},
            ),
            "fireball",
        )
        self.assertEqual(response.point, (221, 381))

    def test_three_deep_markers_can_trigger_first_frame_defense(self) -> None:
        # A fast group should not need another screenshot after crossing deep
        # into our side. A recently disappeared old group still uses the
        # separate held-pressure safety check below.
        group = [(86, 359), (114, 367), (128, 354)]
        response = self.decision(
            self.strategy.decide(
                hand("fireball", "cannon"),
                6,
                group,
                1.0,
            ),
            "fireball",
        )
        self.assertEqual(response.pressure_count, 3)

    def test_two_lane_setup_musketeer_is_not_next_to_cannon(self) -> None:
        for point in CN_HOG_CANNON_POINTS.values():
            self.assertGreaterEqual(math.dist(CN_HOG_DUAL_LANE_MUSKETEER_POINT, point), 70)
        self.assertLess(CN_HOG_DUAL_LANE_MUSKETEER_POINT[1], CN_HOG_FRIENDLY_TOWER_BOXES["king"][1])

    def test_real_moving_dark_ground_cue_places_cannon_before_hog(self) -> None:
        # Pilot 11 B9: y228 -> y253 in four seconds; the old policy cycled
        # Ice Spirit and sent a Hog before using the ready Cannon.
        cards = hand("cannon", "hog", "fireball", "log")
        prior = [{"x": 290, "y": 228, "dark_pixels": 583}]
        current = [{"x": 296, "y": 253, "dark_pixels": 704}]
        self.assertIsNone(
            self.strategy.decide(cards, 8, [], 10.0, far_warnings=[(290, 228)], dark_ground_candidates=prior)
        )
        defense = self.decision(
            self.strategy.decide(cards, 8, [], 14.0, far_warnings=[(296, 253)], dark_ground_candidates=current),
            "cannon",
        )
        self.assertEqual(defense.point, CN_HOG_CANNON_POINTS["right"])
        self.assertEqual(defense.threat_kind, "ground_mass")

    def test_static_dark_siege_cue_never_confirms_ground_motion(self) -> None:
        # A frozen siege body can score 459 dark pixels; it must not become a
        # moving ground threat from two stationary screenshots.
        cards = hand("cannon", "hog", "fireball", "log")
        static = [{"x": 309, "y": 254, "dark_pixels": 459}]
        self.assertIsNone(self.strategy.decide(cards, 8, [], 10.0, dark_ground_candidates=static))
        self.assertIsNone(self.strategy.decide(cards, 8, [], 13.0, dark_ground_candidates=static))

    def test_known_air_overrides_dark_body_motion_before_cannon(self) -> None:
        cards = hand("cannon", "hog", "fireball", "log")
        self.strategy.decide(cards, 8, [], 10.0, dark_ground_candidates=[{"x": 117, "y": 224, "dark_pixels": 350}])
        air = threat("air", 117, 253, confidence=0.90)
        air["template_id"] = "air_balloon_envelope"
        self.assertIsNone(
            self.strategy.decide(
                cards,
                8,
                [],
                14.0,
                threats=[air],
                dark_ground_candidates=[{"x": 117, "y": 253, "dark_pixels": 450}],
            )
        )

    def test_frozen_split_push_allocates_cannon_to_uncovered_lane(self) -> None:
        # Pilot 09 B1: right Musketeer already covers three enemies while
        # three more red plaques approach the left bridge.
        right = [(281, 338), (303, 326), (316, 338)]
        left_warning = [(102, 269), (115, 262), (124, 244)]
        cards = hand("cannon", "log", "fireball", "ice_golem")
        self.strategy.last_defense_by_card[("right", "musketeer")] = 10.0
        response = self.decision(self.strategy.decide(cards, 4, right, 12.0, far_warnings=left_warning), "cannon")
        self.assertEqual(response.point, CN_HOG_CANNON_POINTS["left"])
        self.assertEqual(response.lane, "left")
        self.assertEqual(response.category, "defense")

    def test_elite_ice_golem_combo_advances_only_on_confirmed_deployment(self) -> None:
        opening = self.decision(
            self.strategy.decide(hand("hog", "ice_golem"), 9, [], 10.0),
            "ice_golem",
        )
        self.assertEqual(opening.variant, "elite_ice_golem")
        self.assertEqual(opening.point, CN_HOG_BRIDGE_POINTS["left"])
        self.assertEqual(opening.category, "attack")
        self.assertEqual(self.strategy.pending_hog_until, 0.0)
        self.strategy.record(opening, confirmed=True, now=10.0)
        self.assertGreater(self.strategy.pending_hog_until, 12.0)
        follow = self.decision(self.strategy.decide(hand("hog"), 7, [], 12.0), "hog")
        self.assertEqual(follow.point, opening.point)
        self.strategy.record(follow, confirmed=True, now=12.0)
        self.assertEqual(self.strategy.pending_hog_until, 0.0)
        self.assertEqual(self.strategy.categories["attack"], 2)

    def test_failed_deployment_does_not_advance_combo_or_success_counters(self) -> None:
        opening = self.decision(
            self.strategy.decide(hand("hog", "ice_golem"), 9, [], 10.0),
            "ice_golem",
        )
        self.strategy.record(opening, confirmed=False, now=10.0)
        self.assertEqual(self.strategy.pending_hog_until, 0.0)
        self.assertNotIn("ice_golem", self.strategy.last_play)
        self.assertEqual(sum(self.strategy.categories.values()), 0)
        retry = self.decision(
            self.strategy.decide(hand("hog", "ice_golem"), 9, [], 12.0),
            "ice_golem",
        )
        self.assertEqual(retry.category, "attack")

    def test_unknown_unavailable_and_non_deck_cards_never_get_played(self) -> None:
        cards = [
            {"slot": 0, "card": None, "available": True},
            {"slot": 1, "card": "hog", "available": False},
            {"slot": 2, "card": "giant", "available": True},
            {"slot": 3, "card": "musketeer", "available": False},
        ]
        self.assertIsNone(self.strategy.decide(cards, 10, [], 10.0))
        self.assertIsNone(self.defend(cards, [(110, 385)]))

    def test_first_pressure_frame_holds_attack_second_frame_defends(self) -> None:
        cards = hand("hog", "cannon")
        enemies = [(110, 345)]
        self.assertIsNone(self.strategy.decide(cards, 10, enemies, 10.0))
        defense = self.decision(self.strategy.decide(cards, 10, enemies, 10.5), "cannon")
        self.assertEqual(defense.category, "defense")
        self.assertEqual(defense.point, CN_HOG_CANNON_POINTS["left"])

    def test_established_pressure_cancels_pending_hog_combo(self) -> None:
        opening = self.decision(
            self.strategy.decide(hand("hog", "ice_golem"), 9, [], 10.0),
            "ice_golem",
        )
        self.strategy.record(opening, confirmed=True, now=10.0)
        self.assertIsNone(self.defend(hand("hog"), [(110, 380)], now=12.0))
        self.assertEqual(self.strategy.pending_hog_until, 0.0)

    def test_pressure_dropout_requires_a_clear_interval_before_attack(self) -> None:
        self.assertIsNone(self.defend(hand("hog"), [(110, 345)], now=100.5))
        self.assertIsNone(self.strategy.decide(hand("hog"), 10, [], 102.5))
        self.assertIsNone(self.strategy.decide(hand("hog"), 10, [], 103.4))
        self.decision(self.strategy.decide(hand("hog"), 10, [], 103.6), "hog")

    def test_musketeer_covers_deep_pressure_and_cannon_is_central_fallback(self) -> None:
        defense = self.decision(
            self.defend(hand("hog", "musketeer", "cannon"), [(303, 360)]),
            "musketeer",
        )
        self.assertEqual(defense.point, CN_HOG_MUSKETEER_POINTS["right"])
        self.strategy = HogCycleStrategy(started_at=0.0)
        fallback = self.decision(
            self.defend(hand("hog", "cannon"), [(303, 360)]),
            "cannon",
        )
        self.assertEqual(fallback.point, CN_HOG_CANNON_POINTS["right"])

    def test_log_targets_observed_pressure_from_behind(self) -> None:
        enemies = [(300, 330), (310, 345)]
        spell = self.decision(self.defend(hand("log", "hog"), enemies), "log")
        self.assertEqual(spell.category, "spell")
        self.assertGreater(spell.point[0], 209)
        self.assertGreater(spell.point[1], max(y for _, y in enemies))

    def test_fireball_requires_cluster_and_targets_its_center(self) -> None:
        self.assertIsNone(self.defend(hand("fireball"), [(110, 345)]))
        self.strategy = HogCycleStrategy(started_at=0.0)
        cluster = [(110, 345), (120, 350), (130, 360)]
        spell = self.decision(self.defend(hand("fireball"), cluster), "fireball")
        self.assertEqual(spell.point, (120, 362))
        self.assertEqual(spell.category, "spell")

    def test_empty_board_preserves_defense_cores_and_untargeted_spells(self) -> None:
        self.assertIsNone(
            self.strategy.decide(
                hand("cannon", "musketeer", "fireball", "log"),
                9,
                [],
                10.0,
            )
        )
        self.assertIsNone(self.strategy.decide(hand("fireball", "log"), 10, [], 10.0))
        cycle = self.decision(
            self.strategy.decide(
                hand("cannon", "musketeer", "skeletons", "log"),
                8,
                [],
                10.0,
            ),
            "skeletons",
        )
        self.assertEqual(cycle.category, "cycle")
        self.assertEqual(cycle.point, CN_HOG_BACK_POINTS["left"])

    def test_full_elixir_without_cheap_cycle_uses_two_lane_musketeer(self) -> None:
        cycle = self.decision(
            self.strategy.decide(
                hand("cannon", "musketeer", "fireball", "log"),
                10,
                [],
                10.0,
            ),
            "musketeer",
        )
        self.assertEqual(cycle.category, "cycle")
        self.assertEqual(cycle.point, CN_HOG_DUAL_LANE_MUSKETEER_POINT)
        self.assertEqual(cycle.elixir - COSTS[cycle.card], 6)
        cheaper = self.decision(
            self.strategy.decide(
                hand("cannon", "musketeer", "skeletons", "log"),
                10,
                [],
                10.0,
            ),
            "skeletons",
        )
        self.assertEqual(cheaper.category, "cycle")

    def test_attempt_interval_applies_to_success_and_failure(self) -> None:
        for confirmed in (True, False):
            with self.subTest(confirmed=confirmed):
                self.strategy = HogCycleStrategy(started_at=0.0)
                move = self.decision(self.strategy.decide(hand("hog"), 7, [], 10.0), "hog")
                self.strategy.record(move, confirmed=confirmed, now=10.0)
                self.assertIsNone(self.strategy.decide(hand("skeletons"), 10, [], 11.0))
                self.decision(self.strategy.decide(hand("skeletons"), 10, [], 12.0), "skeletons")

    def test_confirmed_hog_cannot_be_immediately_replayed(self) -> None:
        hog = self.decision(self.strategy.decide(hand("hog"), 7, [], 10.0), "hog")
        self.strategy.record(hog, confirmed=True, now=10.0)
        self.assertIsNone(self.strategy.decide(hand("hog"), 10, [], 12.0))
        self.decision(self.strategy.decide(hand("hog"), 7, [], 17.0), "hog")

    def test_ice_spirit_support_is_once_per_confirmed_hog(self) -> None:
        hog = self.decision(self.strategy.decide(hand("hog"), 7, [], 10.0), "hog")
        self.strategy.record(hog, confirmed=True, now=10.0)
        spirit = self.decision(self.strategy.decide(hand("ice_spirit"), 4, [], 12.0), "ice_spirit")
        self.assertEqual(spirit.point, CN_HOG_SUPPORT_POINTS["left"])
        self.assertEqual(spirit.category, "attack")
        self.strategy.record(spirit, confirmed=False, now=12.0)
        spirit = self.decision(self.strategy.decide(hand("ice_spirit"), 4, [], 14.0), "ice_spirit")
        self.strategy.record(spirit, confirmed=True, now=14.0)
        self.assertIsNone(self.strategy.decide(hand("ice_spirit"), 4, [], 16.0))

    def test_decisions_always_use_available_affordable_known_cards(self) -> None:
        decks = [
            hand("hog", "ice_golem", "ice_spirit", "skeletons"),
            hand("fireball", "log", "musketeer", "cannon"),
        ]
        for cards in decks:
            for elixir in range(11):
                for enemies in ([], [(110, 360), (120, 380), (130, 375)]):
                    with self.subTest(cards=cards, elixir=elixir, enemies=enemies):
                        self.strategy = HogCycleStrategy(started_at=0.0)
                        value = self.defend(cards, enemies, elixir=elixir)
                        if value is not None:
                            self.assertLessEqual(COSTS[value.card], elixir)
                            self.assertEqual(cards[value.slot]["card"], value.card)
                            self.assertTrue(cards[value.slot]["available"])

    def test_unreadable_or_invalid_elixir_does_not_spend(self) -> None:
        for elixir in (None, -1, 11):
            with self.subTest(elixir=elixir):
                self.assertIsNone(self.strategy.decide(hand("hog"), elixir, [], 10.0))

    def test_right_river_warning_does_not_trigger_defense_and_opening_hog_waits(self) -> None:
        for now in (1.0, 2.0):
            self.assertIsNone(self.strategy.decide(hand("hog", "cannon"), 7, [(300, 250)], now))
        self.decision(self.strategy.decide(hand("hog", "cannon"), 7, [(300, 250)], 11.0), "hog")

    def test_low_elixir_single_unknown_threat_preserves_general_damage(self) -> None:
        decision = self.decision(self.defend(hand("log", "musketeer", "hog"), [(300, 400)], elixir=4), "musketeer")
        self.assertEqual(decision.category, "defense")

    def test_recent_confirmed_core_uses_one_cost_delay_instead_of_another_core(self) -> None:
        first = self.decision(self.defend(hand("musketeer"), [(110, 330)], now=10.0), "musketeer")
        self.strategy.record(first, confirmed=True, now=10.0)
        follow = self.decision(
            self.defend(
                hand("cannon", "ice_spirit", "log"),
                [(110, 335)],
                elixir=5,
                now=13.0,
            ),
            "ice_spirit",
        )
        self.assertEqual(follow.category, "defense")
        self.assertEqual(follow.lane, "left")
        self.assertEqual((follow.pressure_count, follow.pressure_depth), (1, 335))

    def test_normal_pressure_can_pair_cannon_and_musketeer_but_not_repeat_them(self) -> None:
        # Candidate B5 demonstrated that the old four-elixir cap blocked the
        # complementary Musketeer after a Cannon. Keep a bounded pair instead.
        first = self.decision(self.defend(hand("musketeer"), [(110, 330)], now=10.0), "musketeer")
        self.strategy.record(first, confirmed=True, now=10.0)
        self.assertIsNone(self.defend(hand("cannon", "log"), [(110, 335)], elixir=5, now=13.0))
        second = self.decision(self.defend(hand("cannon"), [(110, 335)], elixir=5, now=15.0), "cannon")
        self.strategy.record(second, confirmed=True, now=15.0)
        self.assertEqual(sum(cost for _, _, cost in self.strategy.core_spending), 7)
        self.assertIsNone(self.defend(hand("cannon", "musketeer"), [(110, 335)], now=20.0))
        self.decision(self.defend(hand("musketeer"), [(110, 335)], now=22.5), "musketeer")

    def test_failed_core_does_not_delay_the_next_defense(self) -> None:
        first = self.decision(self.defend(hand("musketeer"), [(110, 330)], now=10.0), "musketeer")
        self.strategy.record(first, confirmed=False, now=10.0)
        self.assertEqual(self.strategy.last_core_defense, {})
        self.decision(self.defend(hand("cannon"), [(110, 335)], elixir=5, now=13.0), "cannon")

    def test_pressure_deepening_or_two_extra_markers_breaks_core_wait(self) -> None:
        for enemies in ([(150, 375)], [(110, 332), (120, 335), (130, 337)]):
            with self.subTest(enemies=enemies):
                self.strategy = HogCycleStrategy(started_at=0.0)
                first = self.decision(self.defend(hand("musketeer"), [(110, 330)], now=10.0), "musketeer")
                self.strategy.record(first, confirmed=True, now=10.0)
                self.decision(self.defend(hand("cannon", "ice_spirit"), enemies, now=13.0), "cannon")

    def test_uncovered_opposite_urgent_lane_gets_defense_before_recently_covered_lane(self) -> None:
        first = self.decision(
            self.defend(
                hand("musketeer"),
                [(110, 330), (120, 332), (130, 334)],
                now=10.0,
            ),
            "musketeer",
        )
        self.strategy.record(first, confirmed=True, now=10.0)
        # Three shallow left markers outweigh one deep right marker, but the
        # right lane has received no defense and must not wait for the left.
        enemies = [(110, 332), (120, 335), (130, 337), (280, 380)]
        follow = self.decision(self.defend(hand("cannon", "ice_spirit"), enemies, now=13.0), "cannon")
        self.assertEqual(follow.lane, "right")
        self.assertEqual(follow.point, CN_HOG_CANNON_POINTS["right"])

    def test_sharply_deeper_primary_lane_is_not_overridden_by_opposite_lane(self) -> None:
        first = self.decision(self.defend(hand("musketeer"), [(110, 330)], now=10.0), "musketeer")
        self.strategy.record(first, confirmed=True, now=10.0)
        follow = self.decision(
            self.defend(
                hand("ice_spirit", "cannon"),
                [(110, 440), (300, 380)],
                now=13.0,
            ),
            "ice_spirit",
        )
        self.assertEqual(follow.lane, "left")
        self.assertGreaterEqual(follow.point[1], 440)
        self.assertLessEqual(math.dist(follow.point, (110, 440)), 30)

    def test_defense_core_back_in_hand_is_available_after_short_cooldown(self) -> None:
        for card in ("cannon", "musketeer"):
            with self.subTest(card=card):
                self.strategy = HogCycleStrategy(started_at=0.0)
                self.strategy.last_play[card] = 5.0
                self.assertIsNone(self.defend(hand(card), [(110, 330)], now=8.0))
                self.decision(self.defend(hand(card), [(110, 330)], now=10.0), card)

    def test_close_dense_pressure_prioritizes_affordable_fireball_over_core(self) -> None:
        for elixir, y in ((6, 365), (4, 410)):
            with self.subTest(elixir=elixir, y=y):
                self.strategy = HogCycleStrategy(started_at=0.0)
                enemies = [(110, y), (120, y + 3), (130, y + 5)]
                spell = self.decision(
                    self.defend(
                        hand("fireball", "musketeer", "cannon", "log"),
                        enemies,
                        elixir=elixir,
                    ),
                    "fireball",
                )
                self.assertEqual(spell.category, "spell")

    def test_close_cluster_never_spends_unaffordable_or_unavailable_fireball(self) -> None:
        enemies = [(110, 410), (120, 415), (130, 412)]
        self.assertIsNone(self.defend(hand("fireball"), enemies, elixir=3))
        self.strategy = HogCycleStrategy(started_at=0.0)
        cards = hand("fireball", "ice_spirit")
        cards[0]["available"] = False
        self.decision(self.defend(cards, enemies, elixir=8), "ice_spirit")

    def test_five_elixir_moderate_cluster_still_keeps_general_damage(self) -> None:
        self.decision(
            self.defend(
                hand("fireball", "musketeer"),
                [(110, 360), (120, 365), (130, 362)],
                elixir=5,
            ),
            "musketeer",
        )

    def test_single_deep_marker_does_not_promote_a_distant_cluster_to_urgent_fireball(self) -> None:
        self.decision(
            self.defend(
                hand("fireball", "musketeer"),
                [(110, 300), (120, 302), (130, 305), (110, 420)],
            ),
            "musketeer",
        )

    def test_single_urgent_log_does_not_preempt_one_cost_delay(self) -> None:
        for cheap in ("ice_spirit", "skeletons"):
            with self.subTest(cheap=cheap):
                self.strategy = HogCycleStrategy(started_at=0.0)
                self.decision(self.defend(hand("log", cheap), [(110, 410)], elixir=3), cheap)
        self.strategy = HogCycleStrategy(started_at=0.0)
        self.decision(self.defend(hand("log"), [(110, 410)], elixir=3), "log")

    def test_deep_pressure_uses_deep_positions_and_does_not_place_high_cannon(self) -> None:
        positions = {"musketeer": CN_HOG_DEEP_MUSKETEER_POINTS, "ice_golem": CN_HOG_DEEP_KITE_POINTS}
        for lane, x in (("left", 110), ("right", 300)):
            for card, points in positions.items():
                with self.subTest(lane=lane, card=card):
                    self.strategy = HogCycleStrategy(started_at=0.0)
                    move = self.decision(self.defend(hand(card, "cannon"), [(x, 420)]), card)
                    self.assertEqual(move.point, points[lane])
            for card in ("ice_spirit", "skeletons"):
                self.strategy = HogCycleStrategy(started_at=0.0)
                move = self.decision(self.defend(hand(card, "cannon"), [(x, 420)]), card)
                self.assertGreater(move.point[1], 420)
                self.assertLessEqual(math.dist(move.point, (x, 420)), 30)
        self.strategy = HogCycleStrategy(started_at=0.0)
        self.assertIsNone(self.defend(hand("cannon", "hog"), [(110, 420)]))

    def test_six_elixir_cycles_cheap_card_only_when_hog_not_ready(self) -> None:
        self.decision(self.strategy.decide(hand("skeletons", "cannon"), 6, [], 10.0), "skeletons")
        self.assertIsNone(self.strategy.decide(hand("hog", "skeletons"), 6, [], 10.0))
        self.decision(self.strategy.decide(hand("hog", "skeletons"), 7, [], 10.0), "hog")

    def test_elite_ice_golem_does_not_back_cycle_below_exact_lock_reserve(self) -> None:
        self.assertIsNone(
            self.strategy.decide(
                hand("cannon", "ice_golem", "fireball", "log"),
                5,
                [],
                10.0,
            )
        )
        cycle = self.decision(
            self.strategy.decide(
                hand("cannon", "ice_golem", "skeletons", "log"),
                8,
                [],
                12.0,
            ),
            "skeletons",
        )
        self.assertEqual(cycle.category, "cycle")

    def test_full_elixir_without_hog_keeps_musketeer_for_opposite_lane(self) -> None:
        lead = self.decision(
            self.strategy.decide(
                hand("ice_golem", "musketeer", "cannon", "log"),
                10,
                [],
                10.0,
            ),
            "ice_golem",
        )
        self.assertEqual(lead.category, "cycle")
        self.assertEqual(lead.point, CN_HOG_BACK_POINTS["left"])
        self.strategy.record(lead, confirmed=True, now=10.0)
        self.assertEqual(self.strategy.pending_hog_until, 0.0)

    def test_full_elixir_unlocks_hand_when_hog_is_cooling_down(self) -> None:
        hog = self.decision(self.strategy.decide(hand("hog"), 7, [], 10.0), "hog")
        self.strategy.record(hog, confirmed=True, now=10.0)
        # Hog is in hand but still on its 6s cooldown; full elixir must not idle.
        unlock = self.decision(
            self.strategy.decide(
                hand("hog", "musketeer", "cannon", "log"),
                10,
                [],
                12.0,
            ),
            "musketeer",
        )
        self.assertEqual(unlock.category, "cycle")

    def test_night_battle10_river_markers_do_not_cancel_confirmed_golem_hog(self) -> None:
        # Night trace 01:25:28 -> 01:25:31: these four markers caused a
        # defensive Musketeer to replace the promised Hog in the previous policy.
        opening = self.decision(
            self.strategy.decide(
                hand("fireball", "log", "hog", "ice_golem"),
                10,
                [],
                10.0,
            ),
            "ice_golem",
        )
        self.strategy.record(opening, confirmed=True, now=10.0)
        markers = [(97, 279), (98, 249), (99, 266), (114, 256)]
        follow = self.decision(
            self.defend(
                hand("fireball", "log", "hog", "musketeer"),
                markers,
                elixir=9,
                now=13.0,
            ),
            "hog",
        )
        self.assertEqual(follow.category, "attack")
        self.assertGreater(self.strategy.pending_hog_until, 13.0)

    def test_river_warning_cluster_never_spends_untargeted_defensive_fireball(self) -> None:
        self.assertIsNone(
            self.defend(
                hand("fireball", "log", "cannon"),
                [(97, 279), (98, 249), (99, 266), (114, 256)],
            )
        )

    def test_night_battle2_two_river_markers_do_not_turn_one_shallow_unit_into_a_group(self) -> None:
        # Night trace 01:01:33: one actual right-lane marker at y308 plus
        # river warnings at y275 and y255 consumed the first defensive 4 elixir.
        response = self.decision(
            self.defend(
                hand("hog", "ice_golem", "skeletons", "musketeer"),
                [(110, 275), (277, 308), (293, 255)],
                elixir=7,
                now=20.0,
            ),
            "musketeer",
        )
        self.assertEqual(response.elixir - COSTS[response.card], 3)
        self.assertEqual(response.pressure_count, 1)

    def test_unknown_single_shallow_pressure_does_not_authorize_hog_without_output(self) -> None:
        self.assertIsNone(self.defend(hand("hog"), [(277, 308)], elixir=6))
        self.assertIsNone(self.defend(hand("hog"), [(277, 308)], elixir=7))

    def test_confirmed_core_allows_small_push_counter_hog_with_two_reserve(self) -> None:
        core = self.decision(self.defend(hand("musketeer"), [(110, 345)], now=10.0), "musketeer")
        self.strategy.record(core, confirmed=True, now=10.0)
        response = self.decision(
            self.defend(
                hand("hog", "cannon", "skeletons"),
                [(110, 345), (120, 350)],
                elixir=6,
                now=13.0,
            ),
            "hog",
        )
        self.assertEqual(response.elixir - COSTS[response.card], 2)

    def test_failed_core_does_not_authorize_six_elixir_counterattack(self) -> None:
        core = self.decision(self.defend(hand("musketeer"), [(110, 345)], now=10.0), "musketeer")
        self.strategy.record(core, confirmed=False, now=10.0)
        self.assertIsNone(self.defend(hand("hog"), [(110, 345)], elixir=6, now=13.0))

    def test_urgent_other_lane_still_blocks_hog_and_gets_deep_defense(self) -> None:
        core = self.decision(self.defend(hand("musketeer"), [(110, 320)], now=10.0), "musketeer")
        self.strategy.record(core, confirmed=True, now=10.0)
        enemies = [(100, 320), (110, 325), (120, 330), (130, 332), (300, 415)]
        response = self.decision(
            self.defend(
                hand("hog", "skeletons", "cannon"),
                enemies,
                elixir=8,
                now=13.0,
            ),
            "skeletons",
        )
        self.assertEqual(response.lane, "right")
        self.assertGreater(response.point[1], 415)
        self.assertLessEqual(math.dist(response.point, (300, 415)), 30)

    def test_escalated_wave_has_finite_core_budget(self) -> None:
        first = self.decision(self.defend(hand("musketeer"), [(110, 330)], now=10.0), "musketeer")
        self.strategy.record(first, confirmed=True, now=10.0)
        second = self.decision(self.defend(hand("cannon"), [(150, 380)], now=13.0), "cannon")
        self.strategy.record(second, confirmed=True, now=13.0)
        # Seven confirmed core elixir in the window; another four-elixir
        # core cannot be spent just because its short replay cooldown expired.
        self.assertIsNone(self.defend(hand("musketeer"), [(110, 390)], now=18.0))
        self.assertEqual(sum(cost for _, _, cost in self.strategy.core_spending), 7)

    def test_uncertain_or_failed_defense_does_not_consume_core_budget(self) -> None:
        first = self.decision(self.defend(hand("musketeer"), [(110, 340)], now=10.0), "musketeer")
        self.strategy.record(first, confirmed=False, now=10.0)
        self.assertEqual(self.strategy.core_spending, [])
        self.decision(self.defend(hand("musketeer"), [(110, 340)], now=13.0), "musketeer")

    def test_without_output_only_one_cheap_delay_then_save_for_core(self) -> None:
        delay = self.decision(
            self.defend(
                hand("ice_spirit", "skeletons", "ice_golem"),
                [(110, 345)],
                elixir=2,
                now=10.0,
            ),
            "ice_spirit",
        )
        self.strategy.record(delay, confirmed=True, now=10.0)
        self.assertIsNone(
            self.defend(
                hand("skeletons", "ice_golem"),
                [(110, 347)],
                elixir=2,
                now=13.0,
            )
        )
        self.decision(
            self.defend(
                hand("skeletons", "cannon"),
                [(110, 347)],
                elixir=3,
                now=14.0,
            ),
            "cannon",
        )

    def test_failed_cheap_delay_can_retry_and_new_deep_pressure_can_override(self) -> None:
        delay = self.decision(self.defend(hand("ice_spirit"), [(110, 345)], elixir=2, now=10.0), "ice_spirit")
        self.strategy.record(delay, confirmed=False, now=10.0)
        retry = self.decision(self.defend(hand("skeletons"), [(110, 345)], elixir=2, now=13.0), "skeletons")
        self.strategy.record(retry, confirmed=True, now=13.0)
        self.decision(self.defend(hand("ice_spirit"), [(110, 405)], elixir=2, now=16.0), "ice_spirit")

    def test_disappeared_pressure_never_spends_against_stale_target(self) -> None:
        self.defend(hand("hog"), [(110, 345)], now=10.0)
        self.assertIsNone(self.strategy.decide(hand("musketeer", "cannon", "ice_spirit"), 10, [], 11.0))
        self.decision(self.strategy.decide(hand("hog"), 7, [], 13.1), "hog")

    def test_safe_four_elixir_cycles_one_cost_but_preserves_three(self) -> None:
        self.assertIsNone(self.strategy.decide(hand("skeletons"), 3, [], 10.0))
        cycle = self.decision(self.strategy.decide(hand("skeletons"), 4, [], 10.0), "skeletons")
        self.assertEqual(cycle.elixir - COSTS[cycle.card], 3)
        self.assertEqual(cycle.category, "cycle")

    def test_observed_four_card_lock_back_golem_escape_keeps_four_elixir(self) -> None:
        cards = hand("log", "cannon", "fireball", "ice_golem")
        self.assertIsNone(self.strategy.decide(cards, 5, [], 10.0))
        escape = self.decision(self.strategy.decide(cards, 6, [], 11.0), "ice_golem")
        self.assertEqual(escape.elixir - COSTS[escape.card], 4)
        self.assertEqual(escape.point, CN_HOG_BACK_POINTS["left"])
        self.assertEqual(escape.category, "cycle")
        self.strategy.record(escape, confirmed=True, now=11.0)
        self.assertEqual(self.strategy.pending_hog_until, 0.0)

    def test_unknown_hand_does_not_speculatively_bridge_invest_golem(self) -> None:
        self.assertIsNone(self.strategy.decide(hand("ice_golem", "fireball", "log"), 10, [], 10.0))

    def test_exact_lock_escape_never_overrides_live_defense(self) -> None:
        response = self.decision(
            self.defend(
                hand("log", "cannon", "fireball", "ice_golem"),
                [(300, 340)],
                elixir=6,
            ),
            "cannon",
        )
        self.assertEqual(response.category, "defense")

    def test_local_air_prefers_musketeer_over_cannon_and_log(self) -> None:
        response = self.decision(
            self.defend(
                hand("log", "cannon", "musketeer", "ice_spirit"),
                [(110, 360)],
                threats=[threat("air", 110, 360)],
            ),
            "musketeer",
        )
        self.assertEqual(response.threat_kind, "air")

    def test_air_without_affordable_output_uses_spirit_not_ground_cards(self) -> None:
        response = self.decision(
            self.defend(
                hand("log", "cannon", "ice_spirit", "skeletons"),
                [(110, 360)],
                elixir=3,
                threats=[threat("air", 110, 360)],
            ),
            "ice_spirit",
        )
        self.assertEqual(response.category, "defense")
        self.strategy = HogCycleStrategy(started_at=0.0)
        self.assertIsNone(
            self.defend(
                hand("log", "cannon", "ice_golem", "skeletons"),
                [(110, 410)],
                elixir=3,
                threats=[threat("air", 110, 410)],
            )
        )

    def test_air_fallback_respects_affordability_and_unavailable_musketeer(self) -> None:
        cards = hand("musketeer", "fireball", "cannon", "log")
        cards[0]["available"] = False
        self.decision(self.defend(cards, [(110, 410)], elixir=4, threats=[threat("air", 110, 410)]), "fireball")
        self.strategy = HogCycleStrategy(started_at=0.0)
        self.assertIsNone(self.defend(cards, [(110, 410)], elixir=3, threats=[threat("air", 110, 410)]))

    def test_nonurgent_single_air_does_not_spend_untargeted_fireball(self) -> None:
        self.assertIsNone(
            self.defend(
                hand("fireball", "cannon", "log"),
                [(110, 345)],
                elixir=8,
                threats=[threat("air", 110, 345)],
            )
        )

    def test_dense_air_without_musketeer_can_use_observed_cluster_fireball(self) -> None:
        response = self.decision(
            self.defend(
                hand("fireball", "cannon", "log"),
                [(110, 340), (120, 345)],
                elixir=4,
                threats=[threat("air", 110, 340)],
            ),
            "fireball",
        )
        self.assertEqual(response.point[0], 115)

    def test_other_lane_air_does_not_disable_ground_response(self) -> None:
        response = self.decision(
            self.defend(
                hand("log", "cannon"),
                [(110, 345), (120, 350), (300, 320)],
                threats=[threat("air", 300, 320)],
            ),
            "log",
        )
        self.assertEqual(response.lane, "left")
        self.assertIsNone(response.threat_kind)

    def test_far_same_lane_air_does_not_override_near_rush(self) -> None:
        response = self.decision(
            self.defend(
                hand("musketeer", "cannon", "log"),
                [(150, 310), (150, 385)],
                threats=[threat("air", 150, 310), threat("rush", 150, 385)],
            ),
            "cannon",
        )
        self.assertEqual(response.threat_kind, "rush")

    def test_invalid_weak_or_unassociated_classifications_keep_unknown_behavior(self) -> None:
        cases = [
            None,
            [],
            [threat("air", 110, 350, 0.879)],
            [threat("air", 110, 350, 1.1)],
            [threat("air", 110, 350, float("nan"))],
            [threat("air", 151, 350)],
            [threat("air", 300, 350)],
            [threat("unknown", 110, 350)],
            [{"kind": "air", "confidence": 0.99, "x": None, "y": 350}],
        ]
        for threats in cases:
            with self.subTest(threats=threats):
                self.strategy = HogCycleStrategy(started_at=0.0)
                response = self.decision(
                    self.defend(
                        hand("cannon", "log"),
                        [(110, 350)],
                        threats=threats,
                    ),
                    "cannon",
                )
                self.assertIsNone(response.threat_kind)

    def test_validated_skeleton_barrel_template_accepts_its_specific_operating_point(self) -> None:
        evidence = threat("air", 110, 350, 0.745)
        evidence["template_id"] = "air_skeleton_barrel_top"
        response = self.decision(
            self.defend(
                hand("musketeer", "cannon", "log"),
                [(110, 350)],
                threats=[evidence],
            ),
            "musketeer",
        )
        self.assertEqual(response.threat_kind, "air")

    def test_skeleton_barrel_exception_rejects_lower_score_or_wrong_identity(self) -> None:
        cases = [
            ("air", "air_skeleton_barrel_top", 0.73),
            ("air", "unvalidated_air_template", 0.745),
            ("air", None, 0.745),
            ("rush", "air_skeleton_barrel_top", 0.745),
            ("swarm", "air_skeleton_barrel_top", 0.745),
        ]
        for kind, template_id, confidence in cases:
            with self.subTest(kind=kind, template_id=template_id, confidence=confidence):
                self.strategy = HogCycleStrategy(started_at=0.0)
                evidence = threat(kind, 110, 350, confidence)
                evidence["template_id"] = template_id
                evidence["threshold"] = 0.01  # callers cannot lower policy gates
                response = self.decision(
                    self.defend(
                        hand("cannon", "log"),
                        [(110, 350)],
                        threats=[evidence],
                    ),
                    "cannon",
                )
                self.assertIsNone(response.threat_kind)

    def test_known_threat_without_actual_marker_never_causes_a_defensive_click(self) -> None:
        self.assertIsNone(self.defend(hand("cannon", "log", "fireball"), [], threats=[threat("rush", 110, 350)]))

    def test_mixed_nearby_air_and_ground_prefers_general_damage(self) -> None:
        for ground in ("rush", "swarm"):
            with self.subTest(ground=ground):
                self.strategy = HogCycleStrategy(started_at=0.0)
                response = self.decision(
                    self.defend(
                        hand("musketeer", "cannon", "log"),
                        [(110, 350), (120, 360)],
                        threats=[threat("air", 110, 350), threat(ground, 120, 360)],
                    ),
                    "musketeer",
                )
                self.assertEqual(response.threat_kind, f"air+{ground}")

    def test_mixed_air_does_not_forbid_proven_ground_response_without_musketeer(self) -> None:
        self.decision(
            self.defend(
                hand("cannon", "log"),
                [(110, 350), (120, 360)],
                elixir=3,
                threats=[threat("air", 110, 350), threat("rush", 120, 360)],
            ),
            "cannon",
        )
        self.strategy = HogCycleStrategy(started_at=0.0)
        self.decision(
            self.defend(
                hand("cannon", "log"),
                [(110, 350), (120, 360)],
                elixir=3,
                threats=[threat("air", 110, 350), threat("swarm", 120, 360)],
            ),
            "log",
        )

    def test_ground_swarm_uses_log_before_four_elixir_cards(self) -> None:
        self.decision(
            self.defend(
                hand("musketeer", "fireball", "log", "skeletons"),
                [(110, 360), (120, 365), (125, 370)],
                threats=[threat("swarm", 120, 365)],
            ),
            "log",
        )
        self.strategy = HogCycleStrategy(started_at=0.0)
        self.decision(
            self.defend(
                hand("musketeer", "fireball", "log", "skeletons"),
                [(110, 340)],
                elixir=2,
                threats=[threat("swarm", 110, 340)],
            ),
            "log",
        )

    def test_ground_swarm_fireball_is_fallback_for_unavailable_log(self) -> None:
        cards = hand("musketeer", "fireball", "log", "skeletons")
        cards[2]["available"] = False
        self.decision(
            self.defend(cards, [(110, 360), (120, 365)], elixir=4, threats=[threat("swarm", 120, 365)]), "fireball"
        )

    def test_rush_uses_first_lane_cannon_despite_another_lane_core(self) -> None:
        core = self.decision(self.defend(hand("musketeer"), [(110, 340)], now=10.0), "musketeer")
        self.strategy.record(core, confirmed=True, now=10.0)
        response = self.decision(
            self.defend(
                hand("cannon", "musketeer", "skeletons"),
                [(300, 350)],
                now=13.0,
                threats=[threat("rush", 300, 350)],
            ),
            "cannon",
        )
        self.assertEqual(response.point, CN_HOG_CANNON_POINTS["right"])

    def test_first_rush_cannon_is_not_blocked_by_old_same_lane_output_budget(self) -> None:
        first = self.decision(self.defend(hand("musketeer"), [(110, 330)], now=10.0), "musketeer")
        self.strategy.record(first, confirmed=True, now=10.0)
        second = self.decision(self.defend(hand("musketeer"), [(110, 380)], now=15.0), "musketeer")
        self.strategy.record(second, confirmed=True, now=15.0)
        response = self.decision(
            self.defend(
                hand("cannon", "skeletons"),
                [(110, 360)],
                now=18.0,
                threats=[threat("rush", 110, 360)],
            ),
            "cannon",
        )
        self.assertEqual(response.threat_kind, "rush")

    def test_air_first_effective_output_is_not_blocked_by_previous_cannon(self) -> None:
        core = self.decision(self.defend(hand("cannon"), [(110, 330)], now=10.0), "cannon")
        self.strategy.record(core, confirmed=True, now=10.0)
        self.decision(
            self.defend(
                hand("musketeer", "log"),
                [(110, 340)],
                now=13.0,
                threats=[threat("air", 110, 340)],
            ),
            "musketeer",
        )

    def test_rush_without_cannon_uses_cheap_ground_delay_and_never_high_cannon_for_deep_threat(self) -> None:
        self.decision(
            self.defend(
                hand("ice_golem", "skeletons", "ice_spirit"),
                [(110, 350)],
                elixir=3,
                threats=[threat("rush", 110, 350)],
            ),
            "skeletons",
        )
        self.strategy = HogCycleStrategy(started_at=0.0)
        response = self.decision(
            self.defend(
                hand("cannon", "skeletons"),
                [(110, 420)],
                threats=[threat("rush", 110, 420)],
            ),
            "skeletons",
        )
        self.assertGreater(response.point[1], 420)
        self.assertLessEqual(math.dist(response.point, (110, 420)), 30)

    def test_building_targeting_rush_without_cannon_uses_musketeer_not_ice_golem(self) -> None:
        self.decision(
            self.defend(
                hand("ice_golem", "musketeer"),
                [(110, 360)],
                elixir=4,
                threats=[threat("rush", 110, 360)],
            ),
            "musketeer",
        )
        self.strategy = HogCycleStrategy(started_at=0.0)
        self.assertIsNone(
            self.defend(
                hand("ice_golem"),
                [(110, 420)],
                elixir=4,
                threats=[threat("rush", 110, 420)],
            )
        )

    def test_confirmed_air_or_rush_near_bridge_is_defended_before_y300(self) -> None:
        for kind, card in (("air", "musketeer"), ("rush", "cannon")):
            with self.subTest(kind=kind):
                self.strategy = HogCycleStrategy(started_at=0.0)
                response = self.decision(
                    self.defend(
                        hand("hog", "musketeer", "cannon"),
                        [(110, 285)],
                        threats=[threat(kind, 110, 285)],
                    ),
                    card,
                )
                self.assertEqual(response.threat_kind, kind)

    def test_low_confidence_river_label_does_not_restore_old_combo_cancellation(self) -> None:
        opening = self.decision(self.strategy.decide(hand("hog", "ice_golem"), 9, [], 10.0), "ice_golem")
        self.strategy.record(opening, confirmed=True, now=10.0)
        self.decision(
            self.defend(
                hand("hog", "musketeer"),
                [(97, 279), (98, 249), (99, 266), (114, 256)],
                now=13.0,
                threats=[threat("air", 97, 279, 0.85)],
            ),
            "hog",
        )

    def test_first_v31_match_central_pressure_uses_central_musketeer(self) -> None:
        # 12:29:39: points at x201/y308 and x228/y309 differed by one
        # pixel in the weight calculation; v3.1 put the Musketeer at x348.
        response = self.decision(
            self.defend(
                hand("musketeer", "cannon", "ice_golem", "hog"),
                [(106, 292), (196, 285), (201, 308), (222, 275), (228, 309), (241, 291)],
                elixir=5,
            ),
            "musketeer",
        )
        self.assertEqual(response.lane, "right")
        self.assertEqual(response.point, CN_HOG_CENTRAL_MUSKETEER_POINTS["right"])

    def test_central_placement_boundary_and_deep_override(self) -> None:
        for x, expected in (
            (165, CN_HOG_MUSKETEER_POINTS["left"]),
            (166, CN_HOG_CENTRAL_MUSKETEER_POINTS["left"]),
            (253, CN_HOG_CENTRAL_MUSKETEER_POINTS["right"]),
            (254, CN_HOG_MUSKETEER_POINTS["right"]),
        ):
            with self.subTest(x=x):
                self.strategy = HogCycleStrategy(started_at=0.0)
                response = self.decision(self.defend(hand("musketeer"), [(x, 350)]), "musketeer")
                self.assertEqual(response.point, expected)
        self.strategy = HogCycleStrategy(started_at=0.0)
        response = self.decision(self.defend(hand("musketeer"), [(228, 420)]), "musketeer")
        self.assertEqual(response.point, CN_HOG_DEEP_MUSKETEER_POINTS["right"])

    def test_first_v31_match_large_bridge_cluster_gets_fireball_before_single_target_core(self) -> None:
        # 12:29:15 actual five own-half markers, with Fireball ready and
        # no Log. Across-river labels must not inflate this group.
        enemies = [
            (92, 309),
            (94, 290),
            (104, 301),
            (108, 263),
            (109, 313),
            (111, 277),
            (120, 294),
            (122, 307),
            (125, 269),
            (126, 282),
            (138, 306),
            (141, 293),
            (292, 278),
        ]
        response = self.decision(
            self.defend(
                hand("ice_golem", "musketeer", "fireball", "cannon"),
                enemies,
                elixir=8,
            ),
            "fireball",
        )
        self.assertEqual(response.lane, "left")
        self.assertEqual(response.pressure_count, 5)
        # V5 includes observed bridge-side support within the same spell area,
        # rather than discarding it solely because its plaque is above y300.
        self.assertEqual(response.point, (116, 302))

    def test_large_unknown_group_prefers_air_capable_fireball_over_blind_log(self) -> None:
        enemies = [(100, 332), (110, 335), (120, 330), (125, 333), (130, 337)]
        self.decision(self.defend(hand("log", "musketeer", "fireball"), enemies, elixir=5), "fireball")

    def test_confirmed_ground_swarm_still_uses_log_before_fireball_for_large_group(self) -> None:
        enemies = [(100, 332), (110, 335), (120, 330), (125, 333), (130, 337)]
        self.decision(
            self.defend(
                hand("log", "musketeer", "fireball"),
                enemies,
                elixir=5,
                threats=[threat("swarm", 130, 337)],
            ),
            "log",
        )

    def test_less_than_five_or_only_river_warnings_keep_existing_fireball_restraint(self) -> None:
        self.decision(
            self.defend(
                hand("musketeer", "fireball"),
                [(100, 332), (110, 335), (120, 330), (130, 337)],
                elixir=5,
            ),
            "musketeer",
        )
        self.strategy = HogCycleStrategy(started_at=0.0)
        self.assertIsNone(
            self.defend(
                hand("fireball", "log", "cannon"),
                [(100, 270), (110, 275), (120, 280), (125, 277), (130, 285)],
                elixir=8,
            )
        )

    def test_large_cluster_fireball_still_requires_available_affordable_card(self) -> None:
        enemies = [(100, 332), (110, 335), (120, 330), (125, 333), (130, 337)]
        self.assertIsNone(self.defend(hand("fireball"), enemies, elixir=3))
        self.strategy = HogCycleStrategy(started_at=0.0)
        cards = hand("fireball", "musketeer")
        cards[0]["available"] = False
        self.decision(self.defend(cards, enemies, elixir=8), "musketeer")

    def test_specific_royal_giant_template_promotes_early_siege_pressure(self) -> None:
        evidence = threat("rush", 292, 258)
        evidence["template_id"] = "rush_royal_giant_head"
        response = self.decision(
            self.defend(
                hand("cannon", "musketeer", "fireball"),
                [(292, 258)],
                threats=[evidence],
            ),
            "cannon",
        )
        self.assertEqual(response.lane, "right")
        self.assertEqual(response.threat_kind, "rush")
        self.assertEqual(response.point, CN_HOG_CANNON_POINTS["right"])

    def test_y250_siege_exception_never_promotes_ordinary_or_weak_river_labels(self) -> None:
        for kind, template_id, confidence, y in (
            ("rush", "different_rush_template", 0.96, 258),
            ("air", "rush_royal_giant_head", 0.96, 258),
            ("rush", "rush_royal_giant_head", 0.87, 258),
            ("rush", "rush_royal_giant_head", 0.96, 249),
        ):
            with self.subTest(kind=kind, template_id=template_id, confidence=confidence, y=y):
                self.strategy = HogCycleStrategy(started_at=0.0)
                evidence = threat(kind, 292, y, confidence)
                evidence["template_id"] = template_id
                self.assertIsNone(
                    self.defend(
                        hand("cannon", "fireball", "log"),
                        [(292, y)],
                        threats=[evidence],
                    )
                )

    def test_baseline_b13_unknown_air_group_does_not_spend_log_before_ready_output(self) -> None:
        # 15:39:10 frozen image 423d8431...: balloon/dragons, no ground
        # target, but unknown classification let Log steal Musketeer's fee.
        response = self.decision(
            self.defend(
                hand("log", "fireball", "musketeer", "ice_golem"),
                [(188, 360), (232, 348), (254, 351), (262, 347), (265, 363)],
                elixir=4,
            ),
            "musketeer",
        )
        self.assertEqual(response.elixir - COSTS[response.card], 0)
        self.assertIsNone(response.threat_kind)

    def test_unknown_dense_group_uses_fireball_before_ground_only_fallbacks(self) -> None:
        self.decision(
            self.defend(
                hand("log", "fireball", "cannon", "skeletons"),
                [(232, 348), (254, 351), (265, 363)],
                elixir=4,
            ),
            "fireball",
        )

    def test_unknown_group_keeps_log_fallback_when_effective_output_is_unavailable(self) -> None:
        cards = hand("log", "fireball", "musketeer")
        cards[1]["available"] = False
        cards[2]["available"] = False
        self.decision(self.defend(cards, [(110, 345), (120, 350)], elixir=4), "log")

    def test_baseline_b13_shallow_unknown_balloon_cannot_trigger_hog_counterattack(self) -> None:
        response = self.decision(
            self.defend(
                hand("hog", "musketeer", "log", "cannon"),
                [(301, 317)],
                elixir=7,
            ),
            "musketeer",
        )
        self.assertEqual(response.category, "defense")

    def test_recent_cannon_alone_cannot_authorize_unknown_pressure_counterattack(self) -> None:
        core = self.decision(self.defend(hand("cannon"), [(110, 330)], now=10.0), "cannon")
        self.strategy.record(core, confirmed=True, now=10.0)
        self.assertIsNone(self.defend(hand("hog"), [(110, 330)], elixir=6, now=13.0))

    def test_baseline_b14_and_b16_stable_bridge_points_get_near_musketeer(self) -> None:
        # B14 fixed 137,292; B16 fixed 298,272. These had visible continuing
        # tower damage but were excluded indefinitely by the old y300 gate.
        for point, lane in (((137, 292), "left"), ((298, 272), "right")):
            with self.subTest(point=point):
                self.strategy = HogCycleStrategy(started_at=0.0)
                cards = hand("musketeer", "hog", "fireball", "ice_golem")
                for now in (0.0, 1.2, 2.6):
                    self.assertIsNone(self.strategy.decide(cards, 5, [point], now))
                response = self.decision(self.strategy.decide(cards, 6, [point], 3.4), "musketeer")
                self.assertEqual(response.point, CN_HOG_BRIDGE_MUSKETEER_POINTS[lane])
                self.assertTrue(response.persistent_bridge)
                self.assertIsNone(response.threat_kind)

    def test_transient_bridge_warning_still_allows_clear_lane_hog(self) -> None:
        response = self.decision(self.strategy.decide(hand("hog", "musketeer"), 7, [(137, 292)], 10.0), "hog")
        self.assertFalse(response.persistent_bridge)

    def test_persistent_bridge_requires_three_distinct_frame_times(self) -> None:
        cards = hand("musketeer")
        for now in (0.0, 0.0, 0.0, 2.5):
            self.assertIsNone(self.strategy.decide(cards, 5, [(137, 292)], now))
        self.assertEqual(max(item["frames"] for item in self.strategy.bridge_observations), 2)

    def test_bridge_track_resets_after_gap_and_does_not_inherit_old_age(self) -> None:
        cards = hand("musketeer")
        for now in (0.0, 1.0, 4.0, 5.0):
            self.assertIsNone(self.strategy.decide(cards, 5, [(137, 292)], now))
        self.assertEqual(self.strategy.bridge_observations[0]["first"], 4.0)
        self.assertEqual(self.strategy.bridge_observations[0]["frames"], 2)

    def test_bridge_track_tolerates_bounded_card_io_gap_but_not_movement(self) -> None:
        cards = hand("musketeer")
        for now in (0.0, 2.4, 4.8):
            self.assertIsNone(self.strategy.decide(cards, 5, [(137, 292)], now))
        response = self.decision(self.strategy.decide(cards, 5, [(137, 292)], 5.6), "musketeer")
        self.assertTrue(response.persistent_bridge)
        self.strategy = HogCycleStrategy(started_at=0.0)
        for now, point in ((0.0, (137, 250)), (1.2, (137, 262)), (2.6, (137, 274)), (3.4, (137, 287))):
            self.assertIsNone(self.strategy.decide(cards, 5, [point], now))

    def test_absent_current_bridge_point_never_gets_spending_from_cached_history(self) -> None:
        for now in (0.0, 1.2, 2.6, 3.4):
            self.strategy.decide([], 0, [(137, 292)], now)
        self.assertIsNone(self.strategy.decide(hand("musketeer", "fireball"), 6, [], 4.0))

    def test_validated_balloon_template_uses_its_own_confidence_threshold(self) -> None:
        evidence = threat("air", 301, 317, 0.785)
        evidence["template_id"] = "air_balloon_envelope"
        response = self.decision(
            self.defend(
                hand("musketeer", "hog", "log"),
                [(301, 317)],
                elixir=6,
                threats=[evidence],
            ),
            "musketeer",
        )
        self.assertEqual(response.threat_kind, "air")

    def test_balloon_threshold_exception_rejects_weak_wrong_or_misused_template(self) -> None:
        for kind, template_id, confidence in (
            ("air", "air_balloon_envelope", 0.77),
            ("air", "wrong_id", 0.785),
            ("rush", "air_balloon_envelope", 0.785),
        ):
            with self.subTest(kind=kind, template_id=template_id, confidence=confidence):
                self.strategy = HogCycleStrategy(started_at=0.0)
                evidence = threat(kind, 301, 350, confidence)
                evidence["template_id"] = template_id
                response = self.decision(self.defend(hand("cannon"), [(301, 350)], threats=[evidence]), "cannon")
                self.assertIsNone(response.threat_kind)

    def test_candidate_b1_new_enemy_after_gap_cannot_spend_against_held_old_points(self) -> None:
        # 16:18:33: held depth347 produced Log(111,387), although the
        # current enemy was 145,406 and already behind that launch point.
        for now in (1.0, 1.5):
            self.strategy.decide([], 0, [(110, 340), (112, 347)], now)
        self.strategy.decide([], 0, [], 2.0)
        self.assertIsNone(self.strategy.decide(hand("log"), 7, [(145, 406)], 2.5))
        response = self.decision(self.strategy.decide(hand("log"), 7, [(145, 406)], 3.0), "log")
        self.assertEqual(response.point, (145, 446))
        self.assertEqual((response.pressure_count, response.pressure_depth), (1, 406))

    def test_reappearing_enemy_can_move_and_second_frame_supplies_current_spell_location(self) -> None:
        for now in (1.0, 1.5):
            self.strategy.decide([], 0, [(110, 345), (120, 350), (130, 360)], now)
        self.strategy.decide([], 0, [], 2.0)
        self.assertIsNone(
            self.strategy.decide(
                hand("fireball"),
                7,
                [(280, 330), (290, 335), (300, 340)],
                2.5,
            )
        )
        response = self.decision(
            self.strategy.decide(
                hand("fireball"),
                7,
                [(290, 350), (300, 355), (310, 360)],
                3.0,
            ),
            "fireball",
        )
        self.assertEqual(response.lane, "right")
        self.assertEqual(response.point, (300, 365))
        self.assertEqual(response.pressure_depth, 360)

    def test_first_frame_new_pressure_does_not_borrow_an_old_covered_counterpush(self) -> None:
        core = self.decision(self.defend(hand("musketeer"), [(110, 345)], now=10.0), "musketeer")
        self.strategy.record(core, confirmed=True, now=10.0)
        self.strategy.decide([], 0, [], 12.0)
        self.assertIsNone(self.strategy.decide(hand("hog"), 8, [(300, 410)], 12.5))

    def test_only_validated_ordinary_balloon_can_promote_early_marker_215(self) -> None:
        evidence = threat("air", 87, 215, 0.78657)
        evidence["template_id"] = "air_balloon_envelope"
        response = self.decision(
            self.defend(
                hand("hog", "musketeer", "log"),
                [(87, 215)],
                elixir=6,
                threats=[evidence],
            ),
            "musketeer",
        )
        self.assertEqual(response.threat_kind, "air")
        self.assertEqual(response.pressure_depth, 215)

    def test_early_balloon_boundary_does_not_expand_other_templates_or_unknown_markers(self) -> None:
        cases = [
            ("air", "different_air", 0.96, 215),
            ("air", "air_skeleton_barrel_top", 0.80, 260),
            ("rush", "rush_royal_giant_head", 0.96, 249),
            ("rush", "air_balloon_envelope", 0.96, 215),
            ("air", "air_balloon_envelope", 0.77, 215),
            ("air", "air_balloon_envelope", 0.90, 209),
        ]
        for kind, template_id, confidence, y in cases:
            with self.subTest(kind=kind, template_id=template_id, confidence=confidence, y=y):
                self.strategy = HogCycleStrategy(started_at=0.0)
                evidence = threat(kind, 87, y, confidence)
                evidence["template_id"] = template_id
                self.assertIsNone(
                    self.defend(hand("cannon", "log", "fireball"), [(87, y)], elixir=6, threats=[evidence])
                )
        self.strategy = HogCycleStrategy(started_at=0.0)
        self.assertIsNone(self.defend(hand("cannon", "log", "fireball"), [(87, 215)], elixir=6))

    def test_early_air_classification_requires_its_actual_associated_marker(self) -> None:
        evidence = threat("air", 87, 215, 0.90)
        evidence["template_id"] = "air_balloon_envelope"
        for enemies in ([], [(190, 215)], [(300, 215)]):
            with self.subTest(enemies=enemies):
                self.strategy = HogCycleStrategy(started_at=0.0)
                self.assertIsNone(self.defend(hand("cannon", "fireball", "log"), enemies, elixir=6, threats=[evidence]))

    def test_candidate_b5_cannon_does_not_block_complementary_musketeer_at_four_elixir(self) -> None:
        first = self.decision(self.defend(hand("cannon"), [(123, 318), (128, 300)], now=10.0), "cannon")
        self.strategy.record(first, confirmed=True, now=10.0)
        response = self.decision(
            self.defend(
                hand("ice_golem", "fireball", "hog", "musketeer"),
                [(111, 272), (123, 337), (124, 322), (127, 272)],
                elixir=4,
                now=19.0,
            ),
            "musketeer",
        )
        self.strategy.record(response, confirmed=True, now=19.0)
        self.assertEqual(sum(cost for _, _, cost in self.strategy.core_spending), 7)

    def test_normal_window_rejects_same_cannon_repeat_even_when_six_is_below_seven(self) -> None:
        first = self.decision(self.defend(hand("cannon"), [(110, 340)], now=10.0), "cannon")
        self.strategy.record(first, confirmed=True, now=10.0)
        self.assertIsNone(self.defend(hand("cannon"), [(110, 345)], now=16.0))

    def test_normal_core_pair_budget_is_independent_per_lane(self) -> None:
        left = self.decision(self.defend(hand("musketeer"), [(110, 340)], now=10.0), "musketeer")
        self.strategy.record(left, confirmed=True, now=10.0)
        right = self.decision(self.defend(hand("musketeer"), [(300, 340)], now=15.0), "musketeer")
        self.strategy.record(right, confirmed=True, now=15.0)
        cannon = self.decision(self.defend(hand("cannon"), [(300, 345)], now=20.0), "cannon")
        self.strategy.record(cannon, confirmed=True, now=20.0)
        self.assertEqual(sum(cost for _, side, cost in self.strategy.core_spending if side == "right"), 7)
        self.assertEqual(sum(cost for _, side, cost in self.strategy.core_spending if side == "left"), 4)

    def test_urgent_same_card_exception_stays_inside_eight_elixir_budget(self) -> None:
        first = self.decision(self.defend(hand("cannon"), [(110, 330)], now=10.0), "cannon")
        self.strategy.record(first, confirmed=True, now=10.0)
        second = self.decision(self.defend(hand("cannon"), [(150, 380)], now=15.0), "cannon")
        self.strategy.record(second, confirmed=True, now=15.0)
        self.assertIsNone(self.defend(hand("cannon"), [(150, 385)], now=20.0))

    def test_b35_late_outer_tower_attacker_does_not_receive_out_of_range_middle_cannon(self) -> None:
        # 00:16:27: the attacker at 340,370 remained outside the visible
        # Cannon radius after Cannon(228,330), and kept hitting the right tower.
        response = self.decision(
            self.defend(
                hand("ice_spirit", "cannon", "log"),
                [(340, 370)],
                elixir=3,
            ),
            "ice_spirit",
        )
        self.assertEqual(response.point, (340, 390))
        self.assertLess(math.dist(response.point, (340, 370)), math.dist(CN_HOG_STALL_POINTS["right"], (340, 370)))
        self.assertEqual(response.elixir - COSTS[response.card], 2)

    def test_late_cannon_geometry_applies_to_both_lanes_but_keeps_reachable_targets(self) -> None:
        for point in ((78, 370), (340, 370)):
            with self.subTest(point=point):
                self.strategy = HogCycleStrategy(started_at=0.0)
                self.assertIsNone(self.defend(hand("cannon"), [point], elixir=3))
        self.strategy = HogCycleStrategy(started_at=0.0)
        self.decision(self.defend(hand("cannon"), [(260, 360)], elixir=6), "cannon")

    def test_typed_rush_keeps_early_interception_but_cannot_bypass_late_range_gate(self) -> None:
        self.decision(
            self.defend(
                hand("cannon", "skeletons"),
                [(303, 285)],
                elixir=3,
                threats=[threat("rush", 303, 285)],
            ),
            "cannon",
        )
        self.strategy = HogCycleStrategy(started_at=0.0)
        response = self.decision(
            self.defend(
                hand("cannon", "skeletons"),
                [(340, 370)],
                elixir=3,
                threats=[threat("rush", 340, 370)],
            ),
            "skeletons",
        )
        self.assertEqual(response.point, (340, 390))

    def test_near_target_delay_avoids_tower_footprints_and_stays_in_friendly_arena(self) -> None:
        min_x, min_y, max_x, max_y = CN_HOG_STALL_SAFE_BOUNDS
        for point in ((78, 370), (110, 400), (300, 380), (340, 370), (205, 430), (220, 440), (365, 455)):
            with self.subTest(point=point):
                self.strategy = HogCycleStrategy(started_at=0.0)
                response = self.decision(self.defend(hand("ice_spirit"), [point], elixir=1), "ice_spirit")
                x, y = response.point
                self.assertTrue(min_x <= x <= max_x and min_y <= y <= max_y)
                self.assertGreaterEqual(y, point[1])
                for x1, y1, x2, y2 in CN_HOG_FRIENDLY_TOWER_BOXES.values():
                    self.assertFalse(x1 <= x <= x2 and y1 <= y <= y2)

    def test_early_stall_preserves_existing_bridge_placement(self) -> None:
        response = self.decision(self.defend(hand("ice_spirit"), [(300, 325)], elixir=1), "ice_spirit")
        self.assertEqual(response.point, CN_HOG_STALL_POINTS["right"])

    def test_b35_confirmed_incursion_fireball_includes_nearby_observed_bridge_support(self) -> None:
        # Current input really contains five markers; only three have crossed
        # y300. No unobserved troop identity or hidden count is assumed.
        enemies = [(292, 288), (296, 306), (299, 323), (313, 286), (318, 303)]
        response = self.decision(
            self.defend(
                hand("fireball", "musketeer", "cannon", "log"),
                enemies,
                elixir=6,
            ),
            "fireball",
        )
        self.assertEqual(response.pressure_count, 3)
        self.assertEqual(response.point, (304, 311))

    def test_bridge_support_must_be_local_and_in_same_lane(self) -> None:
        cases = [
            [(296, 306), (299, 323), (318, 303), (290, 240), (313, 240)],
            [(296, 306), (299, 323), (318, 303), (100, 286), (110, 288)],
        ]
        for enemies in cases:
            with self.subTest(enemies=enemies):
                self.strategy = HogCycleStrategy(started_at=0.0)
                self.decision(self.defend(hand("fireball", "musketeer"), enemies, elixir=6), "musketeer")

    def test_bridge_only_large_group_does_not_authorize_fireball(self) -> None:
        self.assertIsNone(
            self.defend(
                hand("fireball", "musketeer", "cannon", "log"),
                [(292, 280), (296, 285), (299, 290), (313, 286), (318, 288)],
                elixir=6,
            )
        )

    def test_nine_elixir_confirmed_ice_golem_hog_pair_keeps_three_for_defense(self) -> None:
        opening = self.decision(self.strategy.decide(hand("ice_golem", "hog"), 9, [], 10.0), "ice_golem")
        self.assertEqual(opening.elixir - COSTS[opening.card], 7)
        self.strategy.record(opening, confirmed=True, now=10.0)
        follow = self.decision(self.strategy.decide(hand("hog"), 7, [], 12.0), "hog")
        self.assertEqual(follow.elixir - COSTS[follow.card], 3)

    def test_eight_elixir_does_not_invest_ice_golem_without_ready_hog(self) -> None:
        self.assertIsNone(self.strategy.decide(hand("ice_golem", "musketeer", "cannon", "log"), 8, [], 10.0))
        single = self.decision(self.strategy.decide(hand("ice_golem", "hog"), 7, [], 12.0), "hog")
        self.assertEqual(single.elixir - COSTS[single.card], 3)

    def test_pending_pair_waits_for_transient_hog_availability_instead_of_back_cycle(self) -> None:
        opening = self.decision(self.strategy.decide(hand("ice_golem", "hog"), 9, [], 10.0), "ice_golem")
        self.strategy.record(opening, confirmed=True, now=10.0)
        cards = hand("hog", "skeletons", "ice_spirit")
        cards[0]["available"] = False
        self.assertIsNone(self.strategy.decide(cards, 7, [], 12.0))
        cards[0]["available"] = True
        self.decision(self.strategy.decide(cards, 7, [], 13.0), "hog")

    def test_nine_elixir_pair_is_still_cancelled_by_confirmed_deep_pressure(self) -> None:
        opening = self.decision(self.strategy.decide(hand("ice_golem", "hog"), 9, [], 10.0), "ice_golem")
        self.strategy.record(opening, confirmed=True, now=10.0)
        self.assertIsNone(self.defend(hand("hog"), [(300, 405)], elixir=6, now=13.0))
        self.assertEqual(self.strategy.pending_hog_until, 0.0)

    def test_validated_enemy_hog_bridge_approach_can_request_early_cannon(self) -> None:
        evidence = threat("rush", 335, 203)
        evidence["template_id"] = "rush_hog_rider"
        response = self.decision(
            self.defend(
                hand("hog", "cannon", "ice_spirit"),
                [(335, 203)],
                elixir=6,
                threats=[evidence],
            ),
            "cannon",
        )
        self.assertEqual(response.lane, "right")
        self.assertEqual(response.point, CN_HOG_CANNON_POINTS["right"])
        self.assertEqual(response.threat_kind, "rush")

    def test_early_hog_does_not_expand_generic_rush_or_air_boundaries(self) -> None:
        cases = [
            ("rush", "unknown_rush", 0.96, 203),
            ("air", "rush_hog_rider", 0.96, 203),
            ("rush", "rush_hog_rider", 0.87, 203),
            ("rush", "rush_hog_rider", 0.96, 199),
        ]
        for kind, template_id, confidence, y in cases:
            with self.subTest(kind=kind, template_id=template_id, confidence=confidence, y=y):
                self.strategy = HogCycleStrategy(started_at=0.0)
                evidence = threat(kind, 335, y, confidence)
                evidence["template_id"] = template_id
                self.assertIsNone(self.defend(hand("cannon", "log"), [(335, y)], elixir=6, threats=[evidence]))

    def test_early_hog_requires_a_current_matching_marker(self) -> None:
        evidence = threat("rush", 335, 203)
        evidence["template_id"] = "rush_hog_rider"
        for enemies in ([], [(110, 203)], [(250, 203)]):
            with self.subTest(enemies=enemies):
                self.strategy = HogCycleStrategy(started_at=0.0)
                self.assertIsNone(self.defend(hand("cannon", "log"), enemies, elixir=6, threats=[evidence]))

    def test_failed_core_never_reserves_same_card_slot_in_window(self) -> None:
        failed = self.decision(self.defend(hand("cannon"), [(110, 340)], now=10.0), "cannon")
        self.strategy.record(failed, confirmed=False, now=10.0)
        self.assertEqual(self.strategy.core_spending, [])
        self.assertEqual(self.strategy.last_defense_by_card, {})
        self.decision(self.defend(hand("cannon"), [(110, 345)], now=16.0), "cannon")

    def test_three_clear_destroyed_tower_frames_switch_attack_lane(self) -> None:
        towers = {"left": False, "right": True}
        for now in (1.0, 2.0):
            self.strategy.decide([], 0, [], now, towers)
            self.assertEqual(self.strategy.attack_lane, "left")
        decision = self.decision(self.strategy.decide(hand("hog"), 9, [], 3.0, towers), "hog")
        self.assertEqual(self.strategy.attack_lane, "right")
        self.assertEqual(decision.point, CN_HOG_BRIDGE_POINTS["right"])


if __name__ == "__main__":
    unittest.main()
