"""Loss-audit regressions for defensive economy and persistent coverage.

These tests exercise public decisions and confirmed deployment outcomes. They
do not authorize live play or turn missing visual evidence into a target.
"""

import pytest

from pyclashbot.bot.random_card_roles import role_for
from pyclashbot.bot.random_deck_strategy import RandomDeckStrategy


def hand(*names):
    return [
        {
            "slot": slot,
            "card": name,
            "variant": name,
            "available": True,
            "cost": role_for(name).cost,
        }
        for slot, name in enumerate(names)
    ]


def cues(elixir=10, **other):
    return {
        "elixir": elixir,
        "enemies": [],
        "threats": [],
        "allies": [],
        "far_warnings": [],
        **other,
    }


def observe_pressure(policy, now=10):
    # No affordable hand is required to remember observed pressure. The enemy
    # remains a current-frame target only during this observation.
    assert policy.decide([], cues(7, enemies=[(115, 340)]), now) is None


def test_far_warning_preserves_only_identified_air_answer_for_defense():
    policy = RandomDeckStrategy(0)
    decision = policy.decide(
        hand("musketeer", "rocket", "freeze", "rage"),
        cues(8, far_warnings=[(115, 245)]),
        10,
    )
    assert decision is None


def test_far_warning_preserves_only_ready_air_answer_when_other_air_card_is_gray():
    policy = RandomDeckStrategy(0)
    cards = hand("musketeer", "archers", "rocket", "freeze")
    cards[1]["available"] = False
    decision = policy.decide(cards, cues(8, far_warnings=[(115, 245)]), 10)
    assert decision is None


def test_far_warning_allows_ground_cycle_when_air_answer_stays_in_hand():
    policy = RandomDeckStrategy(0)
    decision = policy.decide(
        hand("musketeer", "knight", "rocket", "freeze"),
        cues(8, far_warnings=[(115, 245)]),
        10,
    )
    assert decision is not None
    assert decision.card == "knight" and decision.category == "cycle"
    assert 8 - decision.cost >= role_for("musketeer").cost


def test_recent_pressure_reserves_the_actual_cost_of_visible_defender():
    policy = RandomDeckStrategy(0)
    observe_pressure(policy)
    cards = hand("hog", "musketeer", "freeze", "rage")
    assert policy.decide(cards, cues(7), 11) is None
    attack = policy.decide(cards, cues(8), 11.6)
    assert attack is not None and attack.card == "hog"
    assert attack.category == "attack"
    assert attack.reserve >= role_for("musketeer").cost
    assert 8 - attack.cost >= attack.reserve


def test_recent_pressure_reserves_ready_air_cost_when_cheaper_air_card_is_gray():
    policy = RandomDeckStrategy(0)
    observe_pressure(policy)
    cards = hand("hog", "musketeer", "archers", "freeze")
    cards[2]["available"] = False
    assert policy.decide(cards, cues(7), 11) is None


def test_recent_pressure_counts_reliably_identified_unaffordable_defender():
    policy = RandomDeckStrategy(0)
    observe_pressure(policy)
    cards = hand("hog", "musketeer", "freeze", "rage")
    cards[1]["available"] = False
    # Availability is not identity: a gray but identified defender still needs
    # enough elixir to become deployable if the enemy returns.
    assert policy.decide(cards, cues(7), 11) is None


def test_recent_pressure_does_not_reduce_defense_reserve_to_force_golem():
    policy = RandomDeckStrategy(0)
    observe_pressure(policy)
    decision = policy.decide(hand("golem", "musketeer", "freeze", "rage"), cues(10), 11)
    assert decision is None


def test_recent_pressure_does_not_spend_reserved_defense_budget_on_collector():
    policy = RandomDeckStrategy(0)
    observe_pressure(policy)
    decision = policy.decide(hand("elixir_collector", "musketeer", "freeze", "rage"), cues(9), 11)
    assert decision is None


