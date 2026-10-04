"""Regress the observed v1.3 full-elixir deadlocks without weakening air safety."""

import json
import math
from pathlib import Path

from pyclashbot.bot.double_air_567_strategy import DoubleAir567Strategy


def hand(*cards):
    return [{"slot": i, "card": c, "available": True, "variant": c} for i, c in enumerate(cards)]


def choose(p, cards, now, points=(), **kwargs):
    cues = {"own_tower_fill": {"left": 1, "right": 1}, "far_warnings": [], "threats": []}
    cues.update(kwargs)
    return p.decide(hand(*cards), 10, list(points), now, **cues)


def test_duplicate_near_and_far_marker_is_one_target_not_a_swarm():
    p = DoubleAir567Strategy(0)
    points = [(110, 340), (116, 370)]
    for t in (1, 2):
        decision = choose(
            p, ("arrows", "baby_dragon", "pekka", "zap"), t, points, far_warnings=[(110, 345), (116, 367)]
        )
    assert len(p.tracks) == 2
    assert decision.card == "baby_dragon"


def test_slow_ground_motion_accumulates_but_static_siege_never_becomes_ground():
    p = DoubleAir567Strategy(0)
    for t, y in enumerate((290, 292, 294, 296), 1):
        decision = choose(
            p,
            ("goblin_machine", "pekka", "zap", "arrows"),
            t,
            [(115, y)],
            dark_ground_candidates=[{"x": 115, "y": y, "dark_pixels": 400}],
        )
    assert decision.card == "goblin_machine"
    assert decision.threat_kind == "ground"


def test_known_heavy_ground_gets_pekka_but_air_never_does():
    p = DoubleAir567Strategy(0)
    t = {"kind": "ground", "heavy": True, "x": 167, "y": 416, "confidence": 0.95}
    action = choose(p, ("goblin_giant", "pekka", "bomber", "zap"), 1, [(167, 416)], threats=[t])
    assert action.card == "pekka" and action.point[1] >= 370
    p = DoubleAir567Strategy(0)
    t["kind"], t["heavy"] = "air", False
    assert choose(p, ("goblin_giant", "pekka", "bomber", "zap"), 1, [(167, 416)], threats=[t]) is None


def test_unknown_near_king_draws_a_counter_without_spending_pekka_on_distant_siege():
    p = DoubleAir567Strategy(0)
    points = [(167, 416), (115, 250)]
    for now in (1, 2, 4):
        action = choose(p, ("goblin_giant", "pekka", "bomber", "zap"), now, points)
    assert action.card == "bomber"
    assert action.category == "defense_cycle" and action.reserve == 4
    assert action.point[1] >= 370
    p.record(action, True, 4)
    assert choose(p, ("goblin_giant", "pekka", "bomber", "zap"), 6, points) is None
    assert p.observation["pressure"]


def test_destroyed_or_unreadable_tower_does_not_permanently_veto_safe_attack():
    p = DoubleAir567Strategy(0)
    cards = ("goblin_giant", "arrows", "bomber", "zap")
    hp = {"left": 0.3, "right": None}
    assert choose(p, cards, 1, own_tower_fill=hp) is None
    assert choose(p, cards, 6, own_tower_fill=hp) is None
    action = choose(p, cards, 10, own_tower_fill=hp)
    assert action.card == "goblin_giant" and action.category == "attack"


def test_old_unseen_deployment_cannot_claim_new_baby_dragon():
    p = DoubleAir567Strategy(0)
    p.defenders = [
        {"card": "mega_minion", "point": (165, 460), "deployed": 1, "seen": 1, "frames": 0, "visible": False},
        {"card": "baby_dragon", "point": (165, 460), "deployed": 28, "seen": 28, "frames": 0, "visible": False},
    ]
    choose(p, ("goblin_giant", "arrows", "pekka", "zap"), 33, allies=[(184, 359)])
    assert not next(d for d in p.defenders if d["card"] == "mega_minion")["visible"]
    assert next(d for d in p.defenders if d["card"] == "baby_dragon")["visible"]


def test_three_distinct_single_targets_do_not_automatically_get_arrows():
    p = DoubleAir567Strategy(0)
    action = choose(p, ("arrows", "baby_dragon", "pekka", "zap"), 1, [(110, 380), (135, 365), (140, 390)])
    assert action.card == "baby_dragon"


def test_exact_saved_deadlocks_now_produce_bounded_response():
    folder = Path(__file__).parent / "fixtures/cn_567_v2"
    for filename, category in (
        ("audit-b16-130101-observe.json", "defense"),
        ("audit-b17-130336-observe.json", "defense_cycle"),
        ("audit-b17-130305-observe.json", "attack"),
    ):
        path = folder / filename
        row = json.loads(path.read_text(encoding="utf-8"))
        cues = row["cues"]
        p = DoubleAir567Strategy(0)
        for t in (1, 2, 10, 11):
            action = p.decide(
                row["hand"],
                cues["elixir"],
                cues["enemies"],
                t,
                far_warnings=cues.get("far_warnings"),
                threats=cues.get("threats"),
                own_tower_fill=cues.get("own_tower_fill"),
            )
        assert action is not None and action.category == category, filename


def test_near_king_unknown_does_not_spend_pekka_on_another_lane():
    p = DoubleAir567Strategy(0)
    for now in (1, 2):
        action = choose(
            p,
            ("pekka", "bomber", "goblin_giant", "zap"),
            now,
            [(167, 416), (300, 345)],
            threats=[{"kind": "ground", "heavy": True, "x": 300, "y": 345, "confidence": 0.95}],
        )
    assert action.card == "bomber" and action.lane == "left"


def test_stationary_siege_recovers_after_initial_marker_drift():
    p = DoubleAir567Strategy(0)
    for now, y in ((1, 220), (2, 224), (4, 227), (6, 227), (8, 227), (10, 227)):
        action = choose(
            p,
            ("pekka", "goblin_machine", "arrows", "zap"),
            now,
            [(115, y)],
            dark_ground_candidates=[{"x": 115, "y": y, "dark_pixels": 400}],
        )
    assert action is not None and action.threat_kind == "siege"


def test_heavy_role_survives_brief_visual_template_occlusion():
    p = DoubleAir567Strategy(0)
    cards = ("pekka", "mega_minion", "arrows", "zap")
    assert (
        choose(
            p,
            cards,
            1,
            [(115, 340)],
            threats=[{"kind": "ground", "heavy": True, "x": 115, "y": 340, "confidence": 0.95}],
        )
        is None
    )
    action = choose(p, cards, 2, [(115, 342)])
    assert action.card == "pekka" and action.threat_kind == "ground_heavy"


def test_machine_air_fallback_stays_out_of_rocket_dead_zone():
    p = DoubleAir567Strategy(0)
    target = (167, 416)
    action = choose(
        p,
        ("pekka", "goblin_machine", "arrows", "zap"),
        1,
        [target],
        threats=[{"kind": "air", "confidence": 0.95, "x": 167, "y": 416}],
    )
    assert action.card == "goblin_machine"
    assert 50 <= math.dist(action.point, target) <= 80
    assert action.card != "pekka"


def test_air_fallback_declines_machine_when_no_calibrated_point_is_in_range():
    assert DoubleAir567Strategy._rocket_point((60, 470), "left") is None
