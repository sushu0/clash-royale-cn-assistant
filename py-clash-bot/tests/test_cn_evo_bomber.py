"""Evolution is a visible hand state, not an assumption from a deck slot."""

import json
from itertools import combinations
from pathlib import Path

import cv2
import numpy as np

from pyclashbot.bot.card_detection import (
    _identify_cn_hand,
    card_color_data,
    identify_567_hand_frame,
)
from pyclashbot.bot.double_air_567_strategy import COSTS, Decision, DoubleAir567Strategy


def hand(*cards, evolved=True):
    return [
        {
            "slot": i,
            "card": c,
            "variant": "evo_bomber" if c == "bomber" and evolved else c,
            "available": True,
            "evolution_ready": c == "bomber" and evolved,
        }
        for i, c in enumerate(cards)
    ]


def choose(p, cards, now, points=(), evolved=True, **extra):
    cues = {"own_tower_fill": {"left": 1, "right": 1}, "far_warnings": [], "threats": []}
    cues.update(extra)
    return p.decide(hand(*cards, evolved=evolved), 10, list(points), now, **cues)


def test_base_cost_remains_two_and_normal_fixture_does_not_claim_evolution():
    frame = cv2.imread(str(Path(__file__).parent / "fixtures/cn_567/hand_machine.png"))
    assert frame is not None and frame.size > 0, "Cannot decode cn_567/hand_machine.png"
    item = identify_567_hand_frame(frame)[2]
    assert COSTS["bomber"] == 2 and "evo_bomber" not in COSTS
    assert item["card"] == "bomber" and item["variant"] == "bomber"
    assert item["variant_confident"] and not item["evolution_ready"]


def test_ambiguous_form_preserves_base_card_but_does_not_invent_ready_evolution():
    frame = cv2.imread(str(Path(__file__).parent / "fixtures/cn_567/hand_machine.png"))
    assert frame is not None and frame.size > 0, "Cannot decode cn_567/hand_machine.png"
    bank = {
        name: (name.removeprefix("evo_").removeprefix("hero_"), np.array(data))
        for name, data in card_color_data.items()
    }
    bank["evo_bomber"] = ("bomber", np.array(card_color_data["bomber"]))
    item = _identify_cn_hand(frame, bank)[2]
    assert item["card"] == "bomber" and item["available"]
    assert item["variant"] is None and not item["variant_confident"]
    assert not item["evolution_ready"]


def test_confirmed_evolution_prioritizes_ground_splash_and_lane_alignment():
    points = [(110, 290), (120, 298), (128, 305)]
    threats = [{"kind": "ground", "small": True, "heavy": False, "confidence": 0.95, "x": x, "y": y} for x, y in points]
    actions = []
    for evolved in (False, True):
        policy = DoubleAir567Strategy(0)
        for now in (1, 2):
            action = choose(
                policy, ("bomber", "arrows", "baby_dragon", "zap"), now, points, evolved=evolved, threats=threats
            )
        actions.append(action)
    assert actions[0].card == "arrows"
    assert actions[1].card == "bomber" and actions[1].variant == "evo_bomber"
    assert actions[1].point == (115, 340)


def test_evolution_never_replaces_a_real_anti_air_answer():
    policy = DoubleAir567Strategy(0)
    action = choose(
        policy,
        ("bomber", "mega_minion", "pekka", "zap"),
        1,
        [(115, 390)],
        threats=[{"kind": "air", "confidence": 0.95, "x": 115, "y": 390}],
    )
    assert action.card == "mega_minion"


def test_evolved_emergency_transition_is_not_dropped_at_the_attackers_feet():
    cards = ("bomber", "goblin_giant", "pekka", "zap")
    actions = []
    for evolved in (False, True):
        policy = DoubleAir567Strategy(0)
        for now in (1, 2):
            action = choose(policy, cards, now, [(156, 416)], evolved=evolved)
        actions.append(action)
    assert actions[0].category == actions[1].category == "defense_cycle"
    assert actions[0].point == (165, 425)
    assert actions[1].point == (165, 460)
    assert actions[1].reserve == 4


def test_evolved_rear_points_are_mirrored_and_keep_princess_tower_lane():
    assert DoubleAir567Strategy._bomber_defense_point((115, 385), "left") == (115, 445)
    assert DoubleAir567Strategy._bomber_defense_point((303, 385), "right") == (303, 445)
    assert DoubleAir567Strategy._bomber_defense_point((253, 416), "right") == (253, 460)


