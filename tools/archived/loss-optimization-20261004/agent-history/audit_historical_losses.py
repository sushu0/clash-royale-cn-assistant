"""Read-only audit of historical hog/567 losses and retained image evidence."""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(r"D:\codex\CodexWork\clash")
OUT = ROOT / "work/loss-optimization-20261004/agent-history"
LOSS = "失败"
TRACES = {
    "hog": ROOT / "outputs/cn-hog-strategy.jsonl",
    "567": ROOT / "outputs/cn-567-strategy.jsonl",
}
ARCHIVE_ROOTS = [
    "567", "567-audit", "567-evo", "567-evo-audit", "567-optimize",
    "567-v4-ui-20260929-004614", "567-validation", "hog-validation",
    "hog-v3-verified-evidence", "batch5", "winrate", "winrate33",
    "continuous-monitor", "random-result-evidence", "random-strategy",
    "v2-resultfix-audit", "v2-vision-audit", "v3-vision-audit", "v3-royal-giant", "v3-threats",
]
EXCLUDED = {"backup", "backups", "venv", ".venv", "lib", "site-packages"}


def read_jsonl(path):
    with path.open(encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                row = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if isinstance(row, dict) and isinstance(row.get("event"), str):
                yield line_number, row


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def event_id(row):
    clean = {k: v for k, v in row.items() if not k.startswith("capture")}
    return hashlib.sha256(json.dumps(clean, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect((ROOT / "outputs/cn-battle-history.sqlite3").as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db_rows = [dict(row) for row in db.execute("SELECT * FROM battles ORDER BY strategy,session,battle")]
    db.close()
    counts = defaultdict(Counter)
    for row in db_rows:
        counts[row["strategy"]]["未知" if row["conflict"] else row["result"]] += 1
    losses = {
        (r["strategy"], r["session"], r["battle"]): r
        for r in db_rows if r["strategy"] != "random" and r["result"] == LOSS and not r["conflict"]
    }
    events = defaultdict(dict)
    ends = {}
    source_counts = {}
    pending = defaultdict(list)
    for strategy, path in TRACES.items():
        counter = Counter()
        for line_number, row in read_jsonl(path):
            counter[row["event"]] += 1
            session = row.get("session")
            battle = row.get("battle")
            if not isinstance(battle, int):
                continue
            item = {"row": row, "source": str(path), "line": line_number, "alternates": []}
            if not session:
                if row["event"] == "battle_end":
                    key = (strategy, "legacy:" + row.get("time", ""), battle)
                    ends[key] = item
                    if key in losses:
                        for prior in pending.pop(battle, []):
                            events[key][event_id(prior["row"])] = prior
                        events[key][event_id(row)] = item
                    else:
                        pending.pop(battle, None)
                else:
                    pending[battle].append(item)
                continue
            key = (strategy, session, battle)
            if row["event"] == "battle_end":
                ends[key] = item
            if key in losses:
                events[key][event_id(row)] = item
        source_counts[str(path)] = dict(counter)

    archive_paths = []
    archive_json_paths = []
    frozen_hash_paths = defaultdict(list)
    for folder in ARCHIVE_ROOTS:
        for path in (ROOT / "work" / folder).rglob("*.jsonl"):
            if any(part in EXCLUDED or part.startswith("pytest") for part in path.relative_to(ROOT / "work").parts):
                continue
            if path.name == "events.jsonl" or path.name in {"trace.jsonl", "strategy.jsonl"}:
                archive_paths.append(path)
        for path in (ROOT / "work" / folder).rglob("*.json"):
            if any(part in EXCLUDED or part.startswith("pytest") for part in path.relative_to(ROOT / "work").parts):
                continue
            archive_json_paths.append(path)
        for path in (ROOT / "work" / folder).rglob("*.png"):
            if any(part in EXCLUDED or part.startswith("pytest") for part in path.relative_to(ROOT / "work").parts):
                continue
            if len(path.stem) == 64 and all(char in "0123456789abcdef" for char in path.stem):
                frozen_hash_paths[path.stem].append(path)
    archive_additions = 0
    archived_dupes = 0
    def add_archive(path, line_number, row):
        nonlocal archived_dupes, archive_additions
        session = row.get("session")
        battle = row.get("battle")
        if not session or not isinstance(battle, int):
            return
        strategy = "567" if "567" in str(row.get("policy_version", "")) else "hog"
        key = (strategy, session, battle)
        if key not in losses:
            return
        eid = event_id(row)
        item = {"row": row, "source": str(path), "line": line_number, "alternates": []}
        if eid in events[key]:
            events[key][eid]["alternates"].append(item)
            archived_dupes += 1
        else:
            events[key][eid] = item
            archive_additions += 1

    for path in sorted(archive_paths):
        for line_number, row in read_jsonl(path):
            add_archive(path, line_number, row)
    direct_archive_events = 0
    snapshot_manifest_entries = 0

    def add_snapshot_metadata(value):
        nonlocal snapshot_manifest_entries
        if isinstance(value, list):
            for child in value:
                add_snapshot_metadata(child)
        elif isinstance(value, dict):
            sha = value.get("sha256")
            snapshot = value.get("snapshot")
            if isinstance(sha, str) and len(sha) == 64 and isinstance(snapshot, str):
                path = Path(snapshot)
                if path.is_relative_to(ROOT) and path.suffix == ".png":
                    frozen_hash_paths[sha].append(path)
                    snapshot_manifest_entries += 1
            for child in value.values():
                if isinstance(child, (dict, list)):
                    add_snapshot_metadata(child)

    for path in sorted(archive_json_paths):
        try:
            row = json.loads(path.read_text(encoding="utf-8-sig"))
        except (ValueError, OSError):
            continue
        add_snapshot_metadata(row)
        if isinstance(row, dict) and isinstance(row.get("event"), str) and row.get("time"):
            add_archive(path, 1, row)
            direct_archive_events += 1

    hash_cache = {}
    hash_io_errors = []

    def verify(path_text, sha):
        if not isinstance(path_text, str) or not isinstance(sha, str) or len(sha) != 64:
            return "no_hash_contract", None
        path = Path(path_text)
        if not path.is_relative_to(ROOT):
            return "outside_current_root", None
        if path_text not in hash_cache:
            try:
                hash_cache[path_text] = digest(path) if path.is_file() else None
            except OSError as exc:
                hash_cache[path_text] = None
                hash_io_errors.append({"path": path_text, "error": str(exc)})
        actual = hash_cache[path_text]
        return ("verified" if actual == sha else "missing" if actual is None else "hash_mismatch"), actual

    def image_ref(item, field="evidence"):
        candidates = [item, *item["alternates"]]
        bad = []
        for candidate in candidates:
            row = candidate["row"]
            evidence = row.get(field)
            if isinstance(evidence, dict):
                path, sha = evidence.get("path"), evidence.get("sha256")
                status, actual = verify(path, sha)
                if status == "verified":
                    return {"path": path, "sha256": sha, "status": status, "actual_sha256": actual}
                bad.append({"path": path, "sha256": sha, "status": status, "actual_sha256": actual})
            captured = (row.get("captured_evidence") or {}).get(field)
            if isinstance(captured, dict):
                path, sha = captured.get("frozen_path"), captured.get("expected_sha256")
                status, actual = verify(path, sha)
                if status == "verified":
                    return {"path": path, "sha256": sha, "status": status, "actual_sha256": actual}
                bad.append({"path": path, "sha256": sha, "status": status, "actual_sha256": actual})
            if isinstance(evidence, dict) and isinstance(evidence.get("sha256"), str):
                sha = evidence["sha256"]
                fallback_paths = list(frozen_hash_paths.get(sha, []))
                source = Path(candidate["source"])
                if source.suffix == ".json":
                    if field == "evidence_before":
                        fallback_paths.extend([source.with_name(source.stem + "-before.png"), source.with_suffix(".png")])
                    elif field == "evidence_after":
                        fallback_paths.append(source.with_name(source.stem + "-after.png"))
                    else:
                        fallback_paths.append(source.with_suffix(".png"))
                if row.get("event") == "battle_end" and isinstance(evidence.get("path"), str):
                    fallback_paths.append(Path(evidence["path"]).parent / f"result-{row['battle']:02d}.png")
                for fallback in fallback_paths:
                    status, actual = verify(str(fallback), sha)
                    if status == "verified":
                        return {"path": str(fallback), "sha256": sha, "status": status, "actual_sha256": actual}
        return next((ref for ref in bad if ref["status"] == "hash_mismatch"), bad[0] if bad else {"status": "no_reference"})

    rows = []
    examples = []
    all_metrics = defaultdict(Counter)
    for key, record in sorted(losses.items()):
        strategy, session, battle = key
        items = sorted(events[key].values(), key=lambda e: (e["row"].get("time", ""), e["line"]))
        end = ends.get(key)
        if end:
            end_evidence = image_ref(end)
        else:
            status, actual = verify(record.get("evidence"), record.get("evidence_hash"))
            end_evidence = {"path": record.get("evidence"), "sha256": record.get("evidence_hash"), "status": status, "actual_sha256": actual}
        plays = [item for item in items if item["row"]["event"] == "play"]
        observes = [item for item in items if item["row"]["event"] == "observe"]
        metrics = Counter()
        for item in plays + observes:
            row = item["row"]
            ref = image_ref(item, "evidence_before" if row["event"] == "play" else "evidence")
            if ref["status"] == "verified":
                metrics["verified_decision_frames"] += 1
                metrics["verified_" + row["event"] + "_frames"] += 1
            else:
                metrics["decision_frame_" + ref["status"]] += 1
            if row["event"] == "play":
                after = image_ref(item, "evidence_after")
                if ref["status"] == "verified" and after["status"] == "verified":
                    metrics["verified_before_after_pairs"] += 1
                category = (row.get("decision") or {}).get("category", "unknown")
                metrics["category_" + category] += 1
                metrics["confirmed_plays"] += int(row.get("confirmed") is True)
            cues = row.get("cues") or {}
            enemies = cues.get("enemies") or []
            far = cues.get("far_warnings") or []
            threats = cues.get("threats") or []
            if row["event"] == "observe" and isinstance(cues.get("elixir"), (int, float)) and cues["elixir"] >= 10:
                metrics["full_elixir_observe_samples"] += 1
                if enemies or threats:
                    metrics["full_elixir_pressure_observe_samples"] += 1
            hp = cues.get("own_tower_fill") or {}
            low_lanes = [lane for lane, fill in hp.items() if isinstance(fill, (float, int)) and fill <= 0.25]
            if low_lanes:
                metrics["low_own_tower_decision_samples"] += 1
                if not enemies and not threats and far:
                    metrics["low_tower_far_only_decision_samples"] += 1
                    if ref["status"] == "verified" and len(examples) < 80:
                        examples.append({"strategy": strategy, "session": session, "battle": battle, "time": row.get("time"), "finding": "low_tower_far_only_observation", "cues": cues, "decision": row.get("decision"), "evidence": ref, "source": item["source"], "line": item["line"]})
            if ref["status"] == "verified" and row["event"] == "observe" and cues.get("elixir") == 10 and (enemies or threats) and len(examples) < 80:
                examples.append({"strategy": strategy, "session": session, "battle": battle, "time": row.get("time"), "finding": "full_elixir_pressure_observe", "cues": cues, "hand": row.get("hand"), "policy_observation": row.get("policy_observation"), "evidence": ref, "source": item["source"], "line": item["line"]})
        all_metrics[strategy].update(metrics)
        tier = (
            "RESULT_AND_DECISION_IMAGE" if end_evidence["status"] == "verified" and metrics["verified_decision_frames"]
            else "RESULT_IMAGE_ONLY" if end_evidence["status"] == "verified"
            else "DECISION_IMAGE_RESULT_LOG" if metrics["verified_decision_frames"]
            else "LOG_ONLY"
        )
        rows.append({
            "strategy": strategy, "session": session, "battle": battle, "time": record["time"],
            "result": record["result"], "policy": record["policy"], "conflict": record["conflict"],
            "tier": tier, "result_image_status": end_evidence["status"],
            "result_image": end_evidence.get("path"), "expected_result_sha256": end_evidence.get("sha256"),
            "actual_result_sha256": end_evidence.get("actual_sha256"),
            "decision_trace_events": len(plays) + len(observes), "play_events": len(plays), "observe_events": len(observes),
            "verified_decision_frames": metrics["verified_decision_frames"],
            "verified_play_frames": metrics["verified_play_frames"],
            "verified_observe_frames": metrics["verified_observe_frames"],
            "verified_before_after_pairs": metrics["verified_before_after_pairs"],
            "original_end_source": end["source"] if end else None, "original_end_line": end["line"] if end else None,
            "legacy_chronological_association": session.startswith("legacy:"),
            "full_elixir_pressure_observe_samples": metrics["full_elixir_pressure_observe_samples"],
            "low_tower_far_only_decision_samples": metrics["low_tower_far_only_decision_samples"],
            "metrics": dict(metrics),
        })
    def write_json(name, data):
        (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_json("historical-loss-evidence.json", rows)
    write_json("historical-decision-examples.json", examples)
    fields = [name for name in rows[0] if name != "metrics"]
    with (OUT / "historical-loss-evidence.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "source": "read-only database and authoritative historical JSONL plus retained archive JSONL",
        "database_unique_key": ["strategy", "session", "battle"],
        "database_counts": dict(counts),
        "database_total_completed": len(db_rows),
        "database_total_losses": sum(v[LOSS] for v in counts.values()),
        "historical_losses": len(rows),
        "historical_by_strategy": {
            strategy: {
                "losses": len([r for r in rows if r["strategy"] == strategy]),
                "tiers": dict(Counter(r["tier"] for r in rows if r["strategy"] == strategy)),
                "result_image_statuses": dict(Counter(r["result_image_status"] for r in rows if r["strategy"] == strategy)),
                "losses_with_decision_trace": sum(r["decision_trace_events"] > 0 for r in rows if r["strategy"] == strategy),
                "losses_with_verified_decision_frames": sum(r["verified_decision_frames"] > 0 for r in rows if r["strategy"] == strategy),
                "metrics": dict(all_metrics[strategy]),
            } for strategy in TRACES
        },
        "source_event_counts": source_counts,
        "archive_event_files_checked": [str(path) for path in sorted(archive_paths)],
        "archive_direct_json_events": direct_archive_events,
        "archive_json_files_checked": len(archive_json_paths),
        "sha_named_frozen_images_indexed": sum(len(value) for value in frozen_hash_paths.values()),
        "snapshot_manifest_entries_indexed": snapshot_manifest_entries,
        "archive_event_duplicates_collapsed": archived_dupes,
        "archive_new_events": archive_additions,
        "unique_image_paths_hashed_or_checked": len(hash_cache),
        "io_errors": hash_io_errors,
        "definitions": {
            "result_verified": "Current image SHA-256 equals the original result-event SHA-256; this proves unchanged provenance, not an independent new visual outcome review.",
            "decision_verified": "Current play/observe image SHA-256 equals original event SHA-256, or SHA-linked frozen archive image equals that exact hash.",
            "reviewable_failure": "Failure result with verified result screenshot; attribution additionally needs verified decision image and decision trace.",
            "result_log_only": "Recorded failure remains in inventory even when PNG was never recorded, is missing, or ring file now mismatches.",
        },
        "limitations": [
            "No UI or device control; no original evidence or database modified.",
            "Decision trace observations are sampled and cannot measure exact idle intervals.",
            "A verified decision frame permits a bounded review; it does not imply a complete video/replay or a uniquely proven cause of defeat.",
            "Legacy traces without session are associated only by original chronological battle number before their corresponding end; ambiguous legacy identity is explicitly marked.",
            "Historical manual unknown-to-loss reviews are separate from database automatic-loss counts, avoiding unreviewed promotion.",
            "The current random trace is assigned to the root's independent audit; database random counts are included only for global reconciliation.",
        ],
    }
    write_json("historical-summary.json", summary)
    print(json.dumps(summary, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
