"""Offline, read-only strategy probes for the 2026-10-03 code audit."""
import json
import math
from dataclasses import asdict
from pathlib import Path

import cv2

from pyclashbot.bot.hog_cycle_strategy import HogCycleStrategy
from pyclashbot.bot.random_card_roles import role_for
from pyclashbot.bot.random_deck_strategy import RandomDeckStrategy
from pyclashbot.detection.cn_battle_cues import read_cn_battle_cues


def hand(*names):
    return [
        {"slot": i, "card": name, "variant": name, "available": True,
         "cost": role_for(name).cost}
        for i, name in enumerate(names)
    ]


def cues(**extra):
    result = {"elixir": 10, "enemies": [], "threats": [], "far_warnings": []}
    result.update(extra)
    return result


def encode(decision):
    return asdict(decision) if decision is not None else None


out = {}
policy = RandomDeckStrategy(0)
out["destroyed_left_remote"] = encode(policy.decide(
    hand("goblin_barrel", "rocket", "freeze", "rage"),
    cues(enemy_towers={"left": False, "right": True},
         enemy_tower_fill={"left": None, "right": .8}), 10))

policy = RandomDeckStrategy(0)
out["known_four_card_lock"] = [
    {"now": now, "decision": encode(policy.decide(
        hand("graveyard", "freeze", "clone", "mirror"),
        cues(enemy_towers={"left": True, "right": True}), now))}
    for now in (0, 8, 30, 120)
]

policy = RandomDeckStrategy(0)
threats = [{"kind": "air", "x": 115, "y": 345, "confidence": .81,
            "template_id": "air_balloon_envelope"}]
out["validated_balloon_confidence"] = encode(policy.decide(
    hand("cannon", "knight", "freeze", "rage"),
    cues(enemies=[(115, 345)], threats=threats), 10))

policy = HogCycleStrategy(0)
policy.decide(hand("cannon", "musketeer", "ice_spirit", "log"), 10,
              [(115, 345)], 10, threats=threats)
out["same_balloon_hog_comparator"] = encode(policy.decide(
    hand("cannon", "musketeer", "ice_spirit", "log"), 10,
    [(115, 345)], 12, threats=threats))

fixture = Path(r"D:\codex\CodexWork\clash\py-clash-bot\tests\fixtures\cn_threats\air_independent_deep.png")
fixture_cues = read_cn_battle_cues(cv2.imread(str(fixture)), include_567=True)
fixture_cues["elixir"] = 10
policy = RandomDeckStrategy(0)
out["real_fixture_calibrated_air_response"] = {
    "fixture": str(fixture), "cues": fixture_cues,
    "decision": encode(policy.decide(hand("cannon", "knight", "arrows", "fireball"), fixture_cues, 10)),
}

policy = RandomDeckStrategy(0)
spell_hand = hand("fireball", "rage", "freeze", "clone")
policy.decide(spell_hand, cues(enemies=[(115, 380)]), 10)
out["gone_target_cached_spell"] = encode(policy.decide(spell_hand, cues(), 10.6))

policy = RandomDeckStrategy(0)
deep = policy.decide(hand("cannon"), cues(enemies=[(115, 450)]), 10)
out["deep_cannon_fixed_geometry"] = {
    "decision": encode(deep),
    "distance_from_projected_target": math.dist(deep.point, (115, 460)),
    "hog_calibrated_coverage_radius": 90,
}

policy = RandomDeckStrategy(0)
core = policy.decide(hand("giant"), cues(elixir=9), 10)
policy.record(core, True, 10)
out["unobserved_lead_support"] = encode(policy.decide(
    hand("musketeer"), cues(elixir=7, allies=[]), 20))

log_path = Path(r"D:\codex\CodexWork\clash\outputs\cn-random-mastery.jsonl")
with log_path.open("rb") as source:
    source.seek(0, 2)
    size = source.tell()
    offset = max(0, size - 8 * 1024 * 1024)
    source.seek(offset)
    rows = source.read().splitlines()
if offset:
    rows = rows[1:]
events = []
for raw in rows:
    try:
        events.append(json.loads(raw))
    except (json.JSONDecodeError, UnicodeDecodeError):
        continue
low_air, gone_plays, tower_conflicts = [], [], []
plays, finishes = [], []
for event in events:
    scene = event.get("cues", {})
    for threat in scene.get("threats", []):
        if threat.get("kind") == "air" and .74 <= threat.get("confidence", 0) < .88:
            low_air.append({"time": event.get("time"), "battle": event.get("battle"),
                            "threat": threat})
    if event.get("event") == "play":
        plays.append(event)
        decision = event.get("decision", {})
        if decision.get("target") and not scene.get("enemies"):
            gone_plays.append({"time": event.get("time"), "battle": event.get("battle"),
                               "decision": decision, "confirmed": event.get("confirmed")})
        if (decision.get("category") == "remote"
                and scene.get("enemy_towers", {}).get(decision.get("lane")) is False):
            tower_conflicts.append({"time": event.get("time"), "battle": event.get("battle"),
                                    "decision": decision, "confirmed": event.get("confirmed")})
    if event.get("event") == "battle_finished":
        finishes.append({key: event.get(key) for key in
                         ("time", "battle", "outcome", "card_attempts", "cards_confirmed")})
out["bounded_log_snapshot"] = {
    "source": str(log_path), "size_at_read": size, "tail_bytes": size-offset,
    "parsed_events": len(events), "from": events[0].get("time") if events else None,
    "through": events[-1].get("time") if events else None,
    "plays": len(plays), "confirmed": sum(bool(e.get("confirmed")) for e in plays),
    "low_confidence_air_count": len(low_air), "low_confidence_air_samples": low_air[:3],
    "plays_with_absent_current_enemy_count": len(gone_plays),
    "plays_with_absent_current_enemy_samples": gone_plays[:3],
    "remote_destroyed_tower_count": len(tower_conflicts),
    "remote_destroyed_tower_samples": tower_conflicts[:3],
    "recent_finished": finishes[-5:],
}
target = Path(r"D:\codex\CodexWork\clash\work\audit-20261003\strategy-probe-results.json")
target.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=2))
