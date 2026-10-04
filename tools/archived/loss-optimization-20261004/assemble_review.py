"""Merge already reviewed inventories without changing authoritative history."""

import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(r"D:\codex\CodexWork\clash")
TASK = ROOT / "work/loss-optimization-20261004"
OUTPUT = ROOT / "outputs/loss-review-20261005"
OUTPUT.mkdir(parents=True, exist_ok=True)


def rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


merged = []
for row in rows(TASK / "agent-evidence/all-random-losses.csv"):
    verified = row["result_evidence_status"] == "hash_matches"
    merged.append({
        "strategy": "random", "session": row["session"], "battle": row["battle"],
        "time": row["time"], "original_result": row["outcome"], "reviewed_result": "失败",
        "counting_scope": "original_recorded_failure", "policy": row["policy"], "rule_version": row["rule_version"],
        "result_sha_verified": verified,
        "result_path": row["result_evidence_path"], "result_sha256": row["result_sha256"],
        "decision_trace_count": row["decision_trace_count"], "verified_play_frames": row["play_frame_hash_matches"],
        "trace_source": str(ROOT / "outputs/cn-random-mastery.jsonl"), "result_line": row["source_result_line"],
        "scenarios": row["scenarios"],
    })
for row in rows(TASK / "agent-history/historical-loss-evidence.csv"):
    merged.append({
        "strategy": row["strategy"], "session": row["session"], "battle": row["battle"],
        "time": row["time"], "original_result": row["result"], "reviewed_result": "失败",
        "counting_scope": "original_recorded_failure", "policy": row["policy"], "rule_version": "",
        "result_sha_verified": row["result_image_status"] == "verified",
        "result_path": row["result_image"], "result_sha256": row["expected_result_sha256"],
        "decision_trace_count": row["decision_trace_events"], "verified_play_frames": row["verified_play_frames"],
        "trace_source": row["original_end_source"], "result_line": row["original_end_line"], "scenarios": "",
    })
for row in rows(TASK / "agent-history/historical-reviewed-unknowns.csv"):
    merged.append({
        "strategy": row["strategy"], "session": row["session"], "battle": row["battle"],
        "time": row["time"], "original_result": row["original_result"], "reviewed_result": row["reviewed_result"],
        "counting_scope": "separate_reviewed_unknown", "policy": "", "rule_version": "",
        "result_sha_verified": row["current_sha_status"] == "verified",
        "result_path": row["verified_review_image"], "result_sha256": row["review_sha256"],
        "decision_trace_count": "", "verified_play_frames": "",
        "trace_source": row["review_source"], "result_line": "", "scenarios": "",
    })
keys = [(r["strategy"], r["session"], r["battle"]) for r in merged]
assert len(keys) == len(set(keys)) == 1932
assert sum(r["counting_scope"] == "original_recorded_failure" for r in merged) == 1928
assert sum(r["result_sha_verified"] for r in merged) == 1267
merged.sort(key=lambda r: (r["time"], r["strategy"], r["session"], int(r["battle"])))
with (OUTPUT / "all-reviewed-failures.csv").open("w", encoding="utf-8-sig", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=list(merged[0]))
    writer.writeheader()
    writer.writerows(merged)
summary = {
    "recorded_failures": 1928, "separate_reviewed_unknowns": 4, "reviewed_rows": 1932,
    "recorded_failure_result_images_verified": 1263, "all_reviewed_result_images_verified": 1267,
    "recorded_failures_without_verified_result_image": 665,
    "by_strategy": dict(Counter(r["strategy"] for r in merged if r["counting_scope"] == "original_recorded_failure")),
    "original_history_modified": False, "live_game_played": False,
    "sources": [str(TASK / "agent-evidence/random-loss-audit.json"), str(TASK / "agent-history/historical-summary.json")],
    "limitations": [
        "Retained frames and traces are sampled; they do not constitute full video replays.",
        "Failure scenarios are local observed decision defects, not unique proven causes for each defeat.",
        "No measured improvement in live win rate has been established.",
    ],
}
(OUTPUT / "review-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False))
