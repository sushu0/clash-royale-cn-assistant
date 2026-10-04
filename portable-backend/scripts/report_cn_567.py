"""Summarize persisted 567 sessions without promoting unknowns to wins."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def build_report(trace: Path, session: str | None = None) -> dict:
    sessions = {}
    truncated_lines = 0
    with trace.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                truncated_lines += 1
                continue
            name = row.get("session")
            if not name or (session and name != session):
                continue
            entry = sessions.setdefault(
                name,
                {
                    "session": name,
                    "policy": row.get("policy_version"),
                    "completed": 0,
                    "results": Counter(),
                    "deployments": 0,
                    "deployment_failures": 0,
                    "battles": [],
                    "recoveries": 0,
                    "consecutive_closed_loops": 0,
                    "validation_passed": False,
                    "categories": Counter(),
                    "cards": Counter(),
                    "bomber_forms": {},
                },
            )
            if row["event"] == "play":
                entry["deployments"] += 1
                entry["deployment_failures"] += not row.get("confirmed", False)
                if row["decision"]["card"] == "bomber":
                    variant = row["decision"].get("variant")
                    form = (
                        "evolved"
                        if variant in {"evo_bomber", "cn_evo_bomber"}
                        else "normal"
                        if variant == "bomber"
                        else "uncertain"
                    )
                    counter = entry["bomber_forms"].setdefault(form, {"attempts": 0, "confirmed": 0})
                    counter["attempts"] += 1
                    counter["confirmed"] += int(bool(row.get("confirmed")))
                if row.get("confirmed"):
                    entry["categories"][row["decision"]["category"]] += 1
                    entry["cards"][row["decision"]["card"]] += 1
            if row["event"] == "battle_end":
                entry["completed"] += 1
                outcome = row.get("result", "未知")
                entry["results"][outcome if outcome in {"胜利", "失败"} else "未知"] += 1
                evidence = row.get("evidence") or {}
                file = Path(evidence.get("path", ""))
                verified = file.is_file() and hashlib.sha256(file.read_bytes()).hexdigest() == evidence.get("sha256")
                entry["battles"].append(
                    {
                        "battle": row["battle"],
                        "result": outcome,
                        "deployments": row["attempts"],
                        "confirmed": row["confirmed"],
                        "opening_45s": row.get("opening_45s"),
                        "bomber_forms": row.get("bomber_forms", {}),
                        "result_evidence_verified": verified,
                        "result_evidence": evidence.get("path"),
                    }
                )
            if row["event"] == "recovery":
                entry["recoveries"] += 1
                entry["consecutive_closed_loops"] = 0
            if row["event"] == "closed_loop":
                entry["consecutive_closed_loops"] = row["consecutive"]
            if row["event"] == "validation_passed":
                entry["validation_passed"] = True
            entry["latest_event"] = row["event"]
            entry["updated_at"] = row["time"]
    for entry in sessions.values():
        entry["known_results"] = entry["results"]["胜利"] + entry["results"]["失败"]
        entry["wins_per_completed"] = entry["results"]["胜利"] / entry["completed"] if entry["completed"] else None
    return {
        "source": str(trace),
        "truncated_lines": truncated_lines,
        "sessions": list(sessions.values()),
        "metric_note": "Tower damage uses observed left/right princess health-bar fractions; unknown is null. It is not numeric HP OCR, and king tower damage is not measured.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/567-sessions-report.json")
    args = parser.parse_args()
    report = build_report(ROOT / "outputs/cn-567-strategy.jsonl", args.session)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for entry in report["sessions"]:
        print(
            entry["session"],
            "completed",
            entry["completed"],
            "results",
            dict(entry["results"]),
            "deployments",
            entry["deployments"],
            "failed",
            entry["deployment_failures"],
            "closed_loops",
            entry["consecutive_closed_loops"],
            "passed",
            entry["validation_passed"],
        )


if __name__ == "__main__":
    main()
