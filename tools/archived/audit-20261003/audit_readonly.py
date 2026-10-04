"""Offline audit probes. Real game/process/log data are read only."""
from __future__ import annotations

import ast
import collections
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(r"D:\codex\CodexWork\clash")
REPO = ROOT / "py-clash-bot"
HERE = ROOT / "work" / "audit-20261003"
sys.path.insert(0, str(REPO))

from pyclashbot.utils.battle_history import BattleHistory
from pyclashbot.utils import platform as project_platform


def put_json(path, row):
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    report = {"captured_at_local": time.strftime("%Y-%m-%d %H:%M:%S"), "probes": {}}
    synthetic = HERE / "synthetic"
    synthetic.mkdir(exist_ok=True)

    # Cache test uses only a synthetic directory, including import-time migration.
    project_platform.get_app_data_dir = lambda *_args: str(synthetic / "cache")
    from pyclashbot.utils.caching import FileCache

    cache = FileCache("probe.json")
    first = cache.cache_data({"first": 1})
    second = cache.cache_data({"second": 2})
    report["probes"]["cache_merge"] = {"first": first, "second": second,
                                         "saved": cache.load_data()}

    bad_cases = {
        "null_receipts": ("rewards", {"event": "rewards_confirmed", "claim_id": "x", "receipts": None}),
        "list_evidence": ("rewards", {"event": "rewards_confirmed", "claim_id": "x",
                                       "receipts": [{"id": "1", "amount": 1, "evidence": []}]}),
        "string_observation": ("random", {"event": "strategy_observe", "session": "s",
                                             "policy_observation": "invalid"}),
    }
    for name, (strategy, row) in bad_cases.items():
        source = synthetic / f"{name}.jsonl"
        put_json(source, row)
        store = BattleHistory(synthetic / f"{name}.sqlite3")
        try:
            store.ingest(source, strategy)
        except Exception as error:
            report["probes"][name] = {"exception": type(error).__name__, "message": str(error)}
        else:
            report["probes"][name] = {"result": "handled"}
        finally:
            store.close()

    # Sample immutable battle metadata and verify its referenced screenshot bytes.
    ring = collections.Counter()
    examples = []
    battles = sorted((ROOT / "work" / "random-mastery").glob("*/battle-*.json"))
    for path in battles:
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
            evidence = row["evidence"]
            picture = Path(evidence["path"])
            if not picture.is_relative_to(ROOT):
                ring["out_of_scope"] += 1
                continue
            if not picture.exists():
                ring["missing"] += 1
                continue
            actual = hashlib.sha256(picture.read_bytes()).hexdigest()
            status = "matches" if actual == evidence["sha256"] else "overwritten"
            ring[status] += 1
            if status == "overwritten" and len(examples) < 3:
                examples.append({"record": str(path), "image": str(picture),
                                 "expected": evidence["sha256"], "actual": actual})
        except (OSError, ValueError, KeyError, TypeError):
            ring["invalid"] += 1
    report["result_screenshot_integrity"] = {"records": len(battles), "counts": dict(ring), "examples": examples}

    # Read the existing index using sqlite mode=ro; never initialize/migrate it.
    database = ROOT / "outputs" / "cn-battle-history.sqlite3"
    connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        report["database_integrity"] = connection.execute("PRAGMA quick_check").fetchone()[0]
        report["battle_totals"] = [dict(row) for row in connection.execute(
            "SELECT strategy,COUNT(*) AS games,SUM(result='胜利') AS wins,SUM(result='失败') AS losses,"
            "SUM(result='未知') AS unknown,SUM(conflict) AS conflicts FROM battles GROUP BY strategy")]
        report["random_policy_results"] = [dict(row) for row in connection.execute(
            "SELECT policy,COUNT(*) AS games,SUM(result='胜利') AS wins,MIN(time) AS first_at,MAX(time) AS last_at "
            "FROM battles WHERE strategy='random' GROUP BY policy")]
        report["sources"] = [dict(row) for row in connection.execute("SELECT * FROM sources")]
    finally:
        connection.close()

    # Stream the trace to a fixed initial byte boundary while the bot keeps running.
    trace = ROOT / "outputs" / "cn-random-mastery.jsonl"
    byte_boundary = trace.stat().st_size
    counts = collections.Counter()
    results = collections.Counter()
    attempts = confirmed = 0
    finished = 0
    timing_samples = []
    last_time = None
    sessions = set()
    with trace.open("rb") as stream:
        while stream.tell() < byte_boundary:
            raw = stream.readline()
            if not raw.endswith(b"\n") or stream.tell() > byte_boundary:
                break
            try:
                row = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                counts["malformed"] += 1
                continue
            if not isinstance(row, dict):
                counts["non_object"] += 1
                continue
            event = row.get("event", "missing_event")
            counts[event] += 1
            if row.get("session"):
                sessions.add(row["session"])
            last_time = row.get("time")
            if event == "battle_finished":
                finished += 1
                results[row.get("outcome", "未知")] += 1
                attempts += row.get("card_attempts", 0)
                confirmed += row.get("cards_confirmed", 0)
            if event == "play" and isinstance(row.get("timings"), dict):
                duration = row["timings"].get("total_ms")
                if isinstance(duration, (float, int)):
                    timing_samples.append(duration)
    timing_samples.sort()
    report["random_trace"] = {"byte_boundary": byte_boundary, "last_time": last_time,
                              "event_counts": dict(counts), "sessions": len(sessions),
                              "raw_finished_events": finished, "raw_outcomes": dict(results),
                              "attempts": attempts, "confirmed": confirmed,
                              "confirmation_fraction": confirmed / attempts if attempts else None,
                              "timing_samples": len(timing_samples),
                              "play_p50_ms": timing_samples[len(timing_samples) // 2] if timing_samples else None,
                              "play_p95_ms": timing_samples[int((len(timing_samples) - 1) * .95)] if timing_samples else None}

    sources = sorted([*REPO.rglob("*.py"), *REPO.rglob("*.ps1")])
    sources = [path for path in sources if ".git" not in path.parts and "__pycache__" not in path.parts]
    syntax_failures = []
    lines = 0
    for path in sources:
        if path.suffix == ".py":
            content = path.read_text(encoding="utf-8-sig")
            lines += len(content.splitlines())
            try:
                ast.parse(content, filename=str(path))
            except SyntaxError as error:
                syntax_failures.append({"path": str(path), "error": str(error)})
    report["source_inventory"] = {"python_files": sum(path.suffix == ".py" for path in sources),
                                  "powershell_files": sum(path.suffix == ".ps1" for path in sources),
                                  "python_lines": lines, "syntax_failures": syntax_failures,
                                  "files": [{"path": str(path.relative_to(REPO)), "bytes": path.stat().st_size,
                                             "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in sources]}
    destination = HERE / "root-audit-evidence.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {key: value for key, value in report.items() if key != "source_inventory"}
    compact["source_inventory"] = {key: value for key, value in report["source_inventory"].items() if key != "files"}
    print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
