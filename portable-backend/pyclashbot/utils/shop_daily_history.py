"""Receipt-backed, restart-safe daily shop totals, independent of battle ownership.

The six daily offer slots are the deduplication boundary. Run-level counters are
never treated as receipts, and observing a repeated zero-purchase run cannot
erase a previously confirmed transaction.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import time
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from pyclashbot.utils.persistence import atomic_write_json, read_validated_json
from pyclashbot.utils.process_ownership import ExclusiveFileLock, OwnershipError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

# China has no daylight-saving transitions. A fixed offset also works in frozen
# Windows packages without depending on an external zoneinfo/tzdata database.
SHANGHAI = timezone(timedelta(hours=8), "Asia/Shanghai")
RECEIPTS = frozenset({"recognized_reward", "purchased_marker", "verified_gold_decrease"})
RUN_DIRECTORY = re.compile(r"^(\d{8})-\d{6}(?:-\d+)?$")
SHA256 = re.compile(r"^[a-fA-F0-9]{64}$")


class ShopDailyHistoryConflictError(ValueError):
    """The same day and slot has incompatible confirmed offer identities."""


def _positive_integer(value) -> bool:
    return type(value) is int and value > 0


def _day(value: str | date | datetime) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=SHANGHAI)
        return value.astimezone(SHANGHAI).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(value).isoformat()


def _timestamp_day(value: str) -> str:
    return _day(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _run_day(path: str | Path) -> str | None:
    # Accept serialized Windows paths even when offline tests run on POSIX.
    for component in reversed(re.split(r"[\\/]", str(path))):
        match = RUN_DIRECTORY.fullmatch(component)
        if match is not None:
            return datetime.strptime(match[1], "%Y%m%d").date().isoformat()
    return None


def _valid_history(value) -> bool:
    if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("days"), dict):
        return False
    for day, rows in value["days"].items():
        try:
            if _day(day) != day:
                return False
        except (ValueError, TypeError):
            return False
        if not isinstance(rows, dict):
            return False
        for slot, row in rows.items():
            if slot not in {str(index) for index in range(6)} or not isinstance(row, dict):
                return False
            if row.get("slot") != int(slot) or type(row.get("slot")) is not int:
                return False
            if row.get("currency") == "free":
                if row.get("state") != "claimed" or row.get("price") != 0:
                    return False
            elif row.get("currency") in {"gold", "gems"}:
                expected = "purchased" if row["currency"] == "gold" else "skipped_gems"
                if row.get("state") != expected or not _positive_integer(row.get("price")):
                    return False
            else:
                return False
            if not isinstance(row.get("sources"), list) or not row["sources"]:
                return False
    return True


class ShopDailyHistoryStore:
    """Read and merge confirmed receipts under a separate short-lived file lock."""

    def __init__(self, data_root: str | Path, clock: Callable[[], datetime] | None = None):
        self.data_root = Path(data_root).resolve()
        self.path = self.data_root / "outputs" / "shop-daily" / "history.json"
        self.lock_path = self.data_root / "work" / "shop-daily-history.lock"
        self.clock = clock or (lambda: datetime.now(UTC))

    @contextmanager
    def _locked(self) -> Iterator[None]:
        # Another UI/backend instance may be briefly committing the same ledger.
        # This lock never acquires the bot/device ownership file.
        lock = ExclusiveFileLock(self.lock_path)
        deadline = time.monotonic() + 5
        while True:
            try:
                lock.acquire()
                break
            except OwnershipError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.02)
        try:
            yield
        finally:
            lock.release()

    def _read(self) -> dict:
        return read_validated_json(self.path, _valid_history, default={"version": 1, "days": {}})

    def _result_day(self, result: dict) -> str:
        if result.get("date") is not None:
            return _day(result["date"])
        if result.get("evidence_dir"):
            observed = _run_day(result["evidence_dir"])
            if observed is not None:
                return observed
        if result.get("updated_at"):
            return _timestamp_day(result["updated_at"])
        return _day(self.clock())

    @staticmethod
    def _receipt_rows(result: dict, source: dict) -> list[dict]:
        rows = []
        items = result.get("items", [])
        if not isinstance(items, list):
            raise ValueError("Shop result items must be a list")
        for item in items:
            if not isinstance(item, dict):
                continue
            slot, currency, state = item.get("slot"), item.get("currency"), item.get("state")
            if type(slot) is not int or slot not in range(6):
                continue
            evidence = item.get("evidence")
            price = item.get("price")
            verified = isinstance(evidence, str) and evidence in RECEIPTS
            if currency == "free" and state == "claimed" and verified and type(price) is int and price == 0:
                pass
            elif currency == "gold" and state == "purchased" and verified and _positive_integer(price):
                pass
            elif currency == "gems" and state == "skipped_gems" and _positive_integer(price):
                # This is an observed skipped offer, never a purchase receipt.
                evidence = "recognized_gems_offer"
            else:
                continue
            rows.append(
                {
                    "slot": slot,
                    "currency": currency,
                    "price": price,
                    "state": state,
                    "evidence": evidence,
                    "sources": [copy.deepcopy(source)],
                }
            )
        return rows

    @staticmethod
    def _merge(history: dict, day: str, rows: list[dict]) -> bool:
        changed = False
        existing = history["days"].setdefault(day, {})
        for row in rows:
            key = str(row["slot"])
            previous = existing.get(key)
            if previous is None:
                existing[key] = copy.deepcopy(row)
                changed = True
                continue
            if (previous["currency"], previous["price"], previous["state"]) != (
                row["currency"],
                row["price"],
                row["state"],
            ):
                raise ShopDailyHistoryConflictError(f"Conflicting daily shop receipt for {day}, slot {key}")
            for source in row["sources"]:
                if source not in previous["sources"]:
                    previous["sources"].append(copy.deepcopy(source))
                    changed = True
        return changed

    @staticmethod
    def _snapshot(history: dict, day: str) -> dict:
        items = [copy.deepcopy(row) for _slot, row in sorted(history["days"].get(day, {}).items())]
        return {
            "date": day,
            "free_claimed": sum(item["state"] == "claimed" for item in items),
            "gold_purchased": sum(item["state"] == "purchased" for item in items),
            "gems_skipped": sum(item["state"] == "skipped_gems" for item in items),
            "gold_spent": sum(item["price"] for item in items if item["currency"] == "gold"),
            "items": items,
        }

    def _commit(self, day: str, rows: list[dict]) -> dict:
        with self._locked():
            history = self._read()
            if rows and self._merge(history, day, rows):
                atomic_write_json(self.path, history, backup=True, validator=_valid_history)
            return self._snapshot(history, day)

    def observe(self, result: dict) -> dict:
        """Persist only confirmed item rows and return totals for their source day."""
        if not isinstance(result, dict):
            raise ValueError("Shop result must be an object")
        day = self._result_day(result)
        source = {"kind": "run_receipt", "date": day}
        if result.get("evidence_dir"):
            source["evidence_dir"] = str(result["evidence_dir"])
        return self._commit(day, self._receipt_rows(result, source))

    def snapshot(self, day: str | date | datetime | None = None) -> dict:
        """Read one Shanghai day's totals without creating files or taking a lock.

        Writers replace the entire ledger atomically. Read-only bridges can read
        a complete primary/backup snapshot without creating the writer's lock.
        """
        observed_day = _day(self.clock() if day is None else day)
        return self._snapshot(self._read(), observed_day)

    def import_results(self, directory: str | Path | None = None) -> dict:
        """Replay bounded run result files, preserving original files unchanged."""
        directory = Path(directory) if directory is not None else self.path.parent
        report = {"imported": 0, "ignored": 0, "errors": []}
        for path in sorted(directory.glob("*/result.json")):
            try:
                result = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(result, dict):
                    raise ValueError("Shop result must be an object")
                result.setdefault("evidence_dir", str(path.parent))
                source_day = self._result_day(result)
                before = self.snapshot(source_day)
                after = self.observe(result)
                if after != before:
                    report["imported"] += 1
                else:
                    report["ignored"] += 1
            except (OSError, ValueError, TypeError) as error:
                report["errors"].append({"path": str(path), "error": str(error)})
        return report

    def import_verified_acceptance(self, path: str | Path) -> dict:
        """Backfill the verified six-slot calibration report after checking proof.

        This explicitly supports the original report's calibrated layout: free
        slot 0, four ascending gold-price entries in slots 1..4, gem slot 5. Its
        summary is sufficient only when before/after balances and hashed native
        screenshots agree. The original acceptance report remains authoritative.
        """
        path = Path(path).resolve()
        raw = path.read_bytes()
        report = json.loads(raw)
        if not isinstance(report, dict) or report.get("status") != "PASS":
            raise ValueError("Daily shop acceptance must have status PASS")
        if not isinstance(report.get("verified_at"), str):
            raise ValueError("Daily shop acceptance requires a verified timestamp")
        verified = datetime.fromisoformat(report["verified_at"].replace("Z", "+00:00"))
        if verified.tzinfo is None:
            raise ValueError("Daily shop acceptance timestamp must include its timezone")
        day = _day(verified)
        directory_day = re.search(r"(?:^|[-_])(\d{8})$", path.parent.name)
        if directory_day is not None:
            declared = datetime.strptime(directory_day[1], "%Y%m%d").date().isoformat()
            if declared != day:
                raise ValueError("Acceptance report directory date conflicts with verified timestamp")
        acceptance = report.get("today_acceptance")
        if not isinstance(acceptance, dict):
            raise ValueError("Daily shop acceptance is missing purchase details")
        native = report.get("native_images")
        if not isinstance(native, dict) or not {"daily-shop-before.png", "daily-shop-after.png"}.issubset(native):
            raise ValueError("Daily shop acceptance requires before/after image hashes")
        for name, digest in native.items():
            if not isinstance(name, str) or not isinstance(digest, str) or not SHA256.fullmatch(digest):
                raise ValueError("Invalid native image hash")
            image_path = (path.parent / name).resolve()
            if image_path.parent != path.parent or image_path.suffix.lower() != ".png":
                raise ValueError("Native image must be a PNG in the acceptance directory")
            if hashlib.sha256(image_path.read_bytes()).hexdigest() != digest.lower():
                raise ValueError(f"Native image SHA256 mismatch: {name}")
        expected_states = {str(slot): "purchased" for slot in range(5)} | {"5": "gems"}
        prices = acceptance.get("gold_prices")
        if (
            type(acceptance.get("free_offer_claimed")) is not int
            or acceptance["free_offer_claimed"] != 1
            or type(acceptance.get("gold_offers_purchased")) is not int
            or acceptance["gold_offers_purchased"] != 4
            or acceptance.get("slot_states") != expected_states
            or not isinstance(prices, list)
            or len(prices) != 4
            or not all(_positive_integer(price) for price in prices)
            or type(acceptance.get("gold_spent")) is not int
            or sum(prices) != acceptance["gold_spent"]
        ):
            raise ValueError("Acceptance six-slot layout, counts or prices are inconsistent")
        for field in ("gold_before", "gold_after", "free_reward_gold_received", "gems_before", "gems_after"):
            if type(acceptance.get(field)) is not int or acceptance[field] < 0:
                raise ValueError(f"Acceptance requires a valid {field}")
        if (
            acceptance["gold_before"] + acceptance["free_reward_gold_received"] - acceptance["gold_spent"]
            != acceptance["gold_after"]
            or acceptance["gems_before"] != acceptance["gems_after"]
        ):
            raise ValueError("Acceptance balances do not corroborate the purchases")
        source = {
            "kind": "verified_acceptance",
            "path": str(path),
            "verified_at": report["verified_at"],
            "sha256": hashlib.sha256(raw).hexdigest(),
            "native_images": copy.deepcopy(native),
            "basis": "PASS report, native before/after hashes, matching balance arithmetic; calibrated slots 0/free, 1..4/gold_prices, 5/gems",
        }
        rows: list[dict[str, object]] = [
            {
                "slot": 0,
                "currency": "free",
                "price": 0,
                "state": "claimed",
                "evidence": "verified_acceptance",
                "sources": [source],
            }
        ]
        rows.extend(
            {
                "slot": slot,
                "currency": "gold",
                "price": price,
                "state": "purchased",
                "evidence": "verified_acceptance",
                "sources": [source],
            }
            for slot, price in enumerate(prices, start=1)
        )
        repeat = report.get("repeat_button_acceptance")
        if isinstance(repeat, dict):
            if repeat.get("evidence_dir") and _run_day(repeat["evidence_dir"]) not in {None, day}:
                raise ValueError("Acceptance repeat evidence belongs to a different day")
            repeat_items = repeat.get("items", [])
            gem_rows = self._receipt_rows({"items": repeat_items}, source)
            rows.extend(row for row in gem_rows if row["slot"] == 5 and row["currency"] == "gems")
        return self._commit(day, rows)
