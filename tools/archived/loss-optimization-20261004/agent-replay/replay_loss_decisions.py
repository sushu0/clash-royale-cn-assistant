"""Compare policies on logged scenes, retaining only actual deployment feedback.

This is a decision regression audit, not a battle simulator. Missing frames and
one-second wall-clock stamps prevent exact recreation of the live decision loop.
"""

import hashlib
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, fields
from datetime import datetime
from pathlib import Path

ROOT = Path(r"D:\codex\CodexWork\clash")
SOURCE = ROOT / "outputs/cn-random-mastery.jsonl"
BACKUP = ROOT / "work/loss-optimization-20261004/backup/random_deck_strategy.py"
OUTPUT = Path(__file__).resolve().parent
V23 = "random-rules-v2.3-20261003-evidence-gates"
sys.path.insert(0, str(ROOT / "py-clash-bot"))

from pyclashbot.bot import random_deck_strategy as current  # noqa: E402
from pyclashbot.bot.random_card_roles import canonical, role_for  # noqa: E402


def load_old():
    spec = importlib.util.spec_from_file_location("loss_replay_previous_policy", BACKUP)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def stamp(row):
    return datetime.strptime(row["time"], "%Y-%m-%d %H:%M:%S").timestamp()


def version(row):
    return (row.get("experiment") or {}).get("rule_version") or row.get(
        "strategy_version"
    )


def actual_decision(module, row):
    value = dict(row["decision"])
    value["point"] = tuple(value["point"])
    if value.get("target") is not None:
        value["target"] = tuple(value["target"])
    allowed = {field.name for field in fields(module.RandomDecision)}
    return module.RandomDecision(
        **{key: val for key, val in value.items() if key in allowed}
    )


def decision_dict(decision):
    return asdict(decision) if decision is not None else None


def same_action(decision, recorded):
    return decision is not None and all(
        getattr(decision, field) == recorded.get(field)
        for field in ("card", "slot", "category")
    )


def reliable_available(hand):
    result = []
    for item in hand:
        name = item.get("card")
        variant = item.get("variant") or name
        if (
            not name
            or canonical(variant) != canonical(name)
            or item.get("available") is not True
        ):
            continue
        role = role_for(variant, item.get("cost"))
        if role is not None:
            result.append((item, role))
    return result


def identity(row):
    return {
        key: row.get(key)
        for key in ("session", "battle", "source_line", "time", "event")
    }


def comparison(row, old_policy, new_policy, old_decision, new_decision):
    return {
        **identity(row),
        "hand": row.get("hand"),
        "cues": row.get("cues"),
        "logged_decision": row.get("decision"),
        "logged_confirmed": row.get("confirmed"),
        "logged_observation": row.get("observation"),
        "old_decision": decision_dict(old_decision),
        "new_decision": decision_dict(new_decision),
        "old_observation": dict(old_policy.observation),
        "new_observation": dict(new_policy.observation),
        "old_reproduced_logged_action": same_action(
            old_decision, row.get("decision") or {}
        ),
    }


def persistent_core_records(rows, target):
    # Restore actual deployment state without inventing unlogged observations.
    # Only earlier input/outcome records may affect this scene.
    return [
        row
        for row in rows
        if row["source_line"] < target["source_line"] and row.get("event") == "play"
    ]


def minimal_air_replay(old_module, rows, row):
    now = stamp(row)
    old_policy = old_module.RandomDeckStrategy(now - 600)
    new_policy = current.RandomDeckStrategy(now - 600)
    for prior in persistent_core_records(rows, row):
        if not prior.get("decision"):
            continue
        for module, policy in ((old_module, old_policy), (current, new_policy)):
            policy.record(
                actual_decision(module, prior),
                prior.get("confirmed") is True,
                stamp(prior),
            )
    old_decision = old_policy.decide(row["hand"], row["cues"], now)
    new_decision = new_policy.decide(row["hand"], row["cues"], now)
    result = comparison(row, old_policy, new_policy, old_decision, new_decision)
    result["method"] = (
        "actual prior deployment records plus this exact scene; no invented intervening frames"
    )
    result["unsafe_same_air_spend_survives"] = bool(
        new_decision
        and new_decision.slot == row["decision"]["slot"]
        and new_decision.category in {"cycle", "support", "prepare", "attack"}
        and new_decision.target is None
    )
    result["new_current_target_defense"] = bool(
        new_decision
        and new_decision.target is not None
        and new_decision.category in {"defense", "building", "spell"}
    )
    return result


