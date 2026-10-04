"""Read-only acceptance of the two original production pause reports."""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "py-clash-bot"))

from pyclashbot.utils.cn_error_report import list_error_reports
from pyclashbot.utils.persistence import atomic_write_json

catalog_root = ROOT / "outputs" / "error-reports"
source_files = [path for folder in catalog_root.iterdir() if folder.is_dir() and not folder.name.startswith(".") for path in folder.iterdir() if path.is_file()]
before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files}
catalog = list_error_reports(catalog_root)
checks = []
for row in catalog:
    report = json.loads(Path(row["report_json"]).read_text(encoding="utf-8"))
    screenshot = report.get("screenshot", {})
    actual_hash = hashlib.sha256(Path(row["game_png"]).read_bytes()).hexdigest() if row["game_png"] else None
    checks.append({
        "event_id": row["event_id"], "created_at": row["created_at"], "occurred_at": row["occurred_at"], "reason": row["reason"],
        "session": row["session"], "report_dir": row["report_dir"], "report_md": row["report_md"], "report_json": row["report_json"],
        "game_png": row["game_png"], "pending": row["pending"], "incomplete": row["incomplete"], "snapshot_errors": report.get("snapshot_errors"),
        "image_size": [screenshot.get("width"), screenshot.get("height")], "image_sha256": actual_hash,
        "image_hash_matches": actual_hash == screenshot.get("sha256"),
    })
after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files}
result = {"passed": len(catalog) == 2 and before == after and all(not row["incomplete"] and not row["pending"] and row["image_hash_matches"] and row["snapshot_errors"] == {} for row in checks), "count": len(catalog), "history_files_unchanged": before == after, "catalog": checks, "source_hashes": before}
atomic_write_json(Path(__file__).with_name("history-verification.json"), result)
print(json.dumps(result, ensure_ascii=False))
