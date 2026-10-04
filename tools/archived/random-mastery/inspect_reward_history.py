"""Read only hash-verified receipt images from completed claim-all episodes."""
import hashlib
import json
from pathlib import Path

import cv2

from pyclashbot.utils.cn_footer_ocr import read_local_ocr

ROOT = Path(r"D:\codex\CodexWork\clash")
rows = [json.loads(line) for line in (ROOT / "outputs/cn-random-mastery.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
reports = []
for confirmation in [r for r in rows if r["event"] == "claim_all_confirmed"]:
    candidates = [r for r in rows if r["event"] == "claim_reward_reveal" and r["battle"] == confirmation["battle"] and r["time"] <= confirmation["time"]]
    valid = []
    for candidate in candidates:
        evidence = candidate["evidence"]
        path = Path(evidence["path"]).resolve()
        if (path.is_relative_to(ROOT / "work") and path.is_file()
                and hashlib.sha256(path.read_bytes()).hexdigest() == evidence["sha256"]):
            valid.append(candidate)
    if not valid:
        reports.append({"battle": confirmation["battle"], "verified": False})
        continue
    chosen = valid[-1]
    image = cv2.imread(chosen["evidence"]["path"])
    data = read_local_ocr(image, ROOT / f"work/random-mastery/history-ocr-{confirmation['battle']}.png")
    reports.append({"battle": confirmation["battle"], "confirmation": confirmation,
                    "receipt": chosen, "ocr": data, "verified": True})
target = ROOT / "work/random-mastery/reward-history-observations.json"
target.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps([{ "battle":r["battle"],"verified":r["verified"],"text":r.get("ocr",{}).get("text")} for r in reports], ensure_ascii=False))
