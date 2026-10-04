"""Compare recorded wrapper versions with per-session strategy source hashes."""
import collections
import json
import sqlite3
from pathlib import Path

ROOT = Path(r"D:\codex\CodexWork\clash")
db = ROOT / "outputs" / "cn-battle-history.sqlite3"
connection = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)
rows = connection.execute("SELECT policy,session,COUNT(*),SUM(result='胜利') FROM battles WHERE strategy='random' GROUP BY policy,session").fetchall()
connection.close()
policies = {}
for policy, session, count, wins in rows:
    entry = policies.setdefault(policy, {"games": 0, "wins": 0, "strategy_hashes": {}, "missing_manifest_sessions": []})
    entry["games"] += count
    entry["wins"] += wins
    manifest = ROOT / "work" / "random-mastery" / session / "manifest.json"
    if not manifest.is_file():
        entry["missing_manifest_sessions"].append(session)
        continue
    data = json.loads(manifest.read_text(encoding="utf-8"))
    hashes = data.get("sha256", {})
    digest = next((value for key, value in hashes.items() if key.endswith("random_deck_strategy.py")), None)
    if digest:
        variant = entry["strategy_hashes"].setdefault(digest, {"sessions": [], "games": 0, "wins": 0})
        variant["sessions"].append(session)
        variant["games"] += count
        variant["wins"] += wins
report = {"policies": policies, "mixed_strategy_source_policies": [key for key, entry in policies.items() if len(entry["strategy_hashes"]) > 1]}
path = ROOT / "work" / "audit-20261003" / "lineage-evidence.json"
path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({key: entry for key, entry in policies.items() if len(entry["strategy_hashes"]) > 1}, ensure_ascii=True, indent=2))
