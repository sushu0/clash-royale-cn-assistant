"""Behavioral rules for varied decks rather than matching a fixed card rotation."""

import pytest

from pyclashbot.bot.coords import CN_HOG_FRIENDLY_TOWER_BOXES, CN_RANDOM_POLICY_POINTS, CN_RANDOM_SPELL_POINTS
from pyclashbot.bot.random_card_roles import role_for
from pyclashbot.bot.random_deck_strategy import RandomDeckStrategy


def hand(*names):
    return [
        {"slot": slot, "card": name, "variant": name, "available": True, "cost": role_for(name).cost}
        for slot, name in enumerate(names)
    ]


def cues(elixir=10, enemies=None, threats=None, **other):
    return {"elixir": elixir, "enemies": enemies or [], "threats": threats or [], "far_warnings": [], **other}


def test_no_blind_spell_on_empty_lane():
    policy = RandomDeckStrategy(0)
    assert policy.decide(hand("rocket", "fireball", "freeze", "rage"), cues(), 10) is None


def test_hog_is_bridge_attack_with_defense_reserve():
    policy = RandomDeckStrategy(0)
    decision = policy.decide(hand("hog", "musketeer", "fireball", "cannon"), cues(6), 10)
    assert decision.card == "hog" and decision.category == "attack"
    assert decision.point == CN_RANDOM_POLICY_POINTS["bridge"]["left"]
    assert decision.reserve >= 2


def test_golem_waits_for_budget_and_then_starts_from_back():
    policy = RandomDeckStrategy(0)
    assert policy.decide(hand("golem", "rocket", "freeze", "rage"), cues(8), 10) is None
    decision = policy.decide(hand("golem", "rocket", "freeze", "rage"), cues(10), 12)
    assert decision.card == "golem" and decision.category == "prepare"
    assert decision.point == CN_RANDOM_POLICY_POINTS["back"]["left"]


def test_air_threat_does_not_select_ground_only_cannon():
    policy = RandomDeckStrategy(0)
    threat = [{"kind": "air", "confidence": 0.95, "x": 115, "y": 260}]
    decision = policy.decide(hand("cannon", "musketeer", "knight", "log"), cues(5, threats=threat), 10)
    assert decision.card == "musketeer"
    assert decision.category == "defense"


def test_opposite_lane_air_does_not_block_emergency_ground_defense():
    policy = RandomDeckStrategy(0)
    threat = [{"kind": "air", "confidence": 0.95, "x": 303, "y": 250}]
    decision = policy.decide(
        hand("cannon", "rocket", "freeze", "rage"), cues(4, enemies=[(115, 380)], threats=threat), 10
    )
    assert decision.card == "cannon" and decision.lane == "left"


def test_stable_swarm_prioritizes_splash_defender():
    policy = RandomDeckStrategy(0)
    scene = cues(5, enemies=[(110, 310), (125, 318), (115, 320)])
    policy.decide(hand("knight", "valkyrie", "hog", "rocket"), scene, 10)
    decision = policy.decide(hand("knight", "valkyrie", "hog", "rocket"), scene, 12)
    assert decision.card == "valkyrie" and decision.category == "defense"


def test_emergency_building_uses_central_lure_position():
    policy = RandomDeckStrategy(0)
    decision = policy.decide(hand("cannon", "rocket", "freeze", "rage"), cues(4, enemies=[(115, 380)]), 10)
    assert decision.card == "cannon"
    assert decision.point == CN_RANDOM_POLICY_POINTS["building"]["left"]


def test_confirmed_tank_receives_support_but_failed_input_does_not_create_push():
    policy = RandomDeckStrategy(0)
    lead = policy.decide(hand("giant", "rocket", "freeze", "rage"), cues(9), 10)
    policy.record(lead, False, 10)
    assert policy.wave is None
    policy.record(lead, True, 12)
    follow = policy.decide(hand("musketeer", "rocket", "freeze", "rage"), cues(6, allies=[(115, 370)]), 15)
    assert follow.category == "support" and follow.card == "musketeer"


