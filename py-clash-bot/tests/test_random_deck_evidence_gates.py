"""Spending gates reproduce the audit's scene transitions and special hands."""

from pathlib import Path

import cv2
import pytest

from pyclashbot.bot.coords import CN_RANDOM_ENEMY_KING_POINT, CN_RANDOM_POLICY_POINTS
from pyclashbot.bot.random_card_roles import mirrorable, role_for, special_capabilities
from pyclashbot.bot.random_deck_strategy import RandomDeckStrategy
from pyclashbot.detection.cn_battle_cues import read_cn_battle_cues


def hand(*names):
    return [
        {"slot": slot, "card": name, "variant": name, "available": True, "cost": role_for(name).cost}
        for slot, name in enumerate(names)
    ]


def cues(elixir=10, **other):
    return {"elixir": elixir, "enemies": [], "threats": [], "allies": [], "far_warnings": [], **other}


@pytest.mark.parametrize(
    ("confidence", "threshold", "accepted"),
    [
        (0.805, 0.74, True),
        (0.79, 0.78, True),
        (0.73, 0.74, False),
        (0.87, None, False),
        (0.89, None, True),
        (0.96, float("nan"), False),
        (0.96, 1.1, False),
    ],
)
def test_calibrated_detector_gate_preserves_approved_air_and_rejects_bad_scores(confidence, threshold, accepted):
    policy = RandomDeckStrategy(0)
    threat = {"kind": "air", "confidence": confidence, "x": 115, "y": 260}
    if threshold is not None:
        threat["confidence_threshold"] = threshold
    decision = policy.decide(hand("musketeer", "cannon"), cues(5, threats=[threat]), 10)
    assert (decision is not None and decision.category == "defense") is accepted
    if accepted:
        assert decision.card == "musketeer"


def test_independent_real_skeleton_barrel_frame_defends_air_through_full_pipeline():
    fixture = Path(__file__).parent / "fixtures" / "cn_threats" / "air_independent_deep.png"
    frame = cv2.imread(str(fixture))
    assert frame is not None, "Missing test fixture"
    scene = read_cn_battle_cues(frame, include_567=True)
    calibrated = [t for t in scene["threats"] if t["template_id"] == "air_skeleton_barrel_top"]
    assert calibrated and calibrated[0]["confidence_threshold"] <= calibrated[0]["confidence"] < 0.88
    decision = RandomDeckStrategy(0).decide(hand("cannon", "archers", "knight", "log"), scene, 10)
    assert decision.card == "archers" and decision.category == "defense"
    assert decision.target == (253, 336)


@pytest.mark.parametrize("name", ["poison", "fireball", "log", "freeze"])
def test_current_frame_loss_never_authorizes_a_spell_from_cached_pressure(name):
    policy = RandomDeckStrategy(0)
    scene = cues(5, enemies=[(115, 390)], allies=[(110, 365)])
    policy.decide(hand(name), scene, 10)
    assert policy.stable_pressure == [(115, 390)]
    missing = policy.decide(hand(name), cues(5), 10.2)
    assert missing is None
    assert policy.last_pressure_at == 10


def test_motion_prediction_does_not_follow_a_missing_enemy():
    policy = RandomDeckStrategy(0)
    policy.decide(hand("fireball"), cues(5, enemies=[(115, 370)]), 10)
    decision = policy.decide(hand("fireball"), cues(5, enemies=[(115, 390)]), 10.4)
    assert decision.target == (115, 390)
    assert policy.decide(hand("fireball"), cues(5), 10.5) is None
    assert policy.velocity == {}


@pytest.mark.parametrize("name", ["goblin_barrel", "goblin_drill", "miner"])
def test_remote_core_avoids_destroyed_princess_even_if_old_health_fill_remains(name):
    policy = RandomDeckStrategy(0)
    decision = policy.decide(
        hand(name), cues(enemy_towers={"left": False, "right": True}, enemy_tower_fill={"left": 0.01, "right": 0.8}), 10
    )
    assert decision.lane == "right"
    assert decision.point == CN_RANDOM_POLICY_POINTS["remote"]["right"]


