"""Replay only verified saved result frames through local offline vision."""

import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import cv2

ROOT = Path(r"D:\codex\CodexWork\clash")
OUT = ROOT / "work/loss-optimization-20261004/agent-evidence"
sys.path.insert(0, str(ROOT / "py-clash-bot"))
from pyclashbot.bot.cn_1v1_loop import ChineseVision  # noqa: E402

vision = ChineseVision()
records = []
with (OUT / "all-random-losses.csv").open(encoding="utf-8-sig") as stream:
    for loss in csv.DictReader(stream):
        if loss["result_evidence_status"] != "hash_matches":
            continue
        path = Path(loss["result_evidence_path"])
        raw = path.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if actual != loss["result_sha256"]:
            raise RuntimeError(f"Evidence changed during review: {path}")
        frame = cv2.imread(str(path))
        record = {"session": loss["session"], "battle": int(loss["battle"]), "source_line": int(loss["source_result_line"]),
                  "expected": loss["outcome"], "path": str(path), "sha256": actual}
        if frame is None:
            record.update(classification="decode_failed", observed_outcome="未知")
        else:
            record.update(classification=vision.classify(frame)[0], observed_outcome=vision.outcome(frame))
        records.append(record)

summary = {
    "checked": len(records),
    "classifications": Counter(r["classification"] for r in records),
    "observed_outcomes": Counter(r["observed_outcome"] for r in records),
    "mismatches": [r for r in records if r["classification"] != "result" or r["observed_outcome"] != r["expected"]],
    "method": "Offline ChineseVision using current project assets; only exact SHA256-matched saved images.",
}
(OUT / "result-vision-replay.json").write_text(json.dumps({"summary": summary, "records": records}, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=2))
