"""Recheck SHA-linked historical visual reviews without changing original outcomes."""

import csv
import hashlib
import json
import sqlite3
from pathlib import Path

from audit_historical_losses import ARCHIVE_ROOTS, EXCLUDED, OUT, ROOT


def main():
    db = sqlite3.connect((ROOT / "outputs/cn-battle-history.sqlite3").as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    unknowns = {
        (row["strategy"], row["session"], row["battle"]): dict(row)
        for row in db.execute("SELECT * FROM battles WHERE result='未知' AND conflict=0")
    }
    db.close()
    candidates = []
    sha_paths = {}
    for folder in ARCHIVE_ROOTS:
        for path in (ROOT / "work" / folder).rglob("*.png"):
            if any(part in EXCLUDED or part.startswith("pytest") for part in path.parts):
                continue
            if len(path.stem) == 64:
                sha_paths.setdefault(path.stem, []).append(path)
        for path in (ROOT / "work" / folder).rglob("*.json"):
            if any(part in EXCLUDED or part.startswith("pytest") for part in path.parts):
                continue
            if "review" not in path.name:
                continue
            try:
                parsed = json.loads(path.read_text(encoding="utf-8-sig"))
            except (ValueError, OSError):
                continue
            records = parsed if isinstance(parsed, list) else [parsed]
            for review in records:
                if not isinstance(review, dict) or review.get("reviewed_result") != "失败":
                    continue
                key = ("hog", review.get("session"), review.get("battle"))
                if key in unknowns:
                    candidates.append((key, path, review))
    rows = {}
    for key, source, review in candidates:
        sha = review.get("sha256") or review.get("evidence_sha256")
        possible = [review.get("evidence_file"), review.get("image"), unknowns[key].get("evidence")]
        possible.extend(sha_paths.get(sha, []))
        found = None
        for path in possible:
            if not path:
                continue
            path = Path(path)
            if path.is_relative_to(ROOT) and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == sha:
                found = str(path)
                break
        rows[key] = {
            "strategy": key[0], "session": key[1], "battle": key[2],
            "original_result": unknowns[key]["result"], "reviewed_result": "失败",
            "time": unknowns[key]["time"], "review_source": str(source),
            "review_sha256": sha, "verified_review_image": found,
            "current_sha_status": "verified" if found else "not_verified",
            "reviewer": review.get("reviewer") or review.get("reason"),
            "past_visual_review": True,
        }
    records = list(rows.values())
    (OUT / "historical-reviewed-unknowns.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if records:
        with (OUT / "historical-reviewed-unknowns.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
    print(json.dumps({"unknown_database_rows": len(unknowns), "unknown_with_past_loss_review": len(records), "loss_review_current_sha_verified": sum(row["current_sha_status"] == "verified" for row in records), "reviews": records}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