@pytest.mark.parametrize("name", ["goblin_barrel", "miner", "graveyard"])
def test_remote_requires_living_tower_evidence_and_can_use_explicit_king(name):
    policy = RandomDeckStrategy(0)
    both_down = cues(enemy_towers={"left": False, "right": False})
    assert policy.decide(hand(name), both_down, 0) is None
    assert policy.decide(hand(name), both_down, 8) is None
    assert policy.observation["target_status"] == "king_unobserved"
    king = policy.decide(hand(name), cues(enemy_towers={"left": False, "right": False, "king": True}), 9)
    assert king is not None and king.point == CN_RANDOM_ENEMY_KING_POINT


def test_local_counterpush_switches_away_from_destroyed_lane():
    policy = RandomDeckStrategy(0)
    defender = policy.decide(hand("knight"), cues(5, enemies=[(115, 380)]), 10)
    policy.record(defender, True, 10)
    decision = policy.decide(hand("hog"), cues(8, enemy_towers={"left": False, "right": True}), 12)
    assert decision.lane == "right"


def test_four_special_cards_resolve_full_elixir_with_graveyard_at_living_tower():
    policy = RandomDeckStrategy(0)
    cards = hand("graveyard", "freeze", "clone", "mirror")
    scene = cues(enemy_towers={"left": False, "right": True})
    assert policy.decide(cards, scene, 0) is None
    assert policy.decide(cards, scene, 7.99) is None
    decision = policy.decide(cards, scene, 8)
    assert decision.card == "graveyard" and decision.lane == "right"
    assert decision.point == CN_RANDOM_POLICY_POINTS["remote"]["right"]
    assert decision.reserve >= 2


def test_special_hand_reports_unexecutable_state_without_legal_target():
    policy = RandomDeckStrategy(0)
    cards = hand("graveyard", "freeze", "clone", "mirror")
    assert policy.decide(cards, cues(), 0) is None
    assert policy.decide(cards, cues(), 30) is None
    assert {"graveyard", "freeze", "clone"} <= set(policy.observation["unexecutable_cards"])


def test_graveyard_idle_fallback_does_not_displace_urgent_defense_budget():
    policy = RandomDeckStrategy(0)
    cards = hand("graveyard", "freeze", "clone", "mirror")
    scene = cues(enemies=[(115, 390)], enemy_towers={"left": True, "right": True})
    assert policy.decide(cards, scene, 0) is None
    assert policy.decide(cards, scene, 8) is None


def test_mirror_uses_only_confirmed_deployment_with_dynamic_cost_and_new_target():
    policy = RandomDeckStrategy(0)
    original = policy.decide(hand("goblin_barrel"), cues(8, enemy_towers={"left": True}), 10)
    policy.record(original, False, 10)
    assert policy.decide(hand("mirror"), cues(8, enemy_towers={"right": True}), 11) is None
    policy.record(original, True, 11)
    policy.wave = None
    mirror = policy.decide(hand("mirror"), cues(8, enemy_towers={"left": False, "right": True}), 13)
    assert mirror.card == "mirror" and mirror.variant == "mirror" and mirror.mirrored_card == "goblin_barrel"
    assert mirror.cost == original.cost + 1 and mirror.point == CN_RANDOM_POLICY_POINTS["remote"]["right"]
    policy.record(mirror, True, 13)
    assert policy.decide(hand("mirror"), cues(10, enemy_towers={"right": True}), 16) is None


def test_mirror_recomputes_spell_target_and_rejects_missing_or_unaffordable_target():
    policy = RandomDeckStrategy(0)
    spell = policy.decide(hand("fireball"), cues(5, enemies=[(115, 390)]), 10)
    policy.record(spell, True, 10)
    assert policy.decide(hand("mirror"), cues(4, enemies=[(303, 390)]), 12) is None
    assert policy.decide(hand("mirror"), cues(5), 12) is None
    decision = policy.decide(hand("mirror"), cues(5, enemies=[(303, 390)]), 13)
    assert decision.mirrored_card == "fireball" and decision.target == (303, 390)
    assert decision.cost == 5


