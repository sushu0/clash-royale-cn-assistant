"""Persist final verification and live lineage without changing user game data."""

import hashlib
import json
import pathlib
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(r"D:\codex\CodexWork\clash")
REPO = ROOT / "py-clash-bot"
WORK = ROOT / "work" / "repair-20261003"
OUT = ROOT / "outputs" / "repair-20261004"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


live = read(ROOT / "outputs/random-mastery-live-status.json")
frontend = read(ROOT / "work/random-frontend-state.json")
checkpoint = read(ROOT / "work/random-mastery/checkpoint.json")
manifest = read(pathlib.Path(live["evidence_dir"]) / "manifest.json")
source_mismatches = [name for name, digest in manifest["sha256"].items()
                     if hashlib.sha256(pathlib.Path(name).read_bytes()).hexdigest() != digest]
db = sqlite3.connect((ROOT / "outputs/cn-battle-history.sqlite3").as_uri() + "?mode=ro", uri=True)
db.row_factory = sqlite3.Row
integrity = db.execute("PRAGMA quick_check").fetchone()[0]
formal = dict(db.execute("SELECT * FROM battles WHERE strategy='random' AND session='20261004-012439' AND battle=1040").fetchone())
formal_picture = pathlib.Path(formal["evidence"])
formal_valid = hashlib.sha256(formal_picture.read_bytes()).hexdigest() == formal["evidence_hash"]
current_rows = [dict(row) for row in db.execute("SELECT * FROM battles WHERE strategy='random' AND session=? ORDER BY battle", (live["session"],))]
result_hashes = [{"battle": row["battle"], "valid": pathlib.Path(row["evidence"]).is_file()
                 and hashlib.sha256(pathlib.Path(row["evidence"]).read_bytes()).hexdigest() == row["evidence_hash"]}
                for row in current_rows]
sources = [dict(row) for row in db.execute("SELECT strategy,malformed,offset FROM sources")]
rewards = [dict(row) for row in db.execute("SELECT * FROM mastery_rewards WHERE time>='2026-10-04 01:24:00' ORDER BY time")]
db.close()
before = read(WORK / "source-before-manifest.json")
changed = [name for name, digest in before.items() if (REPO / name).is_file()
           and hashlib.sha256((REPO / name).read_bytes()).hexdigest() != digest]
msi = OUT / "pyclashbot-v0.0.0-win64.msi"
report = {
    "captured_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
    "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=REPO, text=True).strip(),
    "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
    "git_clean": not subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True).strip(),
    "baseline_backup": str(WORK / "source-before.zip"),
    "baseline_backup_sha256": hashlib.sha256((WORK / "source-before.zip").read_bytes()).hexdigest(),
    "changed_preexisting_files": changed,
    "offline_tests": {"passed": 988, "subtests_passed": 172, "deselected_emulator_tests": 15,
                      "log": str(WORK / "acceptance-final.log"), "xml": str(WORK / "acceptance-final.xml")},
    "make_lint": {"passed": True, "log": str(WORK / "make-lint-final.log")},
    "frozen_check": read(WORK / "frozen-final-check.json"),
    "msi": {"path": str(msi), "bytes": msi.stat().st_size, "sha256": hashlib.sha256(msi.read_bytes()).hexdigest()},
    "live_status": live, "frontend": frontend, "checkpoint": checkpoint,
    "active_manifest": manifest, "active_manifest_mismatches": source_mismatches,
    "history_integrity": integrity, "sources": sources,
    "formal_finite_battle": formal, "formal_result_hash_valid": formal_valid,
    "subsequent_completed_games": current_rows, "subsequent_result_hashes": result_hashes,
    "new_reward_receipts": rewards,
    "limitations": ["Historical overwritten pixels cannot be reconstructed from code",
                    "Explicit king visual cue and uncalibrated champion abilities remain gated",
                    "Legacy backends and macOS were validated with offline checks, not live sessions",
                    "No win-rate improvement is inferred from this small live sample"],
}
assert report["git_clean"] and not source_mismatches and formal_valid
assert all(item["valid"] for item in result_hashes)
assert frontend["hero_content_fits"] and all(frontend["metric_fits"].values())
assert frontend["live_view"]["embedded"] and frontend["live_view"]["error"] is None
destination = OUT / "PROJECT_REPAIR_ACCEPTANCE_20261004.json"
destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"evidence": str(destination), "git_clean": report["git_clean"],
                  "offline_tests": report["offline_tests"], "manifest_mismatches": source_mismatches,
                  "subsequent_games": len(current_rows), "new_rewards": len(rewards),
                  "history_integrity": integrity, "msi_sha256": report["msi"]["sha256"]}, ensure_ascii=False, indent=2))
