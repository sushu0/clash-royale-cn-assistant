"""Read only random battle corpus; persist scoped audit derivatives."""

import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(r"D:\codex\CodexWork\clash")
SOURCE = ROOT / "outputs/cn-random-mastery.jsonl"
OUT = ROOT / "work/loss-optimization-20261004/agent-evidence"
sys.path.insert(0, str(ROOT / "py-clash-bot"))
from pyclashbot.bot.random_card_roles import role_for  # noqa: E402


def stamp(row):
    return datetime.strptime(row["time"], "%Y-%m-%d %H:%M:%S").timestamp()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


cache = {}


def evidence_status(evidence):
    if not isinstance(evidence, dict) or not evidence.get("path"):
        return "not_recorded"
    key = (evidence["path"], evidence.get("sha256"))
    if key not in cache:
        path = Path(key[0])
        cache[key] = "missing" if not path.is_file() else (
            "hash_matches" if key[1] and digest(path) == key[1] else "hash_mismatch" if key[1] else "exists_no_hash"
        )
    return cache[key]


groups = defaultdict(list)
events = Counter()
errors = []
with SOURCE.open("rb") as stream:
    for lineno, raw in enumerate(stream, 1):
        try:
            row = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            errors.append({"line": lineno, "error": str(exc)})
            continue
        events[row.get("event")] += 1
        battle = row.get("finished_battle", row.get("battle")) if row.get("event") == "battle_finished" else row.get("battle")
        if not isinstance(battle, int):
            continue
        row["source_line"] = lineno
        groups[(row.get("session"), battle)].append(row)

records = []
samples = defaultdict(list)
policy_counts = defaultdict(Counter)
all_outcomes = Counter()
recent_scenarios = Counter()
per_loss_scenarios = Counter()
result_statuses = Counter()
evidence_statuses = Counter()
rows_by_loss = {}


def sample(kind, row, session, battle, **detail):
    recent_scenarios[kind] += 1
    if len(samples[kind]) < 8:
        samples[kind].append({"session": session, "battle": battle, **detail, "trace": row})


for (session, battle), rows in reversed(list(groups.items())):
    endings = [r for r in rows if r.get("event") == "battle_finished"]
    if not endings:
        continue
    outcomes = {r.get("outcome") for r in endings}
    end = endings[-1]
    outcome = end.get("outcome") if len(outcomes) == 1 else "conflicting"
    all_outcomes[outcome] += 1
    policy_counts[end.get("policy")][outcome] += 1
    if outcome != "失败":
        continue
    plays = [r for r in rows if r.get("event") == "play"]
    observes = [r for r in rows if r.get("event") == "strategy_observe"]
    proof_rows = [r for r in rows if r.get("event") in {"battle_started", "battle_observed", "play_evidence", "selection_evidence", "battle_finished"}]
    proof_counts = Counter(evidence_status(r.get("evidence")) for r in proof_rows)
    evidence_statuses.update(proof_counts)
    result_status = evidence_status(end.get("evidence"))
    result_statuses[result_status] += 1
    version = (end.get("experiment") or {}).get("rule_version") or next(
        (r.get("strategy_version") for r in reversed(plays) if r.get("strategy_version")), None
    )
    confirmed = sum(r.get("confirmed") is True for r in plays)
    unconfirmed = sum(r.get("confirmed") is False for r in plays)
    record = {
        "session": session, "battle": battle, "time": end.get("time"), "policy": end.get("policy"),
        "rule_version": version, "outcome": outcome, "result_evidence_status": result_status,
        "result_evidence_path": (end.get("evidence") or {}).get("path"),
        "result_sha256": (end.get("evidence") or {}).get("sha256"),
        "attempts_at_end": end.get("card_attempts"), "confirmed_at_end": end.get("cards_confirmed"),
        "play_trace_count": len(plays), "confirmed_play_trace_count": confirmed,
        "unconfirmed_play_trace_count": unconfirmed, "observe_count": len(observes),
        "decision_trace_count": sum(bool(r.get("decision")) for r in plays),
        "proof_trace_count": len(proof_rows), "proof_hash_matches": proof_counts["hash_matches"],
        "proof_hash_mismatch": proof_counts["hash_mismatch"], "proof_missing": proof_counts["missing"],
        "play_frame_hash_matches": sum(evidence_status(r.get("evidence")) == "hash_matches" for r in proof_rows if r.get("event") == "play_evidence"),
        "source_first_line": rows[0]["source_line"], "source_result_line": end["source_line"],
    }
    records.append(record)
    rows_by_loss[(session, battle)] = rows
    if version != "random-rules-v2.3-20261003-evidence-gates":
        continue
    kinds = set()
    last_defense = {}
    last_target_spell = {}
    last_building = None
    for row in rows:
        event = row.get("event")
        cues = row.get("cues") or {}
        hand = row.get("hand") or []
        decision = row.get("decision") or {}
        elixir = cues.get("elixir", row.get("elixir"))
        available = []
        for item in hand:
            role = role_for(item.get("variant") or item.get("card"), item.get("cost"))
            if role and item.get("available") is True:
                available.append((item, role))
        if event == "play":
            cat = decision.get("category", row.get("category"))
            card = role_for(decision.get("mirrored_card") or decision.get("variant") or decision.get("card"), decision.get("cost"))
            lane = decision.get("lane")
            now = stamp(row)
            is_defense = cat in {"defense", "building"} and decision.get("target")
            if cues.get("far_warnings") and not decision.get("target") and card and card.air and cat in {"cycle", "support", "prepare", "attack"}:
                anti_air = [c.name for _, c in available if c.air and c.role in {"fighter", "swarm", "ranged", "building", "cycle"}]
                if len(anti_air) == 1:
                    kind = "far_warning_spends_only_available_anti_air"
                    kinds.add(kind)
                    sample(kind, row, session, battle, anti_air=anti_air)
            if cues.get("far_warnings") and cat not in {"defense", "spell", "building"} and isinstance(elixir, (float, int)):
                costs = [c.cost for _, c in available if c.role in {"fighter", "swarm", "ranged", "building", "cycle"} and c.name != decision.get("card")]
                if costs and elixir - decision.get("cost", 0) < min(costs):
                    kind = "far_warning_reserve_below_other_available_defender_cost"
                    kinds.add(kind)
                    sample(kind, row, session, battle, remaining_elixir=elixir - decision.get("cost", 0), cheapest_other_available_defender=min(costs))
            if is_defense:
                previous = last_defense.get(lane)
                if previous and now - stamp(previous) <= 3:
                    kind = "same_lane_repeat_defense_within_3_seconds"
                    kinds.add(kind)
                    sample(kind, row, session, battle, previous=previous)
                last_defense[lane] = row
            if cat == "building" and row.get("confirmed") is True:
                if last_building and now - stamp(last_building) <= 10:
                    kind = "repeat_building_within_10_seconds"
                    kinds.add(kind)
                    sample(kind, row, session, battle, previous_building=last_building)
                last_building = row
            if decision.get("target") and cat == "spell" and row.get("confirmed") is True:
                last_target_spell[lane] = row
        elif event == "strategy_observe":
            reason = (row.get("observation") or {}).get("reason", "")
            if "已有可见友军接敌" in reason:
                nearby = [r for r in last_target_spell.values() if 0 <= stamp(row) - stamp(r) <= 2]
                if nearby:
                    kind = "hold_visible_allies_after_confirmed_spell_within_2_seconds"
                    kinds.add(kind)
                    sample(kind, row, session, battle, previous_spell=nearby[-1])
            if elixir == 10:
                kind = "full_elixir_hold_observation"
                kinds.add(kind)
                sample(kind, row, session, battle)
            if cues.get("threats") and "无法覆盖目标" in reason:
                kind = "typed_threat_no_cover_hold"
                kinds.add(kind)
                sample(kind, row, session, battle)
    record["scenarios"] = ";".join(sorted(kinds))
    per_loss_scenarios.update(kinds)