@pytest.mark.parametrize(
    "names",
    [
        pytest.param(("dart_goblin", "rascals", "poison", "barbarians"), id="battle-1081-line-129558"),
        pytest.param(("bowler", "royal_ghost"), id="battle-1108-line-133152"),
        pytest.param(("xbow", "guards", "mini_pekka"), id="battle-1201-line-144968"),
    ],
)
def test_far_cycle_budget_excludes_the_defender_about_to_leave_hand(names):
    # The cited original traces spend a 3-elixir defender, then leave less than
    # the 4/5 elixir required by every other currently available defender.
    policy = RandomDeckStrategy(0)
    decision = policy.decide(hand(*names), cues(6, far_warnings=[(112, 257)]), 10)
    assert decision is None


def test_far_support_budget_excludes_spent_minions_from_future_air_answers():
    # Battle 1088, source line 130426: supporting with 3-elixir minions leaves
    # only 3 elixir, while the other available air answer is a 5-elixir horde.
    policy = RandomDeckStrategy(0)
    lead = policy.decide(hand("giant"), cues(9, enemy_towers={"left": False, "right": True}), 8)
    assert lead is not None and lead.lane == "right"
    policy.record(lead, True, 8)
    cards = hand("barbarians", "fireball", "minion_horde", "minions")
    cards[0]["variant"] = "evo_barbarians"
    decision = policy.decide(
        cards,
        cues(6, enemies=[(292, 272)], far_warnings=[(284, 241), (292, 269)], allies=[(247, 289)]),
        10,
    )
    assert decision is None


@pytest.mark.parametrize("name", ["lightning", "graveyard"])
def test_full_elixir_special_cycle_keeps_current_defensive_reserve(name):
    policy = RandomDeckStrategy(0)
    cards = hand(name, "pekka", "freeze", "clone")
    cards[1]["available"] = False
    scene = cues(10, enemy_towers={"left": True, "right": True})
    assert policy.decide(cards, scene, 0) is None
    # Keep the full-elixir observation continuous while recording fresh enemy
    # pressure; no old enemy coordinate may authorize the subsequent spend.
    assert policy.decide([], cues(10, enemies=[(115, 340)]), 7.6) is None
    assert policy.decide(cards, scene, 8) is None


def test_golem_can_open_after_pressure_window_expires():
    policy = RandomDeckStrategy(0)
    observe_pressure(policy)
    decision = policy.decide(hand("golem", "musketeer", "freeze", "rage"), cues(10), 14.1)
    assert decision is not None
    assert decision.card == "golem" and decision.category == "prepare"
    assert decision.cost == 8 and decision.reserve >= 2


def test_recent_pressure_preserves_only_air_answer_during_confirmed_push():
    policy = RandomDeckStrategy(0)
    lead = policy.decide(hand("giant"), cues(9), 9)
    assert lead is not None and lead.category == "prepare"
    policy.record(lead, True, 9)
    observe_pressure(policy, 10)
    decision = policy.decide(
        hand("musketeer", "rocket", "freeze", "rage"),
        cues(10, allies=[(115, 370)]),
        11,
    )
    assert decision is None


def test_current_air_target_can_spend_preserved_air_answer():
    policy = RandomDeckStrategy(0)
    decision = policy.decide(
        hand("musketeer", "knight", "rocket", "freeze"),
        cues(5, threats=[{"kind": "air", "confidence": 0.95, "x": 115, "y": 260}]),
        10,
    )
    assert decision is not None
    assert decision.card == "musketeer" and decision.category == "defense"
    assert decision.target == (115, 260)


@pytest.mark.parametrize("name", ["fireball", "arrows", "log"])
def test_confirmed_spell_does_not_establish_persistent_defender(name):
    policy = RandomDeckStrategy(0)
    scene = cues(7, enemies=[(115, 340), (130, 345)])
    spell = policy.decide(hand(name), scene, 10)
    assert spell is not None and spell.category == "spell"
    policy.record(spell, True, 10)
    defender = policy.decide(
        hand("knight"),
        cues(5, enemies=[(115, 345), (130, 345)], allies=[(115, 360)]),
        11,
    )
    assert defender is not None
    assert defender.card == "knight" and defender.category == "defense"