def minimal_spell_replay(old_module, spell, row):
    delta = stamp(row) - stamp(spell)
    # Log stamps denote seconds, not the actual monotonic deployment times.
    # Probe several explicit feasible offsets; never label them measured times.
    low, high = max(0.0, delta - 1.0), delta + 1.0
    points = [point for point in (0.6, 1.0, 1.5, 1.9, 2.1) if low <= point <= high]
    probes = []
    for elapsed in points:
        old_policy = old_module.RandomDeckStrategy(-10)
        new_policy = current.RandomDeckStrategy(-10)
        for module, policy in ((old_module, old_policy), (current, new_policy)):
            # The preceding spell's scene is a recorded frame and supplies the
            # first pressure scan for targets below the emergency threshold.
            policy.decide(spell.get("hand") or [], spell.get("cues") or {}, 0)
            policy.record(actual_decision(module, spell), True, 0)
        old_decision = old_policy.decide(row["hand"], row["cues"], elapsed)
        new_decision = new_policy.decide(row["hand"], row["cues"], elapsed)
        old_hold = (
            old_decision is None
            and "已有可见友军接敌" in old_policy.observation.get("reason", "")
        )
        current_response = bool(new_decision and new_decision.target is not None)
        probes.append(
            {
                "probe_elapsed_seconds_not_measured": elapsed,
                "old_reproduces_spell_based_hold": old_hold,
                "new_current_target_response": current_response,
                "old_decision": decision_dict(old_decision),
                "new_decision": decision_dict(new_decision),
                "old_observation": dict(old_policy.observation),
                "new_observation": dict(new_policy.observation),
            }
        )
    reproduced = [probe for probe in probes if probe["old_reproduces_spell_based_hold"]]
    return {
        **identity(row),
        "previous_spell": {
            **identity(spell),
            "decision": spell.get("decision"),
            "confirmed": spell.get("confirmed"),
        },
        "hand": row.get("hand"),
        "cues": row.get("cues"),
        "logged_observation": row.get("observation"),
        "logged_delta_seconds": delta,
        "feasible_elapsed_interval_due_to_second_resolution": [low, high],
        "old_reproduced_at_feasible_probe": bool(reproduced),
        "new_responds_at_every_old_hold_probe": bool(reproduced)
        and all(probe["new_current_target_response"] for probe in reproduced),
        "new_spell_based_persistent_hold_removed": bool(reproduced)
        and all(
            "已有可见友军接敌" not in probe["new_observation"].get("reason", "")
            for probe in reproduced
        ),
        "probes": probes,
    }


