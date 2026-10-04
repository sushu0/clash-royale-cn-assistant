"""Run the project's current result classifier on retained historical loss PNGs."""

import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(r"D:\codex\CodexWork\clash")
OUT = ROOT / "work/loss-optimization-20261004/agent-history"
sys.path.insert(0, str(ROOT / "py-clash-bot"))

import cv2  # noqa: E402

from pyclashbot.bot.cn_1v1_loop import ChineseVision  # noqa: E402


def main():
    vision = ChineseVision()
    cv2.setNumThreads(2)
    evidence = json.loads((OUT / "historical-loss-evidence.json").read_text(encoding="utf-8"))
    reviewed = json.loads((OUT / "historical-reviewed-unknowns.json").read_text(encoding="utf-8"))
    candidates = [
        {
            "strategy": row["strategy"], "session": row["session"], "battle": row["battle"],
            "cohort": "automatic_loss", "path": row["result_image"],
            "expected_sha256": row["expected_result_sha256"], "original_result": row["result"],
        }
        for row in evidence if row["result_image_status"] == "verified"
    ]
    candidates.extend({
        "strategy": row["strategy"], "session": row["session"], "battle": row["battle"],
        "cohort": "past_reviewed_unknown_loss", "path": row["verified_review_image"],
        "expected_sha256": row["review_sha256"], "original_result": row["original_result"],
    } for row in reviewed if row["current_sha_status"] == "verified")
    rows = []
    for number, row in enumerate(candidates, 1):
        result = dict(row)
        try:
            path = Path(row["path"])
            if not path.is_relative_to(ROOT):
                raise ValueError("Outside current task root")
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            result["actual_sha256"] = actual
            if actual != row["expected_sha256"]:
                raise ValueError("SHA-256 changed since evidence audit")
            frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if frame is None:
                raise ValueError("OpenCV image decode failed")
            result["width"] = frame.shape[1]
            result["height"] = frame.shape[0]
            result["classify_state"] = vision.classify(frame)[0]
            result["outcome"] = vision.outcome(frame)
            result["gate"] = "MATCH_RESULT_LOSS" if result["classify_state"] == "result" and result["outcome"] == "失败" else "REVIEW_UNVERIFIED"
            result["error"] = None
        except Exception as exc:
            result.update({"gate": "REVIEW_ERROR", "classify_state": "unknown", "outcome": "未知", "error": str(exc)})
        rows.append(result)
        if number % 100 == 0:
            print(f"Processed {number}/{len(candidates)} result images", flush=True)
    summary = {
        "classifier": "pyclashbot.bot.cn_1v1_loop.ChineseVision; classify(frame) and outcome(frame)",
        "classifier_source_sha256": hashlib.sha256((ROOT / "py-clash-bot/pyclashbot/bot/cn_1v1_loop.py").read_bytes()).hexdigest(),
        "control_scope": "Offline image loading only; no loop or emulator instance, no UI or device action",
        "cohorts": {
            cohort: {
                "images": sum(row["cohort"] == cohort for row in rows),
                "gates": dict(Counter(row["gate"] for row in rows if row["cohort"] == cohort)),
                "classifications": dict(Counter(row["classify_state"] for row in rows if row["cohort"] == cohort)),
                "outcomes": dict(Counter(row["outcome"] for row in rows if row["cohort"] == cohort)),
            } for cohort in {row["cohort"] for row in rows}
        },
        "review_required": [row for row in rows if row["gate"] != "MATCH_RESULT_LOSS"],
        "limitations": [
            "Uses current production detector on historical frames; a mismatch means review is needed, not proof the original outcome was different.",
            "Classifier verification and SHA provenance are independent of tactical attribution or win-rate improvement.",
            "Original traces, database results and retained PNGs were not modified.",
        ],
    }
    (OUT / "historical-result-reclassification.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with (OUT / "historical-result-reclassification.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    (OUT / "historical-result-reclassification-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