def test_confirmed_spell_keeps_defended_lane_for_counterattack():
    policy = RandomDeckStrategy(0)
    spell = policy.decide(hand("fireball"), cues(5, enemies=[(303, 390)]), 10)
    assert spell is not None and spell.category == "spell"
    policy.record(spell, True, 10)
    attack = policy.decide(hand("hog"), cues(8), 11)
    assert attack is not None
    assert attack.category == "attack" and attack.lane == "right"


@pytest.mark.parametrize("name", ["fireball", "log", "freeze"])
def test_economy_changes_never_spend_at_disappeared_enemy_coordinates(name):
    policy = RandomDeckStrategy(0)
    observe_pressure(policy)
    assert policy.decide(hand(name), cues(7), 11) is None


def test_far_warning_does_not_authorize_blind_defense_or_spell():
    policy = RandomDeckStrategy(0)
    decision = policy.decide(hand("fireball"), cues(7, far_warnings=[(115, 245)]), 10)
    assert decision is None


def test_low_confidence_air_does_not_authorize_defense():
    policy = RandomDeckStrategy(0)
    decision = policy.decide(
        hand("musketeer"),
        cues(5, threats=[{"kind": "air", "confidence": 0.73, "confidence_threshold": 0.74, "x": 115, "y": 260}]),
        10,
    )
    assert decision is None


def test_unknown_air_candidate_is_not_used_as_defense_budget_evidence():
    policy = RandomDeckStrategy(0)
    observe_pressure(policy)
    cards = hand("hog")
    cards.append({"slot": 1, "card": None, "variant": None, "candidate": "musketeer", "available": False, "cost": None})
    attack = policy.decide(cards, cues(7), 11)
    assert attack is not None and attack.card == "hog"
    assert attack.category == "attack" and attack.reserve == 3


def test_confirmed_defender_without_current_allies_does_not_hold_enemy_response():
    policy = RandomDeckStrategy(0)
    first = policy.decide(hand("knight"), cues(5, enemies=[(115, 340)]), 10)
    assert first is not None and first.category == "defense"
    policy.record(first, True, 10)
    second = policy.decide(hand("musketeer"), cues(5, enemies=[(115, 345)]), 11)
    assert second is not None and second.category == "defense"


def test_failed_defender_does_not_hold_enemy_response():
    policy = RandomDeckStrategy(0)
    first = policy.decide(hand("knight"), cues(5, enemies=[(115, 340)]), 10)
    assert first is not None and first.category == "defense"
    policy.record(first, False, 10)
    second = policy.decide(hand("musketeer"), cues(5, enemies=[(115, 345)], allies=[(115, 360)]), 11)
    assert second is not None and second.category == "defense"


def test_confirmed_persistent_defender_with_current_allies_still_holds():
    policy = RandomDeckStrategy(0)
    first = policy.decide(hand("knight"), cues(5, enemies=[(115, 340)]), 10)
    assert first is not None and first.category == "defense"
    policy.record(first, True, 10)
    second = policy.decide(hand("musketeer"), cues(5, enemies=[(115, 345)], allies=[(115, 360)]), 11)
    assert second is None


def test_mirror_of_confirmed_ordinary_defender_keeps_dynamic_cost_and_target():
    policy = RandomDeckStrategy(0)
    first = policy.decide(hand("knight"), cues(5, enemies=[(115, 340)]), 10)
    assert first is not None and first.category == "defense"
    policy.record(first, True, 10)
    mirrored = policy.decide(hand("mirror"), cues(5, enemies=[(115, 345)]), 11)
    assert mirrored is not None
    assert mirrored.card == "mirror" and mirrored.mirrored_card == "knight"
    assert mirrored.cost == first.cost + 1
    assert mirrored.category == "defense" and mirrored.target == (115, 345)