def test_graveyard_not_cast_without_a_lead():
    policy = RandomDeckStrategy(0)
    assert policy.decide(hand("graveyard", "rocket", "freeze", "rage"), cues(), 10) is None


def test_profiles_follow_newly_identified_attack_core():
    policy = RandomDeckStrategy(0)
    policy.decide(hand("hog", "skeletons"), cues(4), 10)
    assert "快速" in policy.profile()["mode"]
    policy.decide(hand("golem", "musketeer"), cues(4), 12)
    assert "重型" in policy.profile()["mode"]


@pytest.mark.parametrize(
    ("name", "role", "cost"),
    [
        ("clone", "buff", 3),
        ("cannon_cart", "fighter", 5),
        ("goblinstein", "fighter", 5),
        ("elite_barbarians", "fighter", 6),
        ("hero_ice_golem", "cycle", 2),
    ],
)
def test_roles_do_not_confuse_troops_spells_or_elite_names(name, role, cost):
    card = role_for(name)
    assert card.role == role and card.cost == cost


def test_emergency_defense_uses_shorter_gap_and_updates_pressure_during_cooldown():
    policy = RandomDeckStrategy(0)
    lead = policy.decide(hand("giant"), cues(9), 10)
    policy.record(lead, True, 10)
    assert policy.decide(hand("knight"), cues(5, enemies=[(115, 300)]), 10.1) is None
    decision = policy.decide(hand("knight"), cues(5, enemies=[(115, 300)]), 10.6)
    assert decision.category == "defense"
    policy.record(decision, True, 10.6)
    urgent = policy.decide(hand("cannon"), cues(5, enemies=[(115, 380)]), 10.9)
    assert urgent.category == "building" and urgent.urgent


@pytest.mark.parametrize("point", [(115, 340), (120, 395), (210, 430), (305, 395)])
def test_interception_moves_with_enemy_and_avoids_friendly_towers(point):
    policy = RandomDeckStrategy(0)
    decision = policy.decide(hand("knight"), cues(5, enemies=[point]), 10)
    x, y = decision.point
    assert decision.urgent and y > point[1]
    assert all(not (a <= x <= c and b <= y <= d) for a, b, c, d in CN_HOG_FRIENDLY_TOWER_BOXES.values())


def test_building_cooldown_falls_back_to_available_troop():
    policy = RandomDeckStrategy(0)
    first = policy.decide(hand("cannon"), cues(4, enemies=[(115, 380)]), 10)
    policy.record(first, True, 10)
    decision = policy.decide(hand("cannon", "musketeer"), cues(5, enemies=[(115, 345)]), 12)
    assert decision.card == "musketeer" and decision.category == "defense"


def test_known_allied_defender_prevents_redundant_spending_but_deep_enemy_bypasses_hold():
    policy = RandomDeckStrategy(0)
    first = policy.decide(hand("valkyrie"), cues(5, enemies=[(115, 340)]), 10)
    policy.record(first, True, 10)
    assert policy.decide(hand("knight"), cues(8, enemies=[(115, 345)], allies=[(125, 360)]), 11) is None
    decision = policy.decide(hand("knight"), cues(8, enemies=[(115, 385)], allies=[(125, 360)]), 11.1)
    assert decision.category == "defense"


def test_disappeared_enemy_is_not_defended_for_seconds_after_death():
    policy = RandomDeckStrategy(0)
    scene = cues(5, enemies=[(115, 310)])
    policy.decide(hand("knight"), scene, 10)
    policy.decide(hand("knight"), scene, 10.5)
    decision = policy.decide(hand("hog"), cues(8), 11.4)
    assert decision.category == "attack"


def test_heavy_push_requires_visible_anchor_after_initial_support_window():
    policy = RandomDeckStrategy(0)
    lead = policy.decide(hand("giant"), cues(9), 10)
    policy.record(lead, True, 10)
    decision = policy.decide(hand("musketeer"), cues(7), 20)
    assert decision is None
    decision = policy.decide(hand("musketeer"), cues(7, allies=[(115, 310)]), 20.6)
    assert decision.category == "support"
    assert decision.point[1] > 310
    assert decision.point != CN_RANDOM_POLICY_POINTS["back_support"]["left"]


