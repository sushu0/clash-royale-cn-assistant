"""Freeze a battle cohort; accept its next start or an explicit final-lobby event.

This collector never controls the bot, emulator or ADB. In lobby completion mode,
the last result alone is insufficient: batch_complete must carry verified evidence.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def freeze(evidence, folder):
    expected = evidence.get("sha256")
    source = Path(evidence.get("path", ""))
    result = {"source": str(source), "expected_sha256": expected, "sequence": evidence.get("sequence")}
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        return {**result, "status": "invalid_hash"}
    target = folder / "evidence" / (expected + ".png")
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
        return {**result, "status": "verified_existing", "frozen_path": str(target)}
    try:
        source.resolve().relative_to(ROOT.resolve())
        data = source.read_bytes()
    except (OSError, ValueError) as error:
        return {**result, "status": "missing_or_outside_task", "error": type(error).__name__}
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        return {**result, "status": "overwritten_or_mismatched", "actual_sha256": actual}
    target.write_bytes(data)
    return {**result, "status": "verified_frozen", "frozen_path": str(target)}


def valid_lobby_completion(row, last):
    if not row:
        return False
    evidence = row.get("captured_evidence", {}).get("evidence", {})
    return (row.get("event") == "batch_complete" and row.get("battle") == last
            and row.get("state") == "lobby" and row.get("target_battles") == last
            and evidence.get("status", "").startswith("verified")
            and bool(evidence.get("frozen_path")))


def completion_boundary(completed, first, last, mode, continuation, lobby_completion):
    if not all(battle in completed for battle in range(first, last+1)):
        return None
    if mode in ("auto", "lobby") and valid_lobby_completion(lobby_completion, last):
        return "batch_complete_lobby"
    if mode in ("auto", "next-start") and continuation is not None:
        return "next_battle_start"
    return None


def log_start_candidate(line, trace_session):
    """Startup logging can follow creation of the trace directory by seconds."""
    try:
        logged_at = datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S")
        trace_at = datetime.strptime(trace_session, "%Y%m%d-%H%M%S")
    except ValueError:
        return None
    delta = abs((logged_at - trace_at).total_seconds())
    if delta > 3:
        return None
    return {"trace_session": trace_session, "log_start_time": line[:19],
            "start_time_difference_seconds": delta}


def verified_log_binding(candidate, line, expected_hashes):
    """A nearby timestamp alone never grants ownership of subsequent log lines."""
    marker = "策略源码校验: "
    if not candidate or not expected_hashes or marker not in line:
        return None
    try:
        logged_hashes = ast.literal_eval(line.split(marker, 1)[1])
    except (ValueError, SyntaxError):
        return None
    if logged_hashes != expected_hashes:
        return None
    return {**candidate, "source_hashes_match": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--first", type=int, required=True)
    parser.add_argument("--last", type=int, required=True)
    parser.add_argument("--batch-dir", type=Path, required=True)
    parser.add_argument("--completion-mode", choices=("auto", "lobby", "next-start"), default="auto",
                        help="auto preserves next-start completion and also accepts a verified batch_complete lobby event")
    args = parser.parse_args()
    if args.first < 1 or args.last < args.first:
        parser.error("Expected 1 <= first <= last")
    folder = args.batch_dir.resolve()
    if not folder.is_relative_to((ROOT / "work").resolve()):
        parser.error("Batch directory must stay under the task work directory")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "evidence").mkdir(exist_ok=True)
    manifest = ROOT / "work/hog-validation" / args.session / "policy-manifest.json"
    manifest_bytes = manifest.read_bytes()
    expected_source_hashes = json.loads(manifest_bytes).get("source_sha256", {})
    manifest_copy = folder / "policy-manifest.json"
    if manifest_copy.is_file() and manifest_copy.read_bytes() != manifest_bytes:
        parser.error("Existing batch manifest differs; use a new batch directory")
    manifest_copy.write_bytes(manifest_bytes)
    status_path = folder / "capture-status.json"
    event_path = folder / "events.jsonl"
    prior = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()] if event_path.is_file() else []
    seen = {row["capture_source_line"] for row in prior}
    completed = {row["battle"] for row in prior if row["event"] == "battle_end"}
    missing_path = folder / "missing-evidence.json"
    missing = json.loads(missing_path.read_text(encoding="utf-8")) if missing_path.is_file() else []
    event_count = len(prior)
    trace = (ROOT / "outputs/cn-hog-strategy.jsonl").open("rb")
    log = (ROOT / "outputs/cn-battles-live.log").open("rb")
    trace_buffer = log_buffer = b""
    trace_line = log_line = 0
    log_active = False
    log_candidate = None
    log_session_binding = None
    log_battle = None
    log_path = folder / "battle-log.jsonl"
    log_seen = {json.loads(line)["source_line"] for line in log_path.read_text(encoding="utf-8").splitlines()} if log_path.is_file() else set()
    continuation = None
    lobby_completion = next((row for row in reversed(prior) if row.get("event") == "batch_complete"
                             and row.get("battle") == args.last), None)
    started_at = datetime.now().isoformat(timespec="seconds")
    print(json.dumps({"collector_pid": os.getpid(), "batch_directory": str(folder), "session": args.session,
                      "battles": [args.first, args.last], "completion_mode": args.completion_mode}, ensure_ascii=False), flush=True)
    while True:
        trace_buffer += trace.read()
        pieces = trace_buffer.split(b"\n")
        trace_buffer = pieces.pop()
        for raw in pieces:
            trace_line += 1
            if trace_line in seen or not raw.strip():
                continue
            row = json.loads(raw)
            if row.get("session") != args.session or not args.first <= row.get("battle", -1) <= args.last:
                continue
            frozen = {}
            for field in ("evidence", "evidence_before", "evidence_after"):
                if isinstance(row.get(field), dict):
                    frozen[field] = freeze(row[field], folder)
                    if not frozen[field]["status"].startswith("verified"):
                        missing.append({"trace_line": trace_line, "event": row["event"], "battle": row["battle"],
                                        "time": row["time"], "field": field, **frozen[field]})
            row.update(capture_source_line=trace_line, capture_saved_at=datetime.now().isoformat(timespec="seconds"),
                       captured_evidence=frozen)
            with event_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False)+"\n")
            seen.add(trace_line)
            event_count += 1
            if row["event"] == "battle_end":
                completed.add(row["battle"])
                print(json.dumps({"completed_battle": row["battle"], "result": row["result"],
                                  "confirmed": row["confirmed"], "attempts": row["attempts"]}, ensure_ascii=False), flush=True)
            if row["event"] == "batch_complete" and row["battle"] == args.last:
                lobby_completion = row
                save_json(folder / "batch-complete-event.json", row)
        log_buffer += log.read()
        pieces = log_buffer.split(b"\n")
        log_buffer = pieces.pop()
        for raw in pieces:
            log_line += 1
            line = raw.decode("utf-8", errors="replace").rstrip("\r")
            if "连续对战已启动" in line:
                log_candidate = log_start_candidate(line, args.session)
                log_active = False
                log_battle = None
            if log_candidate is not None and "策略源码校验: " in line:
                binding = verified_log_binding(log_candidate, line, expected_source_hashes)
                log_active = binding is not None
                if binding is not None:
                    log_session_binding = {**binding, "source_hash_log_line": log_line}
            if not log_active:
                continue
            match = re.search(r"对战开始 场次=(\d+)", line)
            if match:
                log_battle = int(match[1])
                if log_battle == args.last+1:
                    continuation = {"log_line": log_line, "text": line, "battle": log_battle}
            selected = (log_battle is not None and args.first <= log_battle <= args.last) or (
                match and int(match[1]) == args.last+1)
            if selected and log_line not in log_seen:
                with (folder / "battle-log.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"source_line": log_line, "text": line}, ensure_ascii=False)+"\n")
                log_seen.add(log_line)
        boundary = completion_boundary(completed, args.first, args.last, args.completion_mode,
                                       continuation, lobby_completion)
        done = boundary is not None
        state = {"collector_pid": os.getpid(), "session": args.session, "first_battle": args.first,
                 "last_battle": args.last, "started_at": started_at, "updated_at": datetime.now().isoformat(timespec="seconds"),
                 "status": "complete" if done else "collecting", "completed_battles": sorted(completed),
                 "event_count": event_count, "missing_evidence_count": len(missing),
                 "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                 "verified_log_session_binding": log_session_binding,
                 "completion_mode": args.completion_mode, "completion_boundary": boundary,
                 "last_battle_continued_to_next": continuation,
                 "last_battle_returned_to_lobby": lobby_completion,
                 "verified_final_lobby": valid_lobby_completion(lobby_completion, args.last),
                 "unexpected_next_start_in_lobby_mode": args.completion_mode == "lobby" and continuation is not None,
                 "boundary_note": "A verified final-lobby batch_complete is a valid terminal boundary; no extra battle is required.",
                 "excluded_battle_after_batch": args.last+1, "trace_byte_offset": trace.tell(), "trace_line": trace_line}
        save_json(status_path, state)
        save_json(folder / "missing-evidence.json", missing)
        if done:
            runner_record = manifest.parent / "batch-complete.json"
            if boundary == "batch_complete_lobby" and runner_record.is_file():
                (folder / "runner-batch-complete.json").write_bytes(runner_record.read_bytes())
            print(json.dumps(state, ensure_ascii=False), flush=True)
            break
        time.sleep(0.7)


if __name__ == "__main__":
    main()