@pytest.mark.parametrize("name", ["archer_queen", "goblinstein", "little_prince", "hero_ice_golem"])
def test_champion_and_hero_deployment_never_claims_ability_or_mirror_support(name):
    assert mirrorable(name) is False
    assert special_capabilities(name)["ability"] == "unsupported_requires_visual_contract"
    policy = RandomDeckStrategy(0)
    deployment = policy.decide(hand(name), cues(10), 10)
    assert deployment is not None
    policy.record(deployment, True, 10)
    assert policy.decide(hand("mirror"), cues(10), 13) is None
    assert policy.profile()["special_mechanics"][name]["ability"] == "unsupported_requires_visual_contract"


@pytest.mark.parametrize(
    ("target", "expect_building"), [((115, 350), True), ((115, 380), True), ((115, 410), False), ((115, 450), False)]
)
def test_cannon_requires_coverage_in_its_placement_window(target, expect_building):
    policy = RandomDeckStrategy(0)
    decision = policy.decide(hand("cannon", "knight"), cues(5, enemies=[target]), 10)
    assert (decision.card == "cannon") is expect_building
    if not expect_building:
        assert decision.card == "knight" and decision.category == "defense"


def test_predicted_motion_can_close_the_building_coverage_window():
    policy = RandomDeckStrategy(0)
    policy.decide(hand("cannon"), cues(4, enemies=[(115, 355)]), 10)
    decision = policy.decide(hand("cannon"), cues(4, enemies=[(115, 380)]), 10.4)
    assert decision is None


def test_visible_anchor_controls_support_point_and_absence_prevents_late_support():
    policy = RandomDeckStrategy(0)
    lead = policy.decide(hand("giant"), cues(9), 10)
    policy.record(lead, True, 10)
    assert policy.decide(hand("musketeer"), cues(7), 20) is None
    visible = policy.decide(hand("musketeer"), cues(7, allies=[(115, 305)]), 20.2)
    assert visible.category == "support" and visible.point[1] == 335
    assert visible.point != CN_RANDOM_POLICY_POINTS["back_support"]["left"]


def test_initial_inferred_support_is_cheap_bounded_and_at_most_once():
    policy = RandomDeckStrategy(0)
    lead = policy.decide(hand("giant"), cues(9), 10)
    policy.record(lead, True, 10)
    assert policy.decide(hand("musketeer"), cues(7), 12) is None
    support = policy.decide(hand("archers"), cues(7), 12)
    assert support.category == "support" and support.cost <= 3
    assert support.inferred_support is True
    policy.record(support, True, 12)
    assert policy.decide(hand("skeletons"), cues(6), 13.2) is None
    assert policy.decide(hand("archers"), cues(7), 18) is None


def test_freeze_needs_current_enemy_and_visible_engaging_allies():
    policy = RandomDeckStrategy(0)
    scene = cues(5, enemies=[(115, 380), (130, 385)], allies=[(115, 350)])
    decision = policy.decide(hand("freeze"), scene, 10)
    assert decision.card == "freeze" and decision.target is not None
    assert policy.decide(hand("freeze"), cues(5, enemies=scene["enemies"]), 10.3) is None
    assert policy.decide(hand("freeze"), cues(5, allies=scene["allies"]), 10.4) is None


def test_clone_never_uses_a_disappeared_or_single_ally():
    policy = RandomDeckStrategy(0)
    lead = policy.decide(hand("giant"), cues(9), 10)
    policy.record(lead, True, 10)
    assert policy.decide(hand("clone"), cues(7, allies=[(115, 320)]), 13) is None
    clone = policy.decide(hand("clone"), cues(7, allies=[(115, 320), (130, 325)]), 13.5)
    assert clone.card == "clone" and clone.category == "buff"
    assert policy.decide(hand("clone"), cues(7), 13.6) is None


def test_spirit_empress_variant_preserves_current_cost_and_air_targeting():
    assert role_for("spirit_empress_ground", 3).cost == 3
    assert role_for("spirit_empress_ground", 3).air is False
    assert role_for("spirit_empress_air", 6).cost == 6
    assert role_for("spirit_empress_air", 6).air is True
    assert role_for("spirit_empress_ground", True).cost == 3


def test_unidentified_or_mismatched_variant_is_not_deployable():
    policy = RandomDeckStrategy(0)
    cards = [{**hand("mirror")[0], "card": None}, {**hand("goblin_barrel")[0], "slot": 1, "variant": "rocket"}]
    assert policy.decide(cards, cues(enemy_towers={"left": True}), 30) is None