def test_one_evolved_support_is_placed_behind_an_observed_giant():
    p = DoubleAir567Strategy(0)
    p.wave = {"at": 1, "lane": "left", "supported": False, "air": False}
    p.defenders = [
        {"card": "goblin_giant", "point": (115, 380), "deployed": 1, "seen": 4, "frames": 3, "visible": True}
    ]
    for now in (5, 6, 7, 8):
        action = choose(p, ("bomber", "goblin_machine", "pekka", "zap"), now, allies=[(115, 380)])
    assert action.card == "bomber" and action.category == "support"
    assert action.point[1] > 380 and action.reserve >= 2
    p.record(action, True, 8)
    assert p.wave["supported"]
    assert p.defenders[-1]["variant"] == "evo_bomber"
    assert choose(p, ("bomber", "goblin_machine", "pekka", "zap"), 10, allies=[(115, 380)]) is None


def test_unobserved_front_counterpush_is_not_treated_as_a_surviving_tank():
    p = DoubleAir567Strategy(0)
    p.record(Decision(0, "goblin_giant", "goblin_giant", (115, 290), "front push", "counterpush", 10, "left"), True, 1)
    for now in (2, 5, 10, 12):
        assert choose(p, ("bomber", "goblin_machine", "mega_minion", "zap"), now) is None


def test_safe_rear_giant_gets_only_one_cheap_follower_without_waiting_nine_seconds():
    p = DoubleAir567Strategy(0)
    p.record(Decision(0, "goblin_giant", "goblin_giant", (165, 460), "safe start", "attack", 10, "left"), True, 1)
    cards = ("bomber", "goblin_machine", "mega_minion", "zap")
    for now in (2, 3, 4):
        assert choose(p, cards, now) is None
    action = choose(p, cards, 5)
    assert action.card == "bomber" and action.category == "support"
    assert action.point == (165, 460)
    assert "recent confirmed rear Giant" in action.reason
    assert not any(d["visible"] for d in p.defenders)
    p.record(action, True, 5)
    assert choose(p, cards, 7) is None


def test_recent_rear_window_expires_and_never_overrides_enemy_pressure():
    cards = ("bomber", "goblin_machine", "mega_minion", "zap")
    p = DoubleAir567Strategy(0)
    p.record(Decision(0, "goblin_giant", "goblin_giant", (165, 460), "safe start", "attack", 10, "left"), True, 1)
    for now in (2, 3, 4, 5):
        action = choose(p, cards, now, [(303, 390)], threats=[{"kind": "air", "confidence": 0.95, "x": 303, "y": 390}])
        if action:
            assert action.category == "defense" and action.card == "mega_minion"
    p = DoubleAir567Strategy(0)
    p.record(Decision(0, "goblin_giant", "goblin_giant", (165, 460), "safe start", "attack", 10, "left"), True, 1)
    assert choose(p, cards, 8) is None
    assert choose(p, cards, 12) is None


def test_evolved_bomber_can_support_a_visible_defending_pekka():
    p = DoubleAir567Strategy(0)
    p.defenders = [{"card": "pekka", "point": (115, 300), "deployed": 1, "seen": 1, "frames": 3, "visible": True}]
    for now in (2, 3):
        action = choose(
            p,
            ("bomber", "goblin_machine", "mega_minion", "zap"),
            now,
            [(115, 285)],
            allies=[(115, 300)],
            threats=[{"kind": "ground", "heavy": True, "confidence": 0.95, "x": 115, "y": 285}],
        )
    assert action.card == "bomber" and action.category == "defense_support"
    assert action.point[1] > 300


def test_safe_preparation_keeps_evolution_for_support_when_another_lead_is_held():
    p = DoubleAir567Strategy(0)
    cards = ("bomber", "goblin_machine", "mega_minion", "zap")
    assert choose(p, cards, 1) is None
    action = choose(p, cards, 10)
    assert action.card == "goblin_machine" and action.reserve == 3


def test_all_seventy_safe_hands_still_have_an_active_option_with_evolution():
    for cards in combinations(COSTS, 4):
        p = DoubleAir567Strategy(0)
        choose(p, cards, 1)
        action = choose(p, cards, 10)
        assert action is not None, cards
        assert action.card not in {"arrows", "zap"}
        assert action.elixir - COSTS[action.card] >= action.reserve


def test_form_reporting_keeps_unconfirmed_and_uncertain_separate(tmp_path):
    # Test dependency stays scoped to this fixture or mock.
    from scripts.report_cn_567 import (  # noqa: PLC0415
        build_report,
    )

    rows = []
    for variant, confirmed in (("bomber", True), ("evo_bomber", False), (None, True)):
        rows.append(
            {
                "event": "play",
                "session": "test",
                "policy_version": "test",
                "time": "test",
                "battle": 1,
                "decision": {"card": "bomber", "variant": variant, "category": "defense"},
                "confirmed": confirmed,
            }
        )
    source = tmp_path / "trace.jsonl"
    source.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    entry = build_report(source)["sessions"][0]
    assert entry["bomber_forms"] == {
        "normal": {"attempts": 1, "confirmed": 1},
        "evolved": {"attempts": 1, "confirmed": 0},
        "uncertain": {"attempts": 1, "confirmed": 1},
    }
    assert entry["deployment_failures"] == 1 and entry["completed"] == 0
