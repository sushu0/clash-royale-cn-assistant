"""Read-only, session-scoped battle analysis with hash-verified screenshot evidence.

The only writes are reports and immutable evidence copies under this task's work/
or an explicitly supplied report path under outputs/. No bot control is performed.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
FORMAT = "%Y-%m-%d %H:%M:%S"
COSTS = {"hog": 4, "musketeer": 4, "cannon": 3, "fireball": 4,
         "ice_golem": 2, "log": 2, "ice_spirit": 1, "skeletons": 1}
COUNTER_REASONS = ("单个浅层压力，野猪施压并保留3费", "已有核心覆盖小股压力，野猪反打并保留2费")
TYPED_REASONS = ("已确认近场空中威胁，优先火枪输出", "已确认近场冲塔威胁，及时中置炮牵引",
                 "冲塔防守缺少炮与低费牌，火枪补充输出")


def timestamp(value: str) -> float:
    return datetime.strptime(value, FORMAT).timestamp()


def read_bot_state() -> dict:
    """Inspect recorded bot processes only; never start, stop or signal them."""
    pid_path = ROOT / "work/bot-processes.json"
    try:
        pids = json.loads(pid_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"state": "unknown", "reason": "PID manifest unavailable"}
    processes = {}
    for name, script in (("watchdog", "watch_cn_1v1.py"), ("runner", "run_cn_1v1.py")):
        pid = pids.get(name + "_pid")
        try:
            process = psutil.Process(int(pid))
            present = process.is_running() and script in " ".join(process.cmdline())
        except (psutil.NoSuchProcess, psutil.ZombieProcess, TypeError, ValueError):
            present = False
        except psutil.AccessDenied:
            present = None
        processes[name] = {"pid": pid, "matching_bot_process_running": present}
    states = [item["matching_bot_process_running"] for item in processes.values()]
    state = "unknown" if None in states else "running" if all(states) else "starting" if states[0] else "stopped"
    return {"state": state, "checked_at": datetime.now().strftime(FORMAT), "processes": processes,
            "method": "Read-only inspection of the two PIDs in bot-processes.json, matching expected script names"}


def compare_frozen_files(manifest: dict | None) -> dict:
    if not manifest:
        return {"all_sources_match": False, "all_assets_match": False, "reason": "Manifest unavailable"}
    repo = ROOT / "py-clash-bot/pyclashbot"
    source_dirs = {"cn_1v1_loop.py": "bot", "hog_cycle_strategy.py": "bot", "coords.py": "bot",
                   "elite_ice_golem_ability.py": "bot", "cn_battle_cues.py": "detection", "cn_threats.py": "detection"}
    sources, assets = {}, {}
    for name, expected in manifest.get("source_sha256", {}).items():
        path = repo / source_dirs[name] / name if name in source_dirs else None
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if path and path.is_file() else None
        sources[name] = {"path": str(path) if path else None, "runtime_manifest_sha256": expected,
                         "current_disk_sha256": actual, "matches": actual == expected}
    image_root = repo / "detection/reference_images"
    for name, expected in manifest.get("asset_sha256", {}).items():
        path = image_root / name
        allowed = path.resolve().is_relative_to(image_root.resolve())
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if allowed and path.is_file() else None
        assets[name] = {"path": str(path), "runtime_manifest_sha256": expected,
                        "current_disk_sha256": actual, "matches": actual == expected}
    return {"checked_at": datetime.now().strftime(FORMAT), "sources": sources, "assets": assets,
            "all_sources_match": bool(sources) and all(item["matches"] for item in sources.values()),
            "all_assets_match": bool(assets) and all(item["matches"] for item in assets.values()),
            "note": "Current disk hashes are compared separately; original runtime hashes remain unchanged."}


def verify_evidence(evidence: dict | None, session: str, pin: bool = False) -> dict:
    """Never interpret a rotating filename as evidence without matching its hash."""
    if not evidence or not evidence.get("path") or not evidence.get("sha256"):
        return {"status": "unavailable"}
    expected = evidence["sha256"]
    if not isinstance(expected, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", expected):
        return {"status": "invalid_expected_hash"}
    source = Path(evidence["path"])
    result = {"path": str(source), "expected_sha256": expected, "sequence": evidence.get("sequence")}
    try:
        source.resolve().relative_to(ROOT.resolve())
        data = source.read_bytes()
    except (OSError, ValueError) as error:
        data = None
        result.update(status="missing_or_outside_task", error=type(error).__name__)
    if data is not None:
        actual = hashlib.sha256(data).hexdigest()
        result["current_sha256"] = actual
        result["status"] = "verified" if actual == expected else "overwritten_or_mismatched"
    pinned = ROOT / "work/hog-v3-verified-evidence" / session / (expected + ".png")
    if result["status"] == "verified" and pin:
        pinned.parent.mkdir(parents=True, exist_ok=True)
        if not pinned.exists():
            pinned.write_bytes(data)
        if hashlib.sha256(pinned.read_bytes()).hexdigest() == expected:
            result["verified_copy"] = str(pinned)
    elif pinned.is_file() and hashlib.sha256(pinned.read_bytes()).hexdigest() == expected:
        result["verified_copy"] = str(pinned)
        result["status"] = "verified_from_prior_copy"
    return result


def analyze(rows: list[dict], starts: dict[int, float]) -> dict:
    plays = [row for row in rows if row["event"] == "play"]
    confirmed = [row for row in plays if row["confirmed"]]
    ended = [row for row in rows if row["event"] == "battle_end"]
    costs = Counter()
    for row in confirmed:
        costs[row["decision"]["category"]] += COSTS[row["decision"]["card"]]
    battle_rows, gaps = [], []
    for end in ended:
        battle = end["battle"]
        cp = [row for row in confirmed if row["battle"] == battle]
        hogs = [row for row in cp if row["decision"]["card"] == "hog"]
        begin = starts[battle]
        finish = timestamp(end["time"])
        points = [begin] + [timestamp(row["time"]) for row in hogs] + [finish]
        bgaps = [{"battle": battle, "from": datetime.fromtimestamp(a).strftime(FORMAT),
                  "to": datetime.fromtimestamp(b).strftime(FORMAT), "seconds": b-a}
                 for a, b in zip(points, points[1:])]
        gaps.extend(bgaps)
        battle_rows.append({"battle": battle, "start": datetime.fromtimestamp(begin).strftime(FORMAT),
                            "end": end["time"], "seconds": finish-begin, "automatic_result": end["result"],
                            "attempts": end["attempts"], "confirmed": end["confirmed"], "hog_count": len(hogs),
                            "longest_no_hog_seconds": max(g["seconds"] for g in bgaps)})
    seconds = sum(row["seconds"] for row in battle_rows)
    hog_count = sum(row["decision"]["card"] == "hog" for row in confirmed)
    defense = [row for row in confirmed if row["decision"]["category"] == "defense"]
    cheap = [row for row in defense if COSTS[row["decision"]["card"]] == 1]
    abilities = [row for row in rows if row["event"] == "elite_ability"]
    cue_rows = [row for row in rows if isinstance(row.get("cues"), dict)]
    threat_rows = [(row, threat) for row in cue_rows for threat in row["cues"].get("threats", [])
                   if isinstance(threat, dict)]
    typed_plays = [row for row in plays if row["decision"].get("threat_kind")]
    typed_confirmed = [row for row in typed_plays if row["confirmed"]]
    by_template = {}
    for _, threat in threat_rows:
        template = threat.get("template_id", "unknown_template")
        record = by_template.setdefault(template, {"observations": 0, "kinds": set(), "scores": [], "thresholds": set()})
        record["observations"] += 1
        record["kinds"].add(threat.get("kind", "unknown"))
        if isinstance(threat.get("confidence"), (int, float)):
            record["scores"].append(threat["confidence"])
        if isinstance(threat.get("confidence_threshold"), (int, float)):
            record["thresholds"].add(threat["confidence_threshold"])
    template_summary = {
        template: {"observations": record["observations"], "kinds": sorted(record["kinds"]),
                   "similarity_min": min(record["scores"]) if record["scores"] else None,
                   "similarity_max": max(record["scores"]) if record["scores"] else None,
                   "recorded_match_thresholds": sorted(record["thresholds"])}
        for template, record in by_template.items()
    }
    return {
        "completed": len(ended), "automatic_outcomes": dict(Counter(row["result"] for row in ended)),
        "attempts": len(plays), "confirmed": len(confirmed),
        "confirmation_rate": len(confirmed)/len(plays) if plays else None,
        "battle_minutes": seconds/60, "hog_count": hog_count,
        "hogs_per_minute": hog_count*60/seconds if seconds else None,
        "nominal_spend_by_category": dict(costs),
        "defense_spell_cost_share": (costs["defense"]+costs["spell"])/sum(costs.values()) if costs else None,
        "one_elixir_defense_confirmed": len(cheap), "defense_confirmed": len(defense),
        "one_elixir_defense_share": len(cheap)/len(defense) if defense else None,
        "new_counter_rules": {reason: {"attempts": sum(row["decision"]["reason"] == reason for row in plays),
                                      "confirmed": sum(row["decision"]["reason"] == reason for row in confirmed)} for reason in COUNTER_REASONS},
        "threat_classification": {
            "cue_events": len(cue_rows), "events_with_typed_matches": sum(bool(row["cues"].get("threats")) for row in cue_rows),
            "events_with_enemy_markers_but_no_typed_match": sum(bool(row["cues"].get("enemies")) and not row["cues"].get("threats") for row in cue_rows),
            "observations_by_kind": dict(Counter(threat.get("kind", "unknown") for _, threat in threat_rows)),
            "observations_by_template": template_summary,
            "typed_observation_examples": [{"battle": row["battle"], "time": row["time"],
                                             "trace_line": row.get("trace_line"), "event": row["event"],
                                             "threat": threat,
                                             "evidence": row.get("evidence_before") or row.get("evidence")}
                                            for row, threat in threat_rows[:24]],
            "decision_attempts_by_threat_kind": dict(Counter(row["decision"]["threat_kind"] for row in typed_plays)),
            "confirmed_decisions_by_threat_kind": dict(Counter(row["decision"]["threat_kind"] for row in typed_confirmed)),
            "confirmed_card_by_threat_kind": dict(Counter(row["decision"]["threat_kind"]+"/"+row["decision"]["card"] for row in typed_confirmed)),
            "typed_rule_reasons": {reason: {"attempts": sum(row["decision"]["reason"] == reason for row in plays),
                                            "confirmed": sum(row["decision"]["reason"] == reason for row in confirmed)} for reason in TYPED_REASONS},
            "typed_decision_events": [{"battle": row["battle"], "time": row["time"], "trace_line": row.get("trace_line"),
                                       "decision": row["decision"], "confirmed": row["confirmed"],
                                       "observed_threats": row["cues"].get("threats", []), "evidence_before": row.get("evidence_before")}
                                      for row in typed_plays],
            "interpretation": "Counts are repeated logged observations/actions, not unique enemy units. No match leaves enemy type unknown, not absent. Similarity thresholds such as 0.74 are template correlation cutoffs, never probabilities."},
        "skill_attempts": len(abilities), "skill_confirmed": sum(row["confirmed"] for row in abilities),
        "longest_no_hog_interval": max(gaps, key=lambda gap: gap["seconds"]) if gaps else None,
        "no_hog_intervals_at_least_60_seconds": [gap for gap in gaps if gap["seconds"] >= 60],
        "confirmed_reasons": dict(Counter(row["decision"]["reason"] for row in confirmed)),
        "battles": battle_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, help="Session identifier YYYYMMDD-HHMMSS")
    parser.add_argument("--output", type=Path, help="Default: work/hog-v3-live-SESSION.json")
    parser.add_argument("--reviews", type=Path, help="Optional list of session/battle/sha256/result/score/reviewer manual reviews")
    parser.add_argument("--max-completed", type=int, help="Limit a stage report to the first N eligible completed battles")
    args = parser.parse_args()
    if not re.fullmatch(r"\d{8}-\d{6}", args.session):
        parser.error("Invalid session identifier")
    if args.max_completed is not None and args.max_completed < 1:
        parser.error("--max-completed must be positive")
    destination = args.output or ROOT / f"work/hog-v3-live-{args.session}.json"
    if not destination.is_absolute():
        destination = ROOT / destination
    if not any(destination.resolve().is_relative_to((ROOT / name).resolve()) for name in ("work", "outputs")):
        parser.error("Report must stay under this task's work/ or outputs/")
    trace_bytes = (ROOT / "outputs/cn-hog-strategy.jsonl").read_bytes()
    log_bytes = (ROOT / "outputs/cn-battles-live.log").read_bytes()
    rows, partial_line_ignored = [], False
    lines = trace_bytes.decode("utf-8").splitlines()
    for index, line in enumerate(lines):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            if index == len(lines)-1:
                partial_line_ignored = True
                continue
            raise
        if row.get("session") == args.session:
            row["trace_line"] = index+1
            rows.append(row)
    starts, resumed, recoveries, runtime_hashes, start_records, lobby_returns, end_records = {}, set(), [], None, {}, [], {}
    active, resume = False, False
    for line_no, line in enumerate(log_bytes.decode("utf-8").splitlines(), 1):
        if "连续对战已启动" in line:
            active = datetime.strptime(line[:19], FORMAT).strftime("%Y%m%d-%H%M%S") == args.session
        if not active:
            continue
        if "策略源码校验: " in line:
            runtime_hashes = ast.literal_eval(line.split("策略源码校验: ", 1)[1])
        if "恢复事件：接管" in line:
            resume = True
        match = re.search(r"对战开始 场次=(\d+)", line)
        if match:
            battle = int(match[1])
            starts[battle] = timestamp(line[:19])
            start_records[battle] = {"battle": battle, "time": line[:19], "line": line_no, "text": line}
            if resume:
                resumed.add(battle)
            resume = False
        if "恢复/重启" in line:
            recoveries.append({"line": line_no, "time": line[:19], "text": line})
        if "即时奖励已处理，返回大厅" in line:
            lobby_returns.append({"line": line_no, "time": line[:19], "text": line})
        end_match = re.search(r"对战结束 .*已完成=(\d+) 连续完成=(\d+)", line)
        if end_match:
            end_records[int(end_match[1])] = {"line": line_no, "time": line[:19], "text": line,
                                              "consecutive_completed": int(end_match[2])}
    ends = [row for row in rows if row["event"] == "battle_end"]
    no_play = {row["battle"] for row in ends if row.get("confirmed", 0) <= 0}
    eligible = sorted((row for row in ends if row["battle"] in starts and row["battle"] not in resumed
                       and row["battle"] not in no_play), key=lambda row: (row["time"], row["battle"]))
    chosen = eligible[:args.max_completed] if args.max_completed is not None else eligible
    cutoff = max((row["time"] for row in chosen), default=None)
    complete = {row["battle"] for row in chosen}
    selected = [row for row in rows if row.get("battle") in complete and cutoff and row["time"] <= cutoff]
    metrics = analyze(selected, starts)
    if metrics["attempts"] != sum(row["attempts"] for row in metrics["battles"]):
        raise ValueError("Trace/log attempt mismatch; inspect a recovered or duplicated battle before reporting")
    if metrics["confirmed"] != sum(row["confirmed"] for row in metrics["battles"]):
        raise ValueError("Trace/log confirmation mismatch")
    evidence_counts, result_evidence = Counter(), []
    for row in selected:
        for field in ("evidence", "evidence_before", "evidence_after"):
            if field not in row:
                continue
            verified = verify_evidence(row[field], args.session, pin=row["event"] == "battle_end")
            evidence_counts[verified["status"]] += 1
            if row["event"] == "battle_end":
                result_evidence.append({"battle": row["battle"], "automatic_result": row["result"], **verified})
    reviews_path = args.reviews or ROOT / f"work/hog-v3-reviews-{args.session}.json"
    accepted, rejected, outside_snapshot, seen_reviews = [], [], [], set()
    for review in json.loads(reviews_path.read_text(encoding="utf-8")) if reviews_path.is_file() else []:
        if review.get("session") == args.session and review.get("battle") not in complete:
            outside_snapshot.append(review)
            continue
        evidence = next((item for item in result_evidence if item["battle"] == review.get("battle")), None)
        valid = (review.get("session") == args.session and review.get("battle") not in seen_reviews
                 and review.get("result") in ("胜利", "失败", "未知")
                 and evidence and evidence.get("expected_sha256") == review.get("sha256")
                 and evidence["status"] in ("verified", "verified_from_prior_copy"))
        (accepted if valid else rejected).append(review)
        if valid:
            seen_reviews.add(review["battle"])
    reviewed_ids = {review["battle"] for review in accepted}
    baseline_full = json.loads((ROOT / "work/v3-trace-audit.json").read_text(encoding="utf-8"))
    baseline = next(session for session in baseline_full["sessions"] if session["session"] == "20260926-005724")
    baseline_fields = ("session", "completed", "automatic_outcomes", "attempts", "confirmed", "confirmation_rate",
                       "battle_minutes", "hog_count", "hogs_per_minute", "nominal_spend_by_category",
                       "defense_spell_cost_share", "skill_attempts", "skill_confirmed", "runtime_hashes")
    baseline_summary = {key: baseline[key] for key in baseline_fields}
    baseline_summary["longest_no_hog_seconds"] = max(gap["seconds"] for gap in baseline["long_no_hog_spans"])
    manifest_path = ROOT / "work/hog-validation" / args.session / "policy-manifest.json"
    manifest_bytes = manifest_path.read_bytes() if manifest_path.is_file() else None
    manifest = json.loads(manifest_bytes) if manifest_bytes else None
    monitor_path = ROOT / f"work/{args.session}-monitor.json"
    monitor_bytes = monitor_path.read_bytes() if monitor_path.is_file() else None
    monitor = json.loads(monitor_bytes) if monitor_bytes else None
    pilots = []
    for pilot_session in ("20260926-115400", "20260926-122831", "20260926-125136"):
        pilot_path = ROOT / f"work/hog-v3-live-{pilot_session}.json"
        if args.session > pilot_session and pilot_path.is_file():
            pilot_full = json.loads(pilot_path.read_text(encoding="utf-8"))
            pilots.append({"session": pilot_session, "role": "Separate earlier pilot; excluded from primary test metrics",
                           "source_report": str(pilot_path), "metrics": pilot_full["metrics"],
                           "independent_screenshot_reviews": pilot_full["independent_screenshot_reviews"],
                           "post_battle_continuations": pilot_full.get("post_battle_continuations", []),
                           "recovery_events": pilot_full.get("recovery_events_in_session_snapshot", []),
                           "runtime_source_hashes": pilot_full["runtime_source_hashes_from_log"]})
    transitions = []
    for end in ends:
        if end["battle"] not in complete:
            continue
        next_start = next((record for _, record in sorted(start_records.items()) if record["time"] > end["time"]), None)
        boundary = next_start["time"] if next_start else (rows[-1]["time"] if rows else end["time"])
        subsequent_rewards = [row for row in rows if row["event"] == "reward" and end["time"] <= row["time"] <= boundary]
        verified_rewards = [{**row, "evidence_verification": verify_evidence(row.get("evidence"), args.session, pin=True)}
                            for row in subsequent_rewards]
        subsequent_unknown = [row for row in rows if row["event"] == "screen_unknown" and end["time"] <= row["time"] <= boundary]
        subsequent_recoveries = [event for event in recoveries if end["time"] <= event["time"] <= boundary]
        subsequent_lobby = [event for event in lobby_returns if end["time"] <= event["time"] <= boundary]
        review = next((review for review in accepted if review["battle"] == end["battle"]), None)
        transitions.append({"battle": end["battle"], "ended_at": end["time"],
                            "automatic_result": end["result"], "independently_reviewed_result": review["result"] if review else None,
                            "next_battle_start": next_start,
                            "seconds_to_next_battle": timestamp(next_start["time"])-timestamp(end["time"]) if next_start else None,
                            "reward_events": verified_rewards, "reward_return_lobby_logs": subsequent_lobby,
                            "recovery_events": subsequent_recoveries,
                            "unknown_screen_events": len(subsequent_unknown),
                            "last_unknown_screen": {
                                "time": subsequent_unknown[-1]["time"], "state": subsequent_unknown[-1].get("state"),
                                "evidence": verify_evidence(subsequent_unknown[-1].get("evidence"), args.session, pin=True)
                            } if subsequent_unknown else None,
                            "next_battle_started_without_logged_recovery": bool(next_start and not subsequent_recoveries)})
    report = {
        "created_at": datetime.now().strftime(FORMAT), "session": args.session,
        "primary_test_scope": {"only_session": args.session, "target_complete_battles": 10,
                               "target_reached": metrics["completed"] >= 10, "pilot_included": False,
                               "requested_snapshot_limit": args.max_completed},
        "policy_versions_in_trace": sorted({row["policy_version"] for row in rows}),
        "last_complete_battle_cutoff": cutoff, "metrics": metrics, "baseline_203": baseline_summary,
        "excluded_resumed_battles": sorted(resumed),
        "excluded_completed_no_play_battles": sorted(no_play),
        "excluded_completed_beyond_snapshot_limit": sorted({row["battle"] for row in eligible}-complete),
        "excluded_incomplete_battles": sorted({row["battle"] for row in rows if "battle" in row} - {row["battle"] for row in ends}),
        "recovery_events_through_cutoff": [item for item in recoveries if cutoff and item["time"] <= cutoff],
        "recovery_events_after_last_completed_battle": [item for item in recoveries if cutoff and item["time"] > cutoff],
        "recovery_events_in_session_snapshot": recoveries,
        "runtime_source_hashes_from_log": runtime_hashes,
        "runtime_manifest": {"path": str(manifest_path), "sha256": hashlib.sha256(manifest_bytes).hexdigest() if manifest_bytes else None, "contents": manifest},
        "manifest_source_matches_startup_log": bool(manifest and manifest["source_sha256"] == runtime_hashes),
        "frozen_runtime_vs_current_disk": compare_frozen_files(manifest),
        "current_bot_state": read_bot_state(),
        "monitor_report": {"path": str(monitor_path), "sha256": hashlib.sha256(monitor_bytes).hexdigest() if monitor_bytes else None,
                           "contents": monitor},
        "completion_log_records": {str(battle): end_records.get(battle) for battle in sorted(complete)},
        "post_start_source_change_note": (
            "An equivalent vision performance patch was saved after this session startup. The running process does not hot-reload it. Runtime hashes retain cn_battle_cues.py=3d3d803462d2a881b58fb78dbb73984322fc221ddaba25b486d51b93676dce5f."
            if args.session == "20260926-115400" else
            "This report preserves the startup manifest/log hashes and never substitutes current source hashes."),
        "result_evidence": result_evidence, "evidence_verification_counts": dict(evidence_counts),
        "separate_pilots": pilots,
        "post_battle_continuations": transitions,
        "independently_verified_win_then_next_battle": [
            {"battle": transition["battle"], "ended_at": transition["ended_at"],
             "next_battle_start": transition["next_battle_start"],
             "seconds_to_next_battle": transition["seconds_to_next_battle"],
             "reward_tap_events": len(transition["reward_events"]),
             "immediate_reward_sequence_observed": bool(transition["reward_events"]),
             "reward_return_lobby_logs": transition["reward_return_lobby_logs"],
             "no_logged_recovery": True,
             "manual_intervention_note": (
                 "Root agent explicitly reports no manual intervention during this win-to-next-battle interval."
                 if args.session == "20260926-130806" and transition["battle"] == 4 else
                 "This read-only report does not infer absence of manual input solely from bot logs.")}
            for transition in transitions if transition["independently_reviewed_result"] == "胜利"
            and transition["next_battle_started_without_logged_recovery"]
            and (not transition["reward_events"] or transition["reward_return_lobby_logs"])],
        "independent_screenshot_reviews": {"accepted": accepted, "rejected": rejected,
            "outside_requested_snapshot": outside_snapshot,
            "reviewed_outcomes": dict(Counter(review["result"] for review in accepted)),
            "not_yet_reviewed_battles": sorted(complete-reviewed_ids)},
        "input_snapshots": {"trace_sha256": hashlib.sha256(trace_bytes).hexdigest(), "log_sha256": hashlib.sha256(log_bytes).hexdigest(), "partial_trace_tail_ignored": partial_line_ignored},
        "definitions": {"battle_minutes": "Start to battle_end; exclude lobby/matchmaking and resumed/incomplete battles.",
                        "no_hog_interval": "Battle start to first confirmed Hog, consecutive confirmed Hog gaps, or last confirmed Hog to end.",
                        "nominal_spend": "Fixed costs of confirmed card plays; skills excluded to match baseline. Not exact measured elixir.",
                        "screenshots": "Hash mismatch means the rotating slot is unusable for that event. View only verified_copy or a freshly verified matching source."},
        "limitations": ["Automatic result labels and independent screenshot reviews remain separate.", "Small nonrandom before/after cohorts do not establish a win-rate improvement or causal effect.", "Skill confirmation records a button/spend observation, not validated combat effectiveness.", "Threat no-match means unknown type; it is not evidence of no enemies. Template correlation is not probability.", "A victory cannot be attributed to typed threat rules when their logged trigger count is zero."]}
    if args.session in ("20260926-125136", "20260926-130806"):
        final_reward_patch = args.session == "20260926-130806"
        report["pre_session_validation_context"] = {
            "root_reported_tests_passed": 123 if final_reward_patch else 122,
            "root_reported_non_reward_frames_with_zero_new_reward_matches": 922 if final_reward_patch else 880,
            "actual_paused_reward_return_report": str(ROOT / "outputs/hog-v3-reward-return.json"),
            "limitation": "The pre-session paused reward return involved restarting the validator. It is not an uninterrupted new win-to-next-battle acceptance. Final-session continuation evidence above is counted separately."}
        if final_reward_patch:
            report["policy_lineage"] = {
                "previous_gameplay_session": "20260926-125136",
                "gameplay_strategy_sha256_unchanged": "39504a37fda16cbce13a1f0f3e7dd1fc6a8e84446e158f951280f5de7102133a",
                "new_loop_sha256": "e5bc743dac033548435f83ef36b0d80bd2fc8d1c1b33ab7c9139a953f91d3321",
                "scope": "New session validates the reward-navigation patch; earlier 3.2 victory and failed continuation remain a separate pilot."}
    target = 10
    prior_transitions = [transition for transition in transitions if transition["battle"] in range(1, target)]
    report["acceptance"] = {
        "ten_complete_battles": all(battle in complete for battle in range(1, target+1)),
        "consecutive_completed_at_tenth": end_records.get(target, {}).get("consecutive_completed"),
        "first_nine_automatically_continued_without_logged_recovery": len(prior_transitions) == 9 and all(
            transition["next_battle_started_without_logged_recovery"] for transition in prior_transitions),
        "all_main_results_independently_reviewed": complete == reviewed_ids,
        "verified_win_reward_to_next_battle_passed": any(
            transition["reward_tap_events"] and transition["reward_return_lobby_logs"]
            for transition in report["independently_verified_win_then_next_battle"]),
        "recovery_events_count": len(recoveries),
        "monitor_target_reached": monitor.get("target_reached") if monitor else None,
        "monitor_stop_exit_code": monitor.get("stop_exit_code") if monitor else None,
        "bot_stopped_now": report["current_bot_state"]["state"] == "stopped",
        "eleventh_battle_started": 11 in starts,
        "intentional_stop_note": (
            "Monitor reached ten complete battles and stopped the bot. No eleventh battle start is claimed."
            if monitor and monitor.get("target_reached") and 11 not in starts else None),
        "long_term_win_rate_improvement_proven": False,
        "statistical_note": "Ten battles with two wins and eight losses are a small descriptive sample, not statistical evidence of a lasting win-rate increase." if metrics["completed"] == 10 and metrics["automatic_outcomes"] == {"失败": 8, "胜利": 2} else
                            "This nonrandom small cohort does not establish a long-term win-rate improvement."}
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(destination), "cutoff": cutoff, "metrics": metrics,
                      "result_evidence": result_evidence, "screenshot_review": report["independent_screenshot_reviews"],
                      "manifest_source_matches_startup_log": report["manifest_source_matches_startup_log"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
