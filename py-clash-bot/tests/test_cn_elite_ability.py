"""Offline safety checks for the observed Elite Ice Golem ability rules."""

from __future__ import annotations

import unittest

from pyclashbot.bot.coords import CN_HOG_ELITE_ABILITY_TAP
from pyclashbot.bot.elite_ice_golem_ability import (
    ABILITY_COST,
    EliteAbilityDecision,
    EliteIceGolemAbility,
)


class TestCnEliteAbility(unittest.TestCase):
    """Use synthetic observations only; never touch the emulator or ADB."""

    def setUp(self) -> None:
        self.ability = EliteIceGolemAbility()
        self.point = (232, 380)
        self.nearby = [(230, 370), (244, 365)]

    def cues(self, *, ready: bool = True, elixir: int | None = 5, enemies: list[tuple[int, int]] | None = None) -> dict:
        return {
            "elite_ability_ready": ready,
            "elixir": elixir,
            "enemies": self.nearby if enemies is None else enemies,
        }

    def deployed(self, now: float = 0.0) -> None:
        self.ability.deployed("elite_ice_golem", self.point, now)

    def decision(self, value: EliteAbilityDecision | None) -> EliteAbilityDecision:
        self.assertIsNotNone(value)
        assert value is not None
        self.assertEqual(value.point, CN_HOG_ELITE_ABILITY_TAP)
        return value

    def test_no_confirmed_elite_deployment_never_uses_ability(self) -> None:
        for variant in (None, "ice_golem", "hog"):
            with self.subTest(variant=variant):
                ability = EliteIceGolemAbility()
                ability.deployed(variant, self.point, 0.0)
                self.assertIsNone(ability.decide(self.cues(), 1.0))
                self.assertIsNone(ability.decide(self.cues(), 1.5))
        self.assertIsNone(self.ability.decide(self.cues(), 1.0))
        self.assertIsNone(self.ability.decide(self.cues(), 1.5))

    def test_gray_button_is_rejected_and_ready_needs_two_frames(self) -> None:
        self.deployed()
        self.assertIsNone(self.ability.decide(self.cues(ready=False), 1.0))
        self.assertIsNone(self.ability.decide(self.cues(ready=False), 1.5))
        self.assertIsNone(self.ability.decide(self.cues(), 2.0))
        self.decision(self.ability.decide(self.cues(), 2.5))

    def test_nearby_pressure_needs_two_frames_and_five_elixir(self) -> None:
        self.deployed()
        self.assertIsNone(self.ability.decide(self.cues(enemies=[]), 1.0))
        self.assertIsNone(self.ability.decide(self.cues(), 1.5))
        self.assertIsNone(self.ability.decide(self.cues(elixir=4), 2.0))
        decision = self.decision(self.ability.decide(self.cues(), 2.5))
        self.assertEqual(decision.nearby_markers, 2)
        self.assertEqual(decision.elixir - ABILITY_COST, 3)

    def test_unknown_elixir_never_uses_ability(self) -> None:
        self.deployed()
        self.assertIsNone(self.ability.decide(self.cues(elixir=None), 1.0))
        self.assertIsNone(self.ability.decide(self.cues(elixir=None), 1.5))

    def test_far_lane_and_behind_deployment_pressure_are_rejected(self) -> None:
        for enemies in ([(110, 370), (120, 365)], [(230, 465), (240, 455)]):
            with self.subTest(enemies=enemies):
                self.deployed()
                self.assertIsNone(self.ability.decide(self.cues(enemies=enemies), 1.0))
                self.assertIsNone(self.ability.decide(self.cues(enemies=enemies), 1.5))

    def test_single_nonurgent_marker_is_not_enough(self) -> None:
        self.deployed()
        cues = self.cues(enemies=[(230, 370)])
        self.assertIsNone(self.ability.decide(cues, 1.0))
        self.assertIsNone(self.ability.decide(cues, 1.5))

    def test_pressure_disappearing_resets_confirmation(self) -> None:
        self.deployed()
        self.assertIsNone(self.ability.decide(self.cues(), 1.0))
        self.assertIsNone(self.ability.decide(self.cues(enemies=[]), 1.5))
        self.assertIsNone(self.ability.decide(self.cues(), 2.0))
        self.decision(self.ability.decide(self.cues(), 2.5))

    def test_nine_second_corridor_expires(self) -> None:
        self.deployed()
        self.assertIsNone(self.ability.decide(self.cues(), 8.5))
        self.decision(self.ability.decide(self.cues(), 9.0))
        self.assertIsNone(self.ability.decide(self.cues(), 9.01))
        self.assertIsNone(self.ability.decide(self.cues(), 12.0))

    def test_success_is_not_repeated_for_the_same_deployment(self) -> None:
        self.deployed()
        self.assertIsNone(self.ability.decide(self.cues(), 1.0))
        self.decision(self.ability.decide(self.cues(), 1.5))
        self.ability.record(confirmed=True, now=1.5)
        self.assertIsNone(self.ability.decide(self.cues(), 3.5))
        self.assertIsNone(self.ability.decide(self.cues(), 8.5))
        self.assertEqual(self.ability.confirmed_uses, 1)

    def test_failed_use_has_two_second_retry_gap_and_two_attempt_limit(self) -> None:
        self.deployed()
        self.assertIsNone(self.ability.decide(self.cues(), 1.0))
        self.decision(self.ability.decide(self.cues(), 1.5))
        self.ability.record(confirmed=False, now=1.5)
        self.assertIsNone(self.ability.decide(self.cues(), 3.49))
        self.decision(self.ability.decide(self.cues(), 3.5))
        self.ability.record(confirmed=False, now=3.5)
        self.assertIsNone(self.ability.decide(self.cues(), 5.5))
        self.assertIsNone(self.ability.decide(self.cues(), 8.5))
        self.assertEqual(self.ability.confirmed_uses, 0)

    def test_new_elite_deployment_can_use_ability_again(self) -> None:
        self.deployed()
        self.assertIsNone(self.ability.decide(self.cues(), 1.0))
        self.decision(self.ability.decide(self.cues(), 1.5))
        self.ability.record(confirmed=True, now=1.5)
        self.deployed(now=20.0)
        self.assertIsNone(self.ability.decide(self.cues(), 21.0))
        self.decision(self.ability.decide(self.cues(), 21.5))
        self.ability.record(confirmed=True, now=21.5)
        self.assertEqual(self.ability.confirmed_uses, 2)

    def test_urgent_three_marker_pressure_allows_four_elixir_reserving_two(self) -> None:
        self.ability.deployed("elite_ice_golem", (232, 420), 0.0)
        cues = self.cues(elixir=4, enemies=[(230, 408), (238, 411), (245, 403)])
        self.assertIsNone(self.ability.decide(cues, 1.0))
        decision = self.decision(self.ability.decide(cues, 1.5))
        self.assertEqual(decision.nearby_markers, 3)
        self.assertEqual(decision.elixir - ABILITY_COST, 2)

    def test_urgent_fewer_than_three_markers_still_preserves_three_elixir(self) -> None:
        self.ability.deployed("elite_ice_golem", (232, 420), 0.0)
        cues = self.cues(elixir=4, enemies=[(230, 408), (238, 411)])
        self.assertIsNone(self.ability.decide(cues, 1.0))
        self.assertIsNone(self.ability.decide(cues, 1.5))
        decision = self.decision(
            self.ability.decide(self.cues(enemies=cues["enemies"]), 2.0),
        )
        self.assertEqual(decision.elixir - ABILITY_COST, 3)


if __name__ == "__main__":
    unittest.main()
