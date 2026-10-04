"""Budget locks and evidence-backed lane selection, without invented identities."""

import math

import pytest

from pyclashbot.bot.coords import CN_567_POINTS
from pyclashbot.bot.double_air_567_strategy import Decision, DoubleAir567Strategy


def decide(policy, now, cards=("pekka", "zap", "goblin_giant", "arrows"), points=(), elixir=10, **kwargs):
    hand = [{"slot": i, "card": card, "variant": card, "available": True} for i, card in enumerate(cards)]
    return policy.decide(hand, elixir, list(points), now, **kwargs)


def test_heavy_spell_lock_draws_next_counter_only_at_current_near_target():
    policy = DoubleAir567Strategy(0)
    assert decide(policy, 1, points=[(273, 342)]) is None
    action = decide(policy, 2, points=[(273, 342)])
    assert action.card == "zap" and action.category == "defense_cycle"
    assert action.point == (273, 342) and action.reserve == 4
    assert policy.observation["pressure"][0]["kind"] == "unknown"
    policy.record(action, True, 2)
    assert decide(policy, 5, points=[(273, 342)]) is None
    assert decide(policy, 6) is None  # never cast at the vanished old point


@pytest.mark.parametrize("elixir", [0, 2, 5, None])
def test_emergency_cycle_keeps_four_elixir(elixir):
    policy = DoubleAir567Strategy(0)
    for now in (1, 2, 3):
        assert decide(policy, now, points=[(273, 342)], elixir=elixir) is None


def test_far_warning_never_becomes_zap_cycle():
    policy = DoubleAir567Strategy(0)
    for now in (1, 2):
        assert decide(policy, now, far_warnings=[(273, 230)]) is None


def test_real_anti_air_precedes_emergency_spell_and_does_not_spend_ground_pekka():
    policy = DoubleAir567Strategy(0)
    cards = ("pekka", "zap", "baby_dragon", "arrows")
    for now in (1, 2):
        action = decide(
            policy, now, cards, points=[(273, 342)], threats=[{"kind": "air", "confidence": 0.95, "x": 273, "y": 342}]
        )
    assert action.card == "baby_dragon" and action.category == "defense"


def test_failed_cycle_does_not_claim_confirmed_spending_or_reset_pressure():
    policy = DoubleAir567Strategy(0)
    decide(policy, 1, points=[(273, 342)])
    action = decide(policy, 2, points=[(273, 342)])
    policy.record(action, False, 2)
    assert policy.last_defense_cycle == -math.inf
    assert not policy.categories
    assert decide(policy, 3, points=[(273, 342)]) is None  # physical retry interval


def test_expired_unseen_air_preparation_releases_safe_cycle():
    policy = DoubleAir567Strategy(0)
    policy.record(Decision(0, "mega_minion", None, (165, 460), "prepare", "prepare", 10, "left"), True, 1)
    cards = ("baby_dragon", "pekka", "arrows", "zap")
    assert decide(policy, 2, cards) is None
    assert decide(policy, 7, cards) is None
    action = decide(policy, 11, cards)
    assert action.card == "baby_dragon" and action.category == "prepare"
    assert action.elixir - 4 >= action.reserve


def test_three_current_readings_choose_weaker_enemy_tower_for_new_wave():
    policy = DoubleAir567Strategy(0)
    cues = {"enemy_towers": {"left": True, "right": True}, "enemy_tower_fill": {"left": 0.8, "right": 0.3}}
    for now in (1, 2, 3):
        decide(policy, now, **cues)
    action = decide(policy, 8, **cues)
    assert action.category == "attack" and action.lane == "right"
    assert action.point == CN_567_POINTS["back"]["right"]


@pytest.mark.parametrize("fill", [None, 0, -1, 1.1, math.nan, math.inf, True])
def test_invalid_tower_fill_never_selects_a_fake_weak_lane(fill):
    policy = DoubleAir567Strategy(0)
    for now in (1, 2, 3):
        decide(policy, now, enemy_towers={"left": True, "right": True}, enemy_tower_fill={"left": 0.8, "right": fill})
    assert policy.attack_lane == "left"


def test_repeated_timestamp_gaps_and_flashes_do_not_confirm_lane():
    policy = DoubleAir567Strategy(0)
    cues = {"enemy_towers": {"left": True, "right": True}, "enemy_tower_fill": {"left": 0.8, "right": 0.3}}
    for now in (1, 1, 1, 6, 11):
        decide(policy, now, **cues)
    assert policy.attack_lane == "left"
    decide(policy, 12, enemy_towers=cues["enemy_towers"], enemy_tower_fill={"left": 0.3, "right": 0.8})
    decide(policy, 13, **cues)
    assert policy.attack_lane == "left"


def test_active_wave_does_not_switch_lanes_and_defense_still_precedes_attack():
    policy = DoubleAir567Strategy(0)
    policy.wave = {"at": 1, "lane": "left", "supported": True, "air": False}
    for now in (1, 2, 3):
        action = decide(
            policy,
            now,
            ("mega_minion", "zap", "goblin_giant", "arrows"),
            [(303, 390)],
            enemy_towers={"left": True, "right": True},
            enemy_tower_fill={"left": 0.8, "right": 0.3},
        )
    assert policy.attack_lane == "left"
    assert action.category == "defense" and action.lane == "right"
