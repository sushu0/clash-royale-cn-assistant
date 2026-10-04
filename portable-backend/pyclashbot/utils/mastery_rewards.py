# ruff: noqa: RUF001
# Native Chinese punctuation and multiplication glyphs are intentional UI/OCR text.
"""Confirmed mastery receipts, independent of claim-button clicks and animation frames."""

import hashlib
import json
import re
import unicodedata
from pathlib import Path

import cv2
import numpy as np

from pyclashbot.utils.cn_footer_ocr import read_local_ocr
from pyclashbot.utils.persistence import append_jsonl_once, atomic_write_bytes


def parse_reward_quantity(text):
    normalized = "".join(text.split()).replace(",", "")
    normalized = "".join(char for char in unicodedata.normalize("NFKD", normalized) if not unicodedata.combining(char))
    normalized = normalized.replace("*", "x")
    if normalized and normalized[0] not in "xX×" and not normalized.isdecimal():
        return None  # Never interpret a misread multiplication prefix as another digit.
    normalized = normalized.translate(str.maketrans({"i": "1", "I": "1", "l": "1", "o": "0", "O": "0"}))
    match = re.fullmatch(r"[xX×]?(\d{1,9})", normalized)
    if not match:
        return None
    amount = int(match.group(1))
    return amount if 0 < amount <= 100_000_000 else None


def read_reward_quantity(image, destination):
    padded = cv2.copyMakeBorder(image, 8, 8, 8, 8, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    result = read_local_ocr(padded, destination, scale=4, language="en-US")
    amount = parse_reward_quantity(result.get("text", ""))
    if amount is not None:
        return amount, result.get("text", ""), "quantity_crop"
    # White glyphs are stable; the animated coin-bag glare can merge x and 1.
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    white = cv2.inRange(hsv, np.array((0, 0, 245)), np.array((179, 85, 255)))
    clean = cv2.copyMakeBorder(255 - white, 8, 8, 8, 8, cv2.BORDER_CONSTANT, value=255)
    result = read_local_ocr(clean, destination, scale=4, language="en-US")
    amount = parse_reward_quantity(result.get("text", ""))
    if amount is not None:
        return amount, result.get("text", ""), "white_quantity_glyphs"
    gray = cv2.copyMakeBorder(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), 8, 8, 8, 8, cv2.BORDER_CONSTANT, value=255)
    result = read_local_ocr(gray, destination, scale=4, language="en-US")
    return parse_reward_quantity(result.get("text", "")), result.get("text", ""), "gray_quantity_glyphs"


def receipt_key(slot, kind, amount):
    return f"{slot}:{kind}:{amount if amount is not None else 'unknown'}"


def distinct_receipts(receipts):
    by_key = {}
    for receipt in receipts:
        key = receipt["id"]
        if key not in by_key or (by_key[key].get("amount") is None and receipt.get("amount") is not None):
            by_key[key] = receipt
    return list(by_key.values())


def confirmed_reward_event(claim_id, receipts, *, session, battle, stamp, policy):
    return {
        "event": "rewards_confirmed",
        "claim_id": claim_id,
        "receipts": distinct_receipts(receipts),
        "session": session,
        "battle": battle,
        "time": stamp,
        "policy": policy,
    }


def append_confirmed_rewards(path: Path, event):
    return append_jsonl_once(path, event, key="claim_id")


def preserve_receipt(frame_bytes, destination: Path):
    digest = hashlib.sha256(frame_bytes).hexdigest()
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / f"{digest}.png"
    if not path.exists():
        atomic_write_bytes(path, frame_bytes)
    return {"path": str(path), "sha256": digest}


def reward_totals(events):
    events = [event for event in events if isinstance(event, dict)]
    claims: dict[str, list[dict]] = {}
    for event in events:
        if (
            event.get("event") == "rewards_confirmed"
            and isinstance(event.get("claim_id"), str)
            and isinstance(event.get("receipts"), list)
        ):
            receipts = [
                row
                for row in event["receipts"]
                if isinstance(row, dict)
                and isinstance(row.get("id"), str)
                and isinstance(row.get("kind"), str)
                and (
                    row.get("amount") is None
                    or (isinstance(row["amount"], int) and not isinstance(row["amount"], bool) and row["amount"] > 0)
                )
            ]
            claims.setdefault(event["claim_id"], distinct_receipts(receipts))
    corrections = {
        (event["claim_id"], event["item_id"]): event["amount"]
        for event in events
        if event.get("event") == "reward_quantity_corrected"
        and isinstance(event.get("claim_id"), str)
        and isinstance(event.get("item_id"), str)
        and isinstance(event.get("amount"), int)
        and not isinstance(event["amount"], bool)
        and event["amount"] > 0
    }
    receipts = []
    for claim_id, values in claims.items():
        for original in values:
            item = dict(original)
            if item.get("amount") is None and (claim_id, item["id"]) in corrections:
                item["amount"] = corrections[(claim_id, item["id"])]
            receipts.append(item)
    return {
        "rewards": len(receipts),
        "coins": sum(item.get("amount") or 0 for item in receipts if item.get("kind") == "coins"),
        "unknown_coin_items": sum(item.get("kind") == "coins" and item.get("amount") is None for item in receipts),
    }


def read_reward_totals(path: Path):
    events = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
    return reward_totals(events)
