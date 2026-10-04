"""Bounded verification of the fixed v4 engineering session and changed files."""

import hashlib
import json
from collections import Counter
from pathlib import Path

TASK = Path(r"D:\codex\CodexWork\clash")
REPO = TASK / "py-clash-bot"
SESSION = "20260929-115207"
FOLDER = Path(__file__).parent
CHANGED = ["pyclashbot/bot/double_air_567_strategy.py", "scripts/cn_bot_control.py",
           "pyclashbot/utils/battle_history.py", "tests/test_cn_567_strategy.py",
           "tests/test_cn_567_v4_strategy.py", "tests/test_battle_history.py"]


def main():
    rows = []
    with (TASK / "outputs/cn-567-strategy.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row.get("session") == SESSION:
                rows.append(row)
    ends = [r for r in rows if r["event"] == "battle_end"]
    plays = [r for r in rows if r["event"] == "play"]
    manifest = json.loads((TASK / f"work/567-validation/{SESSION}/policy-manifest.json").read_text(encoding="utf-8"))
    hashes = {name: hashlib.sha256((REPO / name).read_bytes()).hexdigest() for name in CHANGED}
    evidence = []
    for row in ends:
        item = row["evidence"]
        path = Path(item["path"])
        evidence.append({"battle": row["battle"], "result": row["result"], "path": str(path),
                         "hash_matches": path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]})
    report = {"session": SESSION, "results": dict(Counter(r["result"] for r in ends)),
              "completed": len(ends), "attempts": len(plays), "confirmed": sum(r["confirmed"] for r in plays),
              "events": dict(Counter(r["event"] for r in rows)),
              "categories": dict(Counter(r["decision"]["category"] for r in plays if r["confirmed"])),
              "zap_transitions": sum(r["decision"]["card"] == "zap" and r["decision"]["category"] == "defense_cycle" for r in plays),
              "result_evidence": evidence, "source_sha256": hashes,
              "frozen_policy_matches": hashes[CHANGED[0]] == manifest["source_sha256"]["double_air_567_strategy.py"],
              "batch_returned_to_lobby": any(r["event"] == "batch_complete" for r in rows),
              "last_event": rows[-1]["event"] if rows else None,
              "last_at": rows[-1]["time"] if rows else None}
    (FOLDER / "live-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