def main():
    old_module = load_old()
    groups = defaultdict(list)
    source_digest = hashlib.sha256()
    parse_errors = []
    with SOURCE.open("rb") as stream:
        for line_no, raw in enumerate(stream, 1):
            source_digest.update(raw)
            try:
                row = json.loads(raw)
            except (ValueError, UnicodeError) as exc:
                parse_errors.append({"line": line_no, "error": str(exc)})
                continue
            if version(row) != V23:
                continue
            battle = (
                row.get("finished_battle", row.get("battle"))
                if row.get("event") == "battle_finished"
                else row.get("battle")
            )
            if not isinstance(battle, int):
                continue
            row["source_line"] = line_no
            groups[(row.get("session"), battle)].append(row)

    summary = Counter()
    air_cases, spell_cases, budget_cases = [], [], []
    outcomes = Counter()
    full_replay_examples = []
    for (session, battle), rows in groups.items():
        endings = [row for row in rows if row.get("event") == "battle_finished"]
        if not endings:
            summary["incomplete_groups_excluded"] += 1
            continue
        outcomes_in_group = {row.get("outcome") for row in endings}
        if len(outcomes_in_group) != 1:
            summary["conflicting_outcome_groups_excluded"] += 1
            continue
        outcome = endings[-1].get("outcome")
        outcomes[outcome] += 1
        summary["completed_v23_battles"] += 1
        is_loss = outcome == "失败"
        old_policy = old_module.RandomDeckStrategy(stamp(rows[0]))
        new_policy = current.RandomDeckStrategy(stamp(rows[0]))
        last_spell = {}
        for row in rows:
            if (
                row.get("event") not in {"play", "strategy_observe"}
                or not row.get("hand")
                or not row.get("cues")
            ):
                continue
            now = stamp(row)
            hand, scene = row["hand"], row["cues"]
            recorded = row.get("decision") or {}
            old_decision = old_policy.decide(hand, scene, now)
            new_decision = new_policy.decide(hand, scene, now)
            summary["logged_scenes_replayed"] += 1
            if row.get("event") == "play" and recorded:
                summary["logged_play_scenes"] += 1
                summary["old_reproduced_recorded_action"] += same_action(
                    old_decision, recorded
                )
                available = reliable_available(hand)
                role = role_for(
                    recorded.get("mirrored_card")
                    or recorded.get("variant")
                    or recorded.get("card"),
                    recorded.get("cost"),
                )
                air = [
                    (item, card)
                    for item, card in available
                    if card.air
                    and card.role in {"fighter", "swarm", "ranged", "building", "cycle"}
                ]
                category = recorded.get("category")
                air_candidate = bool(
                    is_loss
                    and scene.get("far_warnings")
                    and not recorded.get("target")
                    and role
                    and role.air
                    and category in {"cycle", "support", "prepare", "attack"}
                    and len(air) == 1
                )
                if air_candidate:
                    entry = minimal_air_replay(old_module, rows, row)
                    entry["prefix_replay"] = comparison(
                        row, old_policy, new_policy, old_decision, new_decision
                    )
                    air_cases.append(entry)
                elixir = scene.get("elixir", row.get("elixir"))
                other_costs = [
                    card.cost
                    for _, card in available
                    if card.role in {"fighter", "swarm", "ranged", "building", "cycle"}
                    and card.name != recorded.get("card")
                ]
                if (
                    is_loss
                    and scene.get("far_warnings")
                    and category not in {"defense", "spell", "building"}
                    and isinstance(elixir, (int, float))
                    and other_costs
                    and elixir - recorded.get("cost", 0) < min(other_costs)
                ):
                    entry = comparison(
                        row, old_policy, new_policy, old_decision, new_decision
                    )
                    entry["logged_remaining_elixir"] = elixir - recorded.get("cost", 0)
                    entry["cheapest_other_available_defender"] = min(other_costs)
                    entry[
                        "new_preserves_declared_reserve_or_defends_current_target"
                    ] = bool(
                        new_decision is None
                        or new_decision.target is not None
                        or elixir - new_decision.cost >= new_decision.reserve
                    )
                    entry[
                        "new_preserves_original_other_defender_cost_or_defends_current_target"
                    ] = bool(
                        new_decision is None
                        or new_decision.target is not None
                        or elixir - new_decision.cost >= min(other_costs)
                    )
                    budget_cases.append(entry)
                if (
                    recorded.get("target")
                    and category == "spell"
                    and row.get("confirmed") is True
                ):
                    last_spell[recorded.get("lane")] = row
                for module, policy in ((old_module, old_policy), (current, new_policy)):
                    policy.record(
                        actual_decision(module, row), row.get("confirmed") is True, now
                    )
            elif is_loss and "已有可见友军接敌" in (row.get("observation") or {}).get(
                "reason", ""
            ):
                nearby = [
                    prior
                    for prior in last_spell.values()
                    if 0 <= now - stamp(prior) <= 2
                ]
                if nearby:
                    entry = minimal_spell_replay(old_module, nearby[-1], row)
                    entry["prefix_replay"] = comparison(
                        row, old_policy, new_policy, old_decision, new_decision
                    )
                    spell_cases.append(entry)
            if (
                len(full_replay_examples) < 8
                and is_loss
                and decision_dict(old_decision) != decision_dict(new_decision)
            ):
                full_replay_examples.append(
                    comparison(row, old_policy, new_policy, old_decision, new_decision)
                )

    def battles(cases):
        return len({(case["session"], case["battle"]) for case in cases})

    reproduced_air = [
        case for case in air_cases if case["old_reproduced_logged_action"]
    ]
    summary.update(
        {
            "loss_air_candidate_occurrences": len(air_cases),
            "loss_air_candidate_battles": battles(air_cases),
            "minimal_air_old_reproduced_occurrences": len(reproduced_air),
            "minimal_air_old_reproduced_battles": battles(reproduced_air),
            "minimal_air_reproduced_unsafe_spends_blocked_or_currently_defended": sum(
                not case["unsafe_same_air_spend_survives"] for case in reproduced_air
            ),
            "minimal_air_all_candidate_unsafe_spends_surviving": sum(
                case["unsafe_same_air_spend_survives"] for case in air_cases
            ),
            "loss_spell_hold_candidate_occurrences": len(spell_cases),
            "loss_spell_hold_candidate_battles": battles(spell_cases),
            "minimal_spell_old_reproduced_cases": sum(
                case["old_reproduced_at_feasible_probe"] for case in spell_cases
            ),
            "minimal_spell_new_responds_at_every_old_hold_probe": sum(
                case["new_responds_at_every_old_hold_probe"] for case in spell_cases
            ),
            "minimal_spell_false_persistent_hold_removed": sum(
                case["new_spell_based_persistent_hold_removed"] for case in spell_cases
            ),
            "loss_budget_candidate_occurrences": len(budget_cases),
            "loss_budget_candidate_battles": battles(budget_cases),
            "prefix_budget_safe_or_current_target_defense": sum(
                case["new_preserves_declared_reserve_or_defends_current_target"]
                for case in budget_cases
            ),
            "prefix_budget_original_other_defender_cost_kept_or_current_target_defense": sum(
                case[
                    "new_preserves_original_other_defender_cost_or_defends_current_target"
                ]
                for case in budget_cases
            ),
            "prefix_budget_old_reproduced_occurrences": sum(
                case["old_reproduced_logged_action"] for case in budget_cases
            ),
            "prefix_budget_original_other_defender_cost_violations": sum(
                not case[
                    "new_preserves_original_other_defender_cost_or_defends_current_target"
                ]
                for case in budget_cases
            ),
            "prefix_budget_old_reproduced_original_cost_kept_or_current_target_defense": sum(
                case["old_reproduced_logged_action"]
                and case[
                    "new_preserves_original_other_defender_cost_or_defends_current_target"
                ]
                for case in budget_cases
            ),
        }
    )
    report = {
        "source": str(SOURCE),
        "source_bytes": SOURCE.stat().st_size,
        "source_sha256": source_digest.hexdigest(),
        "source_line_count": line_no,
        "parse_errors": parse_errors,
        "old_source": str(BACKUP),
        "old_source_sha256": hashlib.sha256(BACKUP.read_bytes()).hexdigest(),
        "new_source": str(Path(current.__file__)),
        "new_source_sha256": hashlib.sha256(
            Path(current.__file__).read_bytes()
        ).hexdigest(),
        "old_version": old_module.STRATEGY_VERSION,
        "new_version": current.STRATEGY_VERSION,
        "summary": dict(summary),
        "completed_outcomes": dict(outcomes),
        "limitations": [
            "Only completed v2.3 battles are included; candidate failure scenarios retain session and battle identity.",
            "Wall-clock timestamps have one-second resolution and intermediate unlogged frames are unavailable.",
            "Action reproduction is defined as the same card, hand slot and decision category; it is not a pixel-exact replay of deployment coordinates.",
            "Prefix comparison feeds the exact logged hand/cues and actual confirmed/unconfirmed outcomes to both policies; hypothetical new actions never alter later observations.",
            "Minimal air comparisons restore only earlier actual deployment records and the selected exact logged scene; they do not reconstruct hidden pressure tracks.",
            "Minimal spell comparisons probe explicit feasible elapsed offsets in the one-second timestamp interval; these offsets are not measured timing.",
            "Candidate counts describe logged decision patterns, not proof that a pattern alone caused a defeat.",
            "This is a rule regression audit and makes no counterfactual outcome or win-rate claim.",
        ],
        "air_cases": air_cases,
        "spell_cases": spell_cases,
        "budget_cases": budget_cases,
        "full_replay_examples": full_replay_examples,
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "decision-replay.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "summary": report["summary"],
                "completed_outcomes": report["completed_outcomes"],
            },
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    main()
