"""Read frozen batch evidence and write a flow report; never control processes."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from summarize_hog_v3 import analyze, compare_frozen_files, read_bot_state, timestamp

ROOT = Path(__file__).resolve().parent.parent


def json_lines(path):
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    result = []
    for index, line in enumerate(lines):
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            if index != len(lines)-1:
                raise
    return result


def merge_blocking_findings(policy_findings, vision_findings):
    """Count shared reviewer findings once, retaining both reports and aliases."""
    merged = []
    for reviewer, findings in (("policy", policy_findings), ("vision", vision_findings)):
        for index, finding in enumerate(findings):
            finding_id = finding.get("id", f"{reviewer}-finding-{index}")
            aliases = {finding_id, *finding.get("aliases", [])}
            hashes = finding.get("evidence_sha256", [])
            if not hashes and finding.get("sha256"):
                hashes = [finding["sha256"]]
            existing = next((item for item in merged if aliases.intersection(item["source_ids"])
                or (hashes and item["battle"] == finding.get("battle")
                    and set(item["evidence_sha256"]) == set(hashes))), None)
            if existing is None:
                existing = {"id": finding_id, "battle": finding.get("battle"), "source_ids": [],
                            "evidence_sha256": sorted(hashes), "reviewers": [], "reviewer_findings": []}
                merged.append(existing)
            existing["source_ids"] = sorted(set(existing["source_ids"]) | aliases)
            existing["reviewers"] = sorted(set(existing["reviewers"]) | {reviewer})
            existing["reviewer_findings"].append({"reviewer": reviewer, "finding": finding})
    return merged


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-dir", required=True, type=Path)
    args = parser.parse_args()
    folder = args.batch_dir.resolve()
    folder.relative_to((ROOT / "work/batch5").resolve())
    existing_path = folder / "batch-summary.json"
    previous_summary = json.loads(existing_path.read_text(encoding="utf-8")) if existing_path.is_file() else {}
    status = json.loads((folder / "capture-status.json").read_text(encoding="utf-8"))
    session, first, last = status["session"], status["first_battle"], status["last_battle"]
    events = json_lines(folder / "events.jsonl")
    manifest = json.loads((folder / "policy-manifest.json").read_text(encoding="utf-8"))
    session_logs, active, startup_hashes = [], False, None
    for number, line in enumerate((ROOT / "outputs/cn-battles-live.log").read_text(encoding="utf-8").splitlines(), 1):
        if "连续对战已启动" in line:
            active = datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S").strftime("%Y%m%d-%H%M%S") == session
        if active:
            session_logs.append({"line": number, "time": line[:19], "text": line})
            if "策略源码校验: " in line:
                startup_hashes = ast.literal_eval(line.split("策略源码校验: ", 1)[1])
    starts, start_evidence = {}, {}
    for log in session_logs:
        match = re.search(r"对战开始 场次=(\d+)", log["text"])
        if match:
            starts[int(match[1])] = timestamp(log["time"])
            start_evidence[int(match[1])] = log
    ends = [row for row in events if row["event"] == "battle_end"]
    complete = {row["battle"] for row in ends}
    selected = [row for row in events if row["battle"] in complete]
    metrics = analyze(selected, starts)
    plays = [row for row in selected if row["event"] == "play"]
    persistent = [row for row in plays if row["decision"].get("persistent_bridge")]
    metrics["persistent_bridge"] = {"attempts": len(persistent), "confirmed": sum(row["confirmed"] for row in persistent),
        "confirmed_cards": dict(Counter(row["decision"]["card"] for row in persistent if row["confirmed"])),
        "events": [{"battle": row["battle"], "time": row["time"], "decision": row["decision"],
                    "confirmed": row["confirmed"], "evidence": row.get("captured_evidence")} for row in persistent]}
    missing = json.loads((folder / "missing-evidence.json").read_text(encoding="utf-8"))
    image_paths, references = {}, 0
    for row in events:
        for evidence in row.get("captured_evidence", {}).values():
            references += 1
            if evidence.get("status", "").startswith("verified"):
                image_paths[evidence["expected_sha256"]] = Path(evidence["frozen_path"])
    image_checks = {sha: path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == sha
                    for sha, path in image_paths.items()}
    terminal = next((row for row in reversed(events) if row["event"] == "batch_complete" and row["battle"] == last), None)
    terminal_sha = terminal.get("captured_evidence", {}).get("evidence", {}).get("expected_sha256") if terminal else None
    terminal_valid = bool(terminal and terminal.get("state") == "lobby" and terminal.get("target_battles") == last
                          and image_checks.get(terminal_sha))
    lobby_review_path = folder / "lobby-review.json"
    lobby_review = json.loads(lobby_review_path.read_text(encoding="utf-8")) if lobby_review_path.is_file() else None
    if lobby_review and (lobby_review.get("sha256") != terminal_sha or not image_checks.get(terminal_sha)):
        lobby_review = None
    terminal_record_path = ROOT / "work/hog-validation" / session / "batch-complete.json"
    terminal_record = json.loads(terminal_record_path.read_text(encoding="utf-8")) if terminal_record_path.is_file() else None
    terminal_record_matches = bool(terminal and terminal_record and all(
        terminal.get(key) == value for key, value in terminal_record.items()))
    transitions = []
    for end in ends:
        battle = end["battle"]
        lobby_boundary = battle == last and status.get("completion_mode") == "lobby"
        boundary_time = terminal.get("time") if lobby_boundary and terminal else (
            start_evidence[battle+1]["time"] if battle+1 in start_evidence else None)
        recoveries = [log for log in session_logs if "恢复/重启" in log["text"]
                      and boundary_time and end["time"] <= log["time"] <= boundary_time]
        transitions.append({"battle": battle, "ended_at": end["time"],
            "boundary_type": "batch_complete_lobby" if lobby_boundary else "next_battle_start",
            "boundary_time": boundary_time, "seconds_to_boundary": timestamp(boundary_time)-timestamp(end["time"]) if boundary_time else None,
            "boundary_evidence": terminal if lobby_boundary else start_evidence.get(battle+1),
            "recoveries": recoveries, "flow_pass": bool(boundary_time and not recoveries and (not lobby_boundary or terminal_valid))})
    review_path = folder / "result-reviews.json"
    reviews = json.loads(review_path.read_text(encoding="utf-8")) if review_path.is_file() else []
    accepted_reviews = [review for review in reviews if image_checks.get(review["sha256"]) and any(
        end["battle"] == review["battle"] and end.get("captured_evidence", {}).get("evidence", {}).get("expected_sha256") == review["sha256"] for end in ends)]
    strategy_path = folder / "strategy-review-findings.json"
    strategy = json.loads(strategy_path.read_text(encoding="utf-8")) if strategy_path.is_file() else None
    policy_path = folder / "policy_audit/AUDIT.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8")) if policy_path.is_file() else strategy
    vision_path = folder / "vision_audit/AUDIT.json"
    vision = json.loads(vision_path.read_text(encoding="utf-8")) if vision_path.is_file() else None
    policy_completed = bool(policy and policy.get("review_completed") and policy.get("session", session) == session)
    vision_completed = bool(vision and vision.get("review_completed") and vision.get("session") == session)
    policy_status = str(policy.get("status", policy.get("strategy_gate", "PENDING"))).upper() if policy else "PENDING"
    vision_status = str(vision.get("status", "PENDING")).upper() if vision else "PENDING"
    policy_blockers = (policy.get("blocking_findings", [finding for finding in policy.get("findings", [])
                              if "blocking" in finding.get("severity", "")]) + policy.get("additional_blocking_findings", [])) if policy else []
    vision_blockers = (vision.get("blocking_findings", []) + vision.get("additional_blocking_visual_findings", [])
                       + vision.get("other_visual_blocking_findings", [])) if vision else []
    joint_findings = merge_blocking_findings(policy_blockers, vision_blockers)
    pid_manifest = json.loads((ROOT / "work/bot-processes.json").read_text(encoding="utf-8"))
    bot_state = read_bot_state()
    no_extra_start = last+1 not in starts
    # The global PID file may already describe a later candidate. Preserve this
    # session's normal-exit evidence rather than downgrading an older closed run.
    watchdog_exits = []
    if terminal:
        terminal_time = timestamp(terminal["time"])
        for number, line in enumerate((ROOT / "outputs/cn-watchdog.log").read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if "限量运行器正常结束，不再自动重启" in line:
                when = timestamp(line[:19])
                if terminal_time <= when <= terminal_time+60:
                    watchdog_exits.append({"source_line":number,"time":line[:19],"text":line})
    scoped_pid_exit = bool(terminal and pid_manifest.get("exit_reason") == "finite_run_ended"
        and pid_manifest.get("max_battles") == last and bot_state["state"] == "stopped"
        and pid_manifest.get("ended_at") and 0 <= timestamp(pid_manifest["ended_at"])-timestamp(terminal["time"]) <= 60)
    exit_path = folder / "process-exit-evidence.json"
    exit_record = json.loads(exit_path.read_text(encoding="utf-8")) if exit_path.is_file() else None
    if not exit_record and (scoped_pid_exit or watchdog_exits):
        exit_record = {"session":session,"recorded_at":datetime.now().isoformat(timespec="seconds"),
                       "normal_exit_confirmed":True,"watchdog_normal_exit_logs":watchdog_exits,
                       "pid_manifest_snapshot":pid_manifest if scoped_pid_exit else None,
                       "process_state_snapshot":bot_state if scoped_pid_exit else None,
                       "note":"Session-bound evidence remains valid after the global PID file changes for a later run."}
        exit_path.write_text(json.dumps(exit_record,ensure_ascii=False,indent=2),encoding="utf-8")
    finite_exit = bool(exit_record and exit_record.get("session") == session and exit_record.get("normal_exit_confirmed"))
    five_complete = set(range(first,last+1)) <= complete
    flow_pass = five_complete and all(row["confirmed"] > 0 for row in ends) and all(row["flow_pass"] for row in transitions)
    if status.get("completion_mode") == "lobby":
        flow_pass = (flow_pass and terminal_valid and no_extra_start and finite_exit
                     and terminal.get("consecutive", 0) >= last-first+1)
    evidence_pass = status.get("status") == "complete" and not missing and all(image_checks.values())
    reviews_complete = complete == {row["battle"] for row in accepted_reviews}
    review_failed = bool(policy_blockers or vision_blockers or "FAIL" in policy_status or "NOT_PASSED" in policy_status or "FAIL" in vision_status)
    joint_completed = policy_completed and vision_completed
    if review_failed:
        gate = "FAIL"
    elif (flow_pass and evidence_pass and reviews_complete and lobby_review and joint_completed
          and policy_status == "PASS" and vision_status == "PASS"):
        gate = "PASS"
    else:
        gate = "PENDING_JOINT_STRATEGY_AND_VISION_REVIEW"
    current_disk = compare_frozen_files(manifest)
    manifest_sha = hashlib.sha256((folder / "policy-manifest.json").read_bytes()).hexdigest()
    manifest_integrity = manifest_sha == status.get("manifest_sha256")
    version_pass = (manifest_integrity and manifest["source_sha256"] == startup_hashes
                    and current_disk["all_sources_match"] and current_disk["all_assets_match"])
    if gate == "PASS" and not version_pass:
        gate = "PENDING_VERSION_RECONCILIATION"
    prior_disk = previous_summary.get("current_disk_comparison", {})
    if prior_disk.get("status") == "EXPECTED_CHANGED_FOR_NEXT_CANDIDATE":
        current_disk.update({key: prior_disk[key] for key in ("status", "change_context", "reviewed_runtime_manifest_unchanged") if key in prior_disk})
    report = {"created_at": datetime.now().isoformat(timespec="seconds"), "session": session,
        "included_battles": list(range(first,last+1)), "acceptance_definition": "Five completed flows and no explicit strategy errors; five wins are not required.",
        "capture": status, "runtime_manifest": manifest, "manifest_matches_startup_log": manifest["source_sha256"] == startup_hashes,
        "frozen_manifest_matches_capture_hash":manifest_integrity,
        "version_gate":"PASS" if version_pass else "REVIEW_REQUIRED",
        "current_disk_comparison": current_disk, "metrics": metrics,
        "evidence_integrity": {"events":len(events), "references":references, "unique_pngs":len(image_paths),
                               "all_frozen_hashes_verified": all(image_checks.values()), "failed_hashes":[sha for sha,ok in image_checks.items() if not ok], "missing_count":len(missing)},
        "evidence_gate": "PASS" if evidence_pass else "PENDING_OR_NOT_PASSED",
        "independent_result_reviews": accepted_reviews, "reviewed_outcomes":dict(Counter(row["reviewed_result"] for row in accepted_reviews)),
        "not_yet_independently_reviewed": sorted(complete-{row["battle"] for row in accepted_reviews}),
        "transitions": transitions, "final_lobby_batch_complete_verified":terminal_valid,
        "independent_final_lobby_review":lobby_review,
        "runner_batch_complete_record":terminal_record, "runner_record_matches_trace":terminal_record_matches,
        "final_consecutive":terminal.get("consecutive") if terminal else None,
        "sixth_or_next_battle_started":not no_extra_start,
        "pid_manifest":exit_record.get("pid_manifest_snapshot") if exit_record else pid_manifest,
        "current_bot_state":exit_record.get("process_state_snapshot") if exit_record and exit_record.get("process_state_snapshot") else bot_state,
        "current_global_pid_manifest":pid_manifest,"current_global_bot_state":bot_state,
        "batch_process_exit_evidence":exit_record,
        "finite_runner_watchdog_normal_exit":finite_exit, "flow_gate":"PASS" if flow_pass else "PENDING_OR_NOT_PASSED",
        "strategy_review":strategy, "policy_review":policy, "vision_review":vision,
        "joint_blocking_findings":joint_findings, "joint_blocking_findings_count":len(joint_findings),
        "review_completion":{"policy":{"completed":policy_completed,"status":policy_status,"source":str(policy_path if policy_path.is_file() else strategy_path)},
                             "vision":{"completed":vision_completed,"status":vision_status,"source":str(vision_path)}},
        "overall_batch_gate":gate, "review_completed":joint_completed,
        "joint_strategy_and_vision_review_complete":joint_completed,
        "limitations":["Flow passing never automatically passes the strategy/vision gates.", "Pending reviews are not interpreted as no errors.", "Type no-match remains unknown; matcher scores are not probabilities."]}
    for key in ("post_run_initial_disk_comparison", "reviewed_runtime_manifest_sha256"):
        if key in previous_summary:
            report[key] = previous_summary[key]
    (folder / "batch-summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report":str(folder/"batch-summary.json"), "completed":metrics["completed"],
                      "automatic_results":metrics["automatic_outcomes"], "flow_gate":report["flow_gate"],
                      "overall_batch_gate":gate, "evidence_integrity":report["evidence_integrity"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