records.sort(key=lambda r: (r["time"], r["session"], r["battle"]))
fields = list(dict.fromkeys(k for r in records for k in r))
with (OUT / "all-random-losses.csv").open("w", encoding="utf-8-sig", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(records)
(OUT / "v23-scenario-samples.json").write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")
summary = {
    "source": str(SOURCE), "source_bytes": SOURCE.stat().st_size, "source_sha256": digest(SOURCE),
    "line_count": lineno, "parse_errors": errors, "event_counts": events,
    "completed_unique_outcomes": all_outcomes, "loss_count": len(records), "policy_outcomes": policy_counts,
    "loss_result_evidence_statuses": result_statuses, "loss_proof_evidence_statuses": evidence_statuses,
    "losses_with_play_trace": sum(bool(r["play_trace_count"]) for r in records),
    "losses_with_decision_trace": sum(bool(r["decision_trace_count"]) for r in records),
    "losses_with_verified_result_and_decision_trace": sum(r["result_evidence_status"] == "hash_matches" and bool(r["decision_trace_count"]) for r in records),
    "losses_with_at_least_one_verified_play_frame": sum(bool(r["play_frame_hash_matches"]) for r in records),
    "losses_with_verified_result_and_play_frame": sum(r["result_evidence_status"] == "hash_matches" and bool(r["play_frame_hash_matches"]) for r in records),
    "proof_events_scope": ["battle_started", "battle_observed", "play_evidence", "selection_evidence", "battle_finished"],
    "v23_losses": sum(r["rule_version"] == "random-rules-v2.3-20261003-evidence-gates" for r in records),
    "v23_scenario_occurrences": recent_scenarios, "v23_losses_by_scenario": per_loss_scenarios,
    "limitations": [
        "Observed trace scenarios indicate reproducible decision patterns; they do not establish sole causal attribution for a loss.",
        "Ring screenshots can exist yet have a different hash; only matching recorded hashes are valid evidence for the recorded frame.",
        "Play screenshots are sampled, not continuous video. Exact second timestamps have one-second resolution.",
        "Unique completed battle identity follows session and finished_battle; incomplete battles are excluded.",
    ],
}
(OUT / "random-loss-audit.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({k: v for k, v in summary.items() if k not in {"event_counts", "policy_outcomes", "limitations"}}, ensure_ascii=False, indent=2))