def test_counterpush_follows_lane_that_was_defended():
    policy = RandomDeckStrategy(0)
    defender = policy.decide(hand("knight"), cues(5, enemies=[(300, 380)]), 10)
    policy.record(defender, True, 10)
    attack = policy.decide(hand("hog"), cues(8), 14)
    assert attack.category == "attack" and attack.lane == "right"


def test_buff_needs_observed_allied_group_and_graveyard_needs_lead_across_river():
    policy = RandomDeckStrategy(0)
    lead = policy.decide(hand("giant"), cues(9), 10)
    policy.record(lead, True, 10)
    assert policy.decide(hand("rage", "graveyard"), cues(8), 13) is None
    buff = policy.decide(hand("rage"), cues(7, allies=[(110, 330), (125, 345)]), 14)
    assert buff.category == "buff"
    graveyard = policy.decide(hand("graveyard"), cues(8, allies=[(115, 250)], enemy_towers={"left": True}), 15)
    assert graveyard.card == "graveyard" and graveyard.category == "remote"


def test_failed_slot_backoff_does_not_block_other_cards():
    policy = RandomDeckStrategy(0)
    first = policy.decide(hand("hog"), cues(8), 10)
    policy.record(first, False, 10)
    decision = policy.decide(hand("hog", "musketeer"), cues(8), 10.7)
    assert decision.card == "musketeer" and decision.slot == 1


def test_cheap_cycle_does_not_starve_visible_heavy_attack_budget():
    policy = RandomDeckStrategy(0)
    assert policy.decide(hand("golem", "ice_spirit", "knight"), cues(8), 10) is None
    assert "预算" in policy.observation["reason"]
    lead = policy.decide(hand("golem", "ice_spirit", "knight"), cues(10), 12)
    assert lead.card == "golem" and lead.category == "prepare"


def test_unknown_enemy_prefers_defender_that_can_cover_air_and_ground():
    policy = RandomDeckStrategy(0)
    decision = policy.decide(hand("knight", "musketeer"), cues(5, enemies=[(115, 380)]), 10)
    assert decision.card == "musketeer"


def unknown_card(slot, candidate="gob_curse"):
    return {"slot": slot, "card": None, "variant": None, "candidate": candidate, "available": False, "cost": None}


def test_battle_916_full_elixir_spell_hand_cycles_after_eight_seconds():
    policy = RandomDeckStrategy(0)
    stuck = [
        hand("lightning")[0],
        unknown_card(1),
        {**hand("clone")[0], "slot": 2},
        {**hand("royal_delivery")[0], "slot": 3},
    ]
    scene = cues(enemy_towers={"left": True, "right": True})
    assert policy.decide(stuck, scene, 0) is None
    assert policy.decide(stuck, scene, 7.99) is None
    decision = policy.decide(stuck, scene, 8)
    assert decision.card == "lightning" and decision.category == "spell"
    assert decision.cost == 6 and decision.point == CN_RANDOM_SPELL_POINTS["left"]
    assert decision.target is None and decision.urgent is False


def test_battle_917_full_elixir_missing_troops_cycles_even_during_enemy_pressure():
    policy = RandomDeckStrategy(0)
    stuck = [hand("earthquake")[0], unknown_card(1, "furnace"), unknown_card(2), unknown_card(3, "goblin_hut")]
    scene = cues(enemies=[(305, 390)], enemy_towers={"left": False, "right": True})
    assert policy.decide(stuck, scene, 0) is None
    assert policy.decide(stuck, scene, 7.99) is None
    decision = policy.decide(stuck, scene, 8)
    assert decision.card == "earthquake" and decision.cost == 3
    assert decision.lane == "right" and decision.point == CN_RANDOM_SPELL_POINTS["right"]


@pytest.mark.parametrize("interruption_elixir", [9, None])
def test_full_elixir_timer_restarts_after_nonfull_or_unknown_observation(interruption_elixir):
    policy = RandomDeckStrategy(0)
    scene = cues(enemy_towers={"left": True})
    assert policy.decide(hand("lightning"), scene, 0) is None
    assert policy.decide(hand("lightning"), cues(interruption_elixir), 7.1) is None
    assert policy.full_elixir_since is None
    assert policy.decide(hand("lightning"), scene, 8) is None
    assert policy.decide(hand("lightning"), scene, 15.99) is None
    assert policy.decide(hand("lightning"), scene, 16).card == "lightning"


