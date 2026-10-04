"""Read-only fixed-window ledger for an explicitly selected bot run.

Only this tool's trial directory is written. It never launches, stops, clicks or
reconfigures the bot. ReplayEngine is pure and tested independently of live I/O.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = {"胜利", "失败", "未知"}
FREEZE_EVENTS = {"battle_start", "battle_end", "battle_abandoned", "recovery", "screen_unknown", "batch_complete"}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class ReplayEngine:
    def __init__(self, config):
        self.config = config
        self.slots = []
        self.active = None
        self.current_session = None
        self.runs = []
        self.holds = []
        self.seen = set()
        self.event_count = 0
        self.duplicate_events = 0
        self.outside_window = 0
        self.anchor_seen = False
        self.review_issues = []

    def hold(self, code, transaction, detail=None):
        item = {"code": code, "event_id": transaction.get("event_id"), "detail": detail}
        if item not in self.holds:
            self.holds.append(item)

    def close_unknown(self, slot, event, reason):
        slot.update(status="CLOSED", raw_result="未知", close_reason=reason, closed_at=event.get("time"))
        if self.active == slot["index"]:
            self.active = None

    def apply(self, transaction):
        identifier = transaction["event_id"]
        if identifier in self.seen:
            self.duplicate_events += 1
            return
        self.seen.add(identifier)
        event = transaction["event"]
        session = event.get("session")
        if not self.anchor_seen:
            if session != self.config["first_session"]:
                return
            self.anchor_seen = True
        self.event_count += 1
        if len(self.slots) == self.config["target_count"] and all(slot["status"] == "CLOSED" for slot in self.slots):
            self.outside_window += 1
            return
        if transaction.get("manifest_fingerprint") != self.config["manifest_fingerprint"]:
            self.hold("VERSION_MISMATCH", transaction, session)
            return
        if session != self.current_session:
            if session in self.runs:
                self.hold("INTERLEAVED_RUN_SESSIONS", transaction, session)
                return
            self.runs.append(session)
            self.current_session = session
        if self.holds:
            return
        kind = event.get("event")
        local_key = [session, event.get("battle")]
        slot = self.slots[self.active-1] if self.active else None
        if kind == "battle_start":
            if event.get("resumed"):
                if slot is None:
                    self.hold("ORPHAN_RESUMED_BATTLE", transaction, local_key)
                    return
                if local_key not in slot["aliases"]:
                    slot["aliases"].append(local_key)
                slot["resume_events"].append(identifier)
                slot["event_ids"].append(identifier)
                return
            # A fresh start is positive evidence that an older open encounter
            # no longer continues. Keep that older slot as a closed non-win.
            if slot is not None:
                self.close_unknown(slot, event, "new_fresh_start_before_result")
            if len(self.slots) >= self.config["target_count"]:
                self.outside_window += 1
                return
            if not self.slots and self.config.get("created_at") and event.get("time"):
                if datetime.fromisoformat(event["time"]) < datetime.fromisoformat(self.config["created_at"]):
                    self.hold("FIRST_BATTLE_PREDATES_COMMITTED_PLAN", transaction, event["time"])
                    return
            slot = {"index": len(self.slots)+1, "status": "OPEN", "raw_result": None,
                    "started_at": event.get("time"), "start_event_id": identifier,
                    "aliases": [local_key], "event_ids": [identifier], "resume_events": [],
                    "recovery_events": [], "result_evidence": [], "diagnostic_evidence": [],
                    "missing_result_evidence": False, "review": None}
            self.slots.append(slot)
            self.active = slot["index"]
            return
        if kind == "recovery":
            if slot:
                slot["recovery_events"].append({"event_id": identifier, "event": event})
                slot["event_ids"].append(identifier)
                slot["diagnostic_evidence"].extend(transaction.get("frozen_evidence", []))
            return
        if kind in ("battle_end", "battle_abandoned"):
            if slot is None or local_key not in slot["aliases"]:
                # An exact repeat can have a new source line but the same raw
                # event; event digest de-duplication above handles that case.
                if len(self.slots) >= self.config["target_count"] and slot is None:
                    self.outside_window += 1
                else:
                    self.hold("ORPHAN_OR_MISMATCHED_TERMINAL_EVENT", transaction, local_key)
                return
            slot["event_ids"].append(identifier)
            if kind == "battle_abandoned":
                slot["diagnostic_evidence"].extend(transaction.get("frozen_evidence", []))
                self.close_unknown(slot, event, event.get("reason", "battle_abandoned"))
                return
            result = event.get("result")
            if result not in RESULTS:
                result = "未知"
            evidence = transaction.get("frozen_evidence", [])
            slot["result_evidence"].extend(evidence)
            slot["missing_result_evidence"] = not any(item.get("verified") for item in evidence)
            slot.update(status="CLOSED", raw_result=result, close_reason="battle_end", closed_at=event.get("time"),
                        end_event_id=identifier, end_event=event)
            self.active = None
            return
        if slot:
            slot["event_ids"].append(identifier)
            if kind == "screen_unknown":
                slot["diagnostic_evidence"].extend(transaction.get("frozen_evidence", []))

    def apply_reviews(self, reviews):
        self.review_issues = []
        for slot in self.slots:
            slot["review"] = None
        for review in reviews:
            number = review.get("slot")
            if (review.get("trial_id") != self.config["trial_id"] or not isinstance(number, int)
                    or not 1 <= number <= len(self.slots) or review.get("result") not in RESULTS or not review.get("reviewer")):
                self.review_issues.append({"code": "INVALID_REVIEW", "review": review})
                continue
            slot = self.slots[number-1]
            good_hashes = {item.get("sha256") for item in slot["result_evidence"] if item.get("verified")}
            valid_image = review.get("sha256") in good_hashes
            # A genuinely interrupted encounter may have no result image.
            # Explicit unresolved review can close its audit as a non-win only.
            unresolved = (review["result"] == "未知" and slot["raw_result"] == "未知"
                          and not slot["result_evidence"] and review.get("basis") == "no_result_available"
                          and bool(review.get("reason")))
            if slot["status"] != "CLOSED" or not (valid_image or unresolved):
                self.review_issues.append({"code": "REVIEW_EVIDENCE_MISMATCH", "review": review})
                continue
            earlier = slot["review"]
            review_id = digest(review)
            if earlier and earlier["result"] != review["result"] and review.get("supersedes") != earlier["review_id"]:
                self.review_issues.append({"code": "CONFLICTING_REVIEW", "slot": number})
                continue
            slot["review"] = {**review, "review_id": review_id}

    def report(self):
        closed = [slot for slot in self.slots if slot["status"] == "CLOSED"]
        raw_counts = {result: sum(slot["raw_result"] == result for slot in closed) for result in RESULTS}
        wins = sum(slot.get("review", {}).get("result") == "胜利" for slot in closed if slot.get("review"))
        pending_unknown = [slot["index"] for slot in closed if slot["raw_result"] == "未知" and not slot["review"]]
        missing = [slot["index"] for slot in closed if slot["missing_result_evidence"]]
        all_closed = len(self.slots) == self.config["target_count"] and len(closed) == self.config["target_count"]
        if self.holds:
            status = "HOLD"
        elif all_closed and wins >= self.config["min_confirmed_wins"] and not pending_unknown and not missing and not self.review_issues:
            status = "PASS"
        elif all_closed:
            status = "WINDOW_CLOSED_NOT_YET_QUALIFIED"
        else:
            status = "COLLECTING"
        return {"schema_version": 1, "config": self.config, "status": status, "anchor_seen": self.anchor_seen,
                "accepted_sessions": self.runs, "slots_admitted": len(self.slots), "slots_closed": len(closed),
                "active_slot": self.active, "raw_result_counts": raw_counts, "confirmed_win": wins,
                "target_denominator": self.config["target_count"], "all_target_slots_closed": all_closed,
                "unknown_review_pending_slots": pending_unknown, "missing_result_evidence_slots": missing,
                "holds": self.holds, "review_issues": self.review_issues, "event_count": self.event_count,
                "duplicate_events": self.duplicate_events, "outside_window_events": self.outside_window,
                "slots": self.slots,
                "rules": ["Only independently reviewed, hash-linked wins count toward the required number.",
                          "Unknown/abandoned encounters retain their slots and are non-wins; never remove them from the denominator.",
                          "Silence, power loss or a process disappearing does not manufacture a result or a victory.",
                          "Version/identity ambiguity latches HOLD; the helper never creates a replacement sample automatically."]}


def read_manifest(session):
    path = ROOT / "work/hog-validation" / session / "policy-manifest.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    return value, digest(value)


def freeze_event_evidence(event, trial_dir):
    result = []
    if event.get("event") not in FREEZE_EVENTS:
        return result
    for field in ("evidence", "evidence_before", "evidence_after"):
        item = event.get(field)
        if not isinstance(item, dict):
            continue
        sha = item.get("sha256")
        record = {"field": field, "source": item.get("path"), "sha256": sha, "verified": False}
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
            result.append({**record, "error": "invalid_expected_hash"})
            continue
        target = trial_dir / "evidence" / f"{sha}.png"
        try:
            if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == sha:
                record.update(verified=True, frozen_path=str(target))
            else:
                source = Path(item["path"])
                source.resolve().relative_to(ROOT.resolve())
                data = source.read_bytes()
                actual = hashlib.sha256(data).hexdigest()
                if actual != sha:
                    record.update(error="overwritten_or_mismatched", actual_sha256=actual)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temp = target.with_suffix(".png.tmp")
                    with temp.open("wb") as stream:
                        stream.write(data)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temp, target)
                    record.update(verified=True, frozen_path=str(target))
        except (OSError, ValueError, KeyError) as error:
            record.update(error=type(error).__name__)
        result.append(record)
    return result


def disk_version_issues(manifest):
    package = ROOT / "py-clash-bot/pyclashbot"
    sources = {"cn_1v1_loop.py": "bot", "hog_cycle_strategy.py": "bot", "coords.py": "bot",
               "elite_ice_golem_ability.py": "bot", "card_detection.py": "bot",
               "adb_base.py": "emulators", "base.py": "emulators",
               "cn_battle_cues.py": "detection", "cn_threats.py": "detection"}
    issues = []
    for name, expected in manifest.get("source_sha256", {}).items():
        paths = [package / sources[name] / name] if name in sources else list(package.rglob(name))
        actual = hashlib.sha256(paths[0].read_bytes()).hexdigest() if len(paths) == 1 and paths[0].is_file() else None
        if actual != expected:
            issues.append({"source": name, "expected": expected, "actual": actual})
    image_root = package / "detection/reference_images"
    for name, expected in manifest.get("asset_sha256", {}).items():
        path = (image_root / name).resolve()
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_relative_to(image_root.resolve()) and path.is_file() else None
        if actual != expected:
            issues.append({"asset": name, "expected": expected, "actual": actual})
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first-session", required=True)
    parser.add_argument("--trial-dir", required=True, type=Path)
    parser.add_argument("--target-count", type=int, default=100)
    parser.add_argument("--min-confirmed-wins", type=int, default=33)
    parser.add_argument("--poll-seconds", type=float, default=2)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"\d{8}-\d{6}", args.first_session):
        parser.error("Use the exact trace session directory ID, not the later log startup timestamp")
    if not 1 <= args.min_confirmed_wins <= args.target_count or args.poll_seconds < .5:
        parser.error("Invalid target, win requirement, or poll interval")
    trial_dir = args.trial_dir.resolve()
    trial_dir.relative_to((ROOT / "work/winrate33").resolve())
    trial_dir.mkdir(parents=True, exist_ok=True)
    transactions_dir = trial_dir / "transactions"
    transactions_dir.mkdir(exist_ok=True)
    manifest, fingerprint = read_manifest(args.first_session)
    config_path = trial_dir / "trial.json"
    required = {"trial_id": trial_dir.name, "first_session": args.first_session,
                "target_count": args.target_count, "min_confirmed_wins": args.min_confirmed_wins,
                "manifest_fingerprint": fingerprint}
    if config_path.is_file():
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if any(config.get(key) != value for key, value in required.items()):
            parser.error("Existing trial configuration differs; never reset or replace its window")
    else:
        config = {**required, "created_at": datetime.now().isoformat(timespec="seconds")}
        atomic_json(config_path, config)
        atomic_json(trial_dir / "frozen-manifest.json", manifest)
    engine = ReplayEngine(config)
    journal = []
    for path in sorted(transactions_dir.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        journal.append(record)
        engine.apply(record)
    holds_path = trial_dir / "control-holds.json"
    if holds_path.is_file():
        for hold in json.loads(holds_path.read_text(encoding="utf-8")):
            if hold not in engine.holds:
                engine.holds.append(hold)
    cursor_path = trial_dir / "cursor.json"
    cursor = json.loads(cursor_path.read_text(encoding="utf-8")) if cursor_path.is_file() else {"offset": 0, "line": 0}
    if journal:
        # Durable transactions precede cursor commits; the transaction tail is
        # authoritative after any interrupted checkpoint write.
        cursor = {"offset": journal[-1]["source_end_offset"], "line": journal[-1]["source_line"]}
    source_path = ROOT / "outputs/cn-hog-strategy.jsonl"
    seen_anchor = engine.anchor_seen
    manifest_cache = {args.first_session: (manifest, fingerprint)}
    last_printed = None
    while True:
        window_closed = engine.report()["all_target_slots_closed"]
        if not window_closed:
            issues = disk_version_issues(manifest)
            if issues:
                engine.hold("DISK_VERSION_CHANGED", {}, issues)
        if journal and cursor["offset"]:
            tail = journal[-1]
            with source_path.open("rb") as source_guard:
                source_guard.seek(tail["source_begin_offset"])
                previous_raw = source_guard.read(tail["source_end_offset"]-tail["source_begin_offset"])
            if hashlib.sha256(previous_raw).hexdigest() != tail["source_raw_sha256"]:
                engine.hold("SOURCE_PREFIX_CHANGED", {}, tail["source_line"])
        if source_path.stat().st_size < cursor["offset"]:
            engine.hold("SOURCE_TRUNCATED", {}, dict(cursor))
        elif not window_closed:
            with source_path.open("rb") as source:
                source.seek(cursor["offset"])
                while True:
                    beginning = source.tell()
                    raw = source.readline()
                    if not raw or not raw.endswith(b"\n"):
                        break
                    line_number = cursor["line"] + 1
                    try:
                        event = json.loads(raw)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        engine.hold("MALFORMED_SOURCE_LINE", {}, {"line": line_number})
                        break
                    session = event.get("session")
                    if not seen_anchor and session != args.first_session:
                        cursor = {"offset": source.tell(), "line": line_number}
                        continue
                    seen_anchor = True
                    try:
                        if session not in manifest_cache:
                            manifest_cache[session] = read_manifest(session)
                        run_manifest, run_fingerprint = manifest_cache[session]
                        atomic_json(trial_dir / "run-manifests" / f"{session}.json", run_manifest)
                    except (OSError, ValueError, TypeError):
                        run_fingerprint = None
                    identifier = digest(event)
                    record = {"event_id": identifier, "event": event,
                              "manifest_fingerprint": run_fingerprint,
                              "source_line": line_number, "source_begin_offset": beginning,
                              "source_end_offset": source.tell(), "source_raw_sha256": hashlib.sha256(raw).hexdigest(),
                              "frozen_evidence": freeze_event_evidence(event, trial_dir)}
                    path = transactions_dir / f"{line_number:09d}-{identifier[:16]}.json"
                    if path.is_file():
                        record = json.loads(path.read_text(encoding="utf-8"))
                    else:
                        atomic_json(path, record)
                    engine.apply(record)
                    journal.append(record)
                    cursor = {"offset": source.tell(), "line": line_number}
                    atomic_json(cursor_path, cursor)
                    if engine.report()["all_target_slots_closed"]:
                        break
        atomic_json(cursor_path, cursor)
        atomic_json(holds_path, engine.holds)
        reviews_path = trial_dir / "reviews.json"
        reviews = json.loads(reviews_path.read_text(encoding="utf-8")) if reviews_path.is_file() else []
        engine.apply_reviews(reviews)
        if reviews:
            atomic_json(trial_dir / "review-snapshots" / f"{digest(reviews)}.json", reviews)
        report = engine.report()
        report["updated_at"] = datetime.now().isoformat(timespec="seconds")
        report["source_cursor"] = cursor
        atomic_json(trial_dir / "ledger.json", report)
        summary = {key: report[key] for key in ("status", "slots_admitted", "slots_closed", "confirmed_win", "raw_result_counts", "active_slot")}
        if summary != last_printed:
            print(json.dumps(summary, ensure_ascii=False), flush=True)
            last_printed = summary
        if args.once or report["status"] == "PASS":
            return
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
