"""Extract representative raw rows without modifying source evidence."""

import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(r"D:\codex\CodexWork\clash")
OUT = ROOT / "work/loss-optimization-20261004/agent-evidence"
sys.path.insert(0, str(ROOT / "py-clash-bot"))
from pyclashbot.bot.random_card_roles import role_for  # noqa: E402

selected = {1041, 1049, 1172, 1257, 1259, 1260, 1261}
rows = {battle: [] for battle in selected}
with (ROOT / "outputs/cn-random-mastery.jsonl").open("rb") as stream:
    for lineno, raw in enumerate(stream, 1):
        row = json.loads(raw)
        battle = row.get("battle")
        if battle in selected and str(row.get("session", "")).startswith("20261004"):
            row["source_line"] = lineno
            rows[battle].append(row)

examples = []
for battle, group in rows.items():
    (OUT / f"battle-{battle}-extracted.json").write_text(json.dumps(group, ensure_ascii=False, indent=2), encoding="utf-8")
    for row in group:
        event = row.get("event")
        cues = row.get("cues") or {}
        decision = row.get("decision") or {}
        if event == "play" and cues.get("far_warnings") and decision.get("category") == "cycle":
            card = role_for(decision.get("variant"), decision.get("cost"))
            air = []
            for item in row.get("hand", []):
                role = role_for(item.get("variant") or item.get("card"), item.get("cost"))
                if role and item.get("available") and role.air and role.role in {"fighter", "swarm", "ranged", "building", "cycle"}:
                    air.append(role.name)
            if card and card.air and len(air) == 1:
                following = [r for r in group if r["source_line"] > row["source_line"] and r.get("cues", {}).get("enemies")][:3]
                examples.append({"kind": "only_available_anti_air_cycle", "battle": battle, "trace": row, "following_enemy_observations": following})
        if event == "play_evidence":
            evidence = row.get("evidence") or {}
            path = Path(evidence.get("path", ""))
            if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == evidence.get("sha256"):
                examples.append({"kind": "hash_verified_play_frame", "battle": battle, "trace": row})
        if event == "strategy_observe" and cues.get("elixir") == 10:
            examples.append({"kind": "full_elixir_hold", "battle": battle, "trace": row})

(OUT / "representative-examples.json").write_text(json.dumps(examples, ensure_ascii=False, indent=2), encoding="utf-8")
losses = list(csv.DictReader((OUT / "all-random-losses.csv").open(encoding="utf-8-sig")))
v23 = [r for r in losses if r["rule_version"] == "random-rules-v2.3-20261003-evidence-gates"]
print(json.dumps({
    "v23_result_status": Counter(r["result_evidence_status"] for r in v23),
    "all_loss_play_counts": sum(int(r["play_trace_count"]) for r in losses),
    "all_loss_unconfirmed_play_counts": sum(int(r["unconfirmed_play_trace_count"]) for r in losses),
    "v23_play_counts": sum(int(r["play_trace_count"]) for r in v23),
    "v23_unconfirmed_play_counts": sum(int(r["unconfirmed_play_trace_count"]) for r in v23),
    "representative_rows": [{"kind": r["kind"], "battle": r["battle"], "line": r["trace"]["source_line"], "time": r["trace"]["time"],
                             "card": r["trace"].get("card_hint"), "evidence": r["trace"].get("evidence")} for r in examples],
}, ensure_ascii=False, indent=2))
