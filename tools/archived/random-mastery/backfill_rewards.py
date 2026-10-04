"""Backfill only verified, completed receipts; retain original logs unchanged."""
import hashlib
import json
from pathlib import Path

from pyclashbot.utils.mastery_rewards import append_confirmed_rewards, confirmed_reward_event, preserve_receipt, read_reward_totals

ROOT = Path(r"D:\codex\CodexWork\clash")
observations = json.loads((ROOT / "work/random-mastery/reward-history-observations.json").read_text(encoding="utf-8"))
amounts = {row["battle"]: row["amount"] for row in json.loads((ROOT / "work/random-mastery/reward-history-quantities.json").read_text(encoding="utf-8"))}
ledger = ROOT / "outputs/cn-mastery-rewards.jsonl"
existing = {json.loads(line)["claim_id"] for line in ledger.read_text(encoding="utf-8").splitlines()} if ledger.exists() else set()
for row in observations:
    if not row["verified"] or not amounts.get(row["battle"]):
        continue
    confirmation = row["confirmation"]
    claim_id = hashlib.sha256(f"legacy:{confirmation['session']}:{confirmation['battle']}:{confirmation['time']}".encode()).hexdigest()
    if claim_id in existing:
        continue
    source = row["receipt"]["evidence"]
    path = Path(source["path"]).resolve()
    if not path.is_relative_to(ROOT / "work"):
        raise RuntimeError("Receipt outside task work")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != source["sha256"]:
        raise RuntimeError("Receipt image was overwritten; refusing backfill")
    evidence = preserve_receipt(data, ROOT / "work/random-mastery/reward-receipts")
    receipt = {"id": "1:coins", "kind": "coins", "amount": amounts[row["battle"]], "evidence": evidence,
               "source_time": row["receipt"]["time"], "method": "verified_image_and_quantity_crop_ocr"}
    event = confirmed_reward_event(claim_id, [receipt], session=confirmation["session"], battle=row["battle"],
                                   stamp=confirmation["time"], policy=confirmation["policy"])
    append_confirmed_rewards(ledger, event)
print(json.dumps(read_reward_totals(ledger)))