def test_confirmed_consumption_restarts_full_elixir_timer():
    policy = RandomDeckStrategy(0)
    scene = cues(enemy_towers={"left": True})
    assert policy.decide(hand("lightning"), scene, 0) is None
    decision = policy.decide(hand("lightning"), scene, 8)
    policy.record(decision, True, 8.1)
    assert policy.full_elixir_since is None
    assert policy.decide(hand("lightning"), scene, 10) is None
    assert policy.decide(hand("lightning"), scene, 17.99) is None
    assert policy.decide(hand("lightning"), scene, 18).card == "lightning"


def test_failed_idle_spell_keeps_timer_but_honors_attempt_gap_and_slot_backoff():
    policy = RandomDeckStrategy(0)
    scene = cues(enemy_towers={"left": True})
    assert policy.decide(hand("lightning"), scene, 0) is None
    decision = policy.decide(hand("lightning"), scene, 8)
    policy.record(decision, False, 8)
    assert policy.full_elixir_since == 0
    assert policy.decide(hand("lightning", "rocket"), scene, 8.1) is None
    fallback = policy.decide(hand("lightning", "rocket"), scene, 8.6)
    assert fallback.card == "rocket" and fallback.slot == 1
    assert policy.decide(hand("lightning"), scene, 9.21).card == "lightning"


@pytest.mark.parametrize(
    "towers", [{}, {"left": None, "right": None}, {"left": False, "right": False}, {"left": False, "right": None}]
)
def test_idle_spell_requires_confirmed_living_enemy_tower(towers):
    policy = RandomDeckStrategy(0)
    scene = cues(enemy_towers=towers)
    assert policy.decide(hand("lightning"), scene, 0) is None
    assert policy.decide(hand("lightning"), scene, 8) is None


def test_idle_spell_selects_cheaper_damaging_spell_and_living_lower_health_tower():
    policy = RandomDeckStrategy(0)
    scene = cues(enemy_towers={"left": True, "right": True}, enemy_tower_fill={"left": 0.9, "right": 0.3})
    assert policy.decide(hand("lightning", "earthquake"), scene, 0) is None
    decision = policy.decide(hand("lightning", "earthquake"), scene, 8)
    assert decision.card == "earthquake" and decision.cost == 3
    assert decision.lane == "right" and decision.point == CN_RANDOM_SPELL_POINTS["right"]


@pytest.mark.parametrize(
    "name", ["clone", "freeze", "rage", "gob_curse", "royal_delivery", "log", "barb_barrel", "tornado", "vines"]
)
def test_idle_spell_never_blind_casts_spells_with_special_target_or_placement(name):
    policy = RandomDeckStrategy(0)
    scene = cues(enemy_towers={"left": True, "right": True})
    assert policy.decide(hand(name), scene, 0) is None
    assert policy.decide(hand(name), scene, 30) is None


def test_idle_spell_rejects_gray_or_unidentified_damaging_card():
    policy = RandomDeckStrategy(0)
    gray = [{**hand("lightning")[0], "available": False}, unknown_card(1, "earthquake")]
    scene = cues(enemy_towers={"left": True})
    assert policy.decide(gray, scene, 0) is None
    assert policy.decide(gray, scene, 8) is None


def test_idle_spell_does_not_displace_ordinary_attack_or_urgent_defense():
    policy = RandomDeckStrategy(0)
    scene = cues(enemy_towers={"left": True})
    assert policy.decide(hand("earthquake"), scene, 0) is None
    attack = policy.decide(hand("earthquake", "hog"), scene, 8)
    assert attack.card == "hog" and attack.category == "attack"
    defense = policy.decide(hand("earthquake", "musketeer"), cues(enemies=[(305, 390)], enemy_towers={"left": True}), 9)
    assert defense.card == "musketeer" and defense.category == "defense"
