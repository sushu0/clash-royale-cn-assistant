"""Daily receipt totals survive reruns, restarts, midnight and verified migration."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from pyclashbot.utils.shop_daily_history import ShopDailyHistoryConflictError, ShopDailyHistoryStore


def receipt(slot=1, price=500, currency="gold", state="purchased", evidence="recognized_reward"):
    return {"slot": slot, "price": price, "currency": currency, "state": state, "evidence": evidence}


def run_result(items, **extra):
    return {"items": items, "date": "2026-10-06", **extra}


@pytest.fixture
def store(tmp_path):
    return ShopDailyHistoryStore(tmp_path, clock=lambda: datetime(2026, 10, 6, 5, tzinfo=UTC))


@pytest.fixture
def acceptance_path(tmp_path):
    folder = tmp_path / "verified-acceptance"
    folder.mkdir()
    hashes = {}
    for name in ("daily-shop-before.png", "daily-shop-after.png"):
        raw = f"stand-in test image: {name}".encode()
        (folder / name).write_bytes(raw)
        hashes[name] = hashlib.sha256(raw).hexdigest()
    report = {
        "status": "PASS",
        "verified_at": "2026-10-06T02:56:17+08:00",
        "today_acceptance": {
            "free_offer_claimed": 1,
            "gold_offers_purchased": 4,
            "gold_prices": [500, 1000, 1500, 2000],
            "gold_spent": 5000,
            "free_reward_gold_received": 1599,
            "gold_before": 70078,
            "gold_after": 66677,
            "gems_before": 3415,
            "gems_after": 3415,
            "slot_states": {str(slot): "purchased" for slot in range(5)} | {"5": "gems"},
        },
        "repeat_button_acceptance": {"items": [receipt(5, 100, "gems", "skipped_gems", None)]},
        "native_images": hashes,
    }
    path = folder / "ACCEPTANCE.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def test_zero_repeat_and_incremental_updates_do_not_overwrite_confirmed_totals(store):
    first = run_result([receipt(), receipt(0, 0, "free", "claimed"), receipt(5, 100, "gems", "skipped_gems")])
    for _index in range(3):
        assert store.observe(first)["gold_spent"] == 500
    assert (
        store.observe(
            run_result(
                [
                    receipt(0, None, "purchased", "already_purchased", None),
                    receipt(1, None, "purchased", "already_purchased", None),
                    receipt(5, 100, "gems", "skipped_gems", None),
                ],
                free_claimed=0,
                gold_purchased=0,
                gold_spent=0,
            )
        )["gold_spent"]
        == 500
    )
    result = store.snapshot()
    assert (result["free_claimed"], result["gold_purchased"], result["gems_skipped"]) == (1, 1, 1)
    assert len(result["items"]) == 3


def test_restart_reads_durable_history_without_recounting(store):
    store.observe(run_result([receipt()]))
    restored = ShopDailyHistoryStore(store.data_root, store.clock)
    assert restored.observe(run_result([receipt()]))["gold_spent"] == 500
    assert restored.snapshot()["gold_purchased"] == 1
    assert store.path.exists()


def test_snapshot_of_absent_data_root_creates_no_files_or_directories(tmp_path):
    root = tmp_path / "absent-runtime"
    ledger = ShopDailyHistoryStore(root, clock=lambda: datetime(2026, 10, 6, 5, tzinfo=UTC))
    assert not root.exists()
    assert ledger.snapshot() == {
        "date": "2026-10-06",
        "free_claimed": 0,
        "gold_purchased": 0,
        "gems_skipped": 0,
        "gold_spent": 0,
        "items": [],
    }
    assert not root.exists()
    assert not ledger.path.exists()
    assert not ledger.lock_path.exists()


def test_shanghai_midnight_resets_display_and_new_slots_can_be_counted(tmp_path):
    current = [datetime(2026, 10, 6, 15, 59, tzinfo=UTC)]
    ledger = ShopDailyHistoryStore(tmp_path, clock=lambda: current[0])
    ledger.observe({"items": [receipt()]})
    current[0] = datetime(2026, 10, 6, 16, 0, tzinfo=UTC)
    assert ledger.snapshot()["date"] == "2026-10-07"
    assert ledger.snapshot()["gold_spent"] == 0
    ledger.observe({"items": [receipt()]})
    assert ledger.snapshot()["gold_spent"] == 500
    assert ledger.snapshot("2026-10-06")["gold_spent"] == 500


def test_datetime_day_is_converted_to_shanghai(store):
    store.observe({"items": [receipt()], "updated_at": "2026-10-05T16:00:00Z"})
    assert store.snapshot(datetime(2026, 10, 5, 16, tzinfo=UTC))["gold_spent"] == 500


def test_old_run_source_directory_preserves_its_day_after_restart(store):
    result = {
        "items": [receipt()],
        "evidence_dir": r"D:\codex\outputs\shop-daily\20261005-235500-123",
        "updated_at": "2026-10-06T12:00:00+08:00",
    }
    assert store.observe(result)["date"] == "2026-10-05"
    assert store.snapshot()["gold_spent"] == 0
    assert store.snapshot("2026-10-05")["gold_spent"] == 500


@pytest.mark.parametrize("run_state", ["cancelled", "partial", "failed", "running", "completed"])
def test_only_confirmed_item_receipts_are_counted_regardless_of_run_state(store, run_state):
    result = store.observe(
        run_result(
            [
                receipt(1),
                receipt(2, 1000, state="cancelled_unverified"),
                receipt(3, 1500, state="awaiting_receipt"),
                receipt(4, 2000, state="unverified_attempt"),
                receipt(0, 0, "free", "opened"),
            ],
            state=run_state,
            free_claimed=99,
            gold_purchased=99,
            gold_spent=100000,
        )
    )
    assert (result["free_claimed"], result["gold_purchased"], result["gold_spent"]) == (0, 1, 500)


@pytest.mark.parametrize("evidence", [None, "", "button_clicked", "unverified_attempt", {"claimed": True}])
def test_success_labels_without_receipt_proof_do_not_count(store, evidence):
    assert store.observe(run_result([receipt(evidence=evidence)]))["gold_spent"] == 0


@pytest.mark.parametrize(
    "bad_item",
    [
        receipt(True),
        receipt(6),
        receipt(-1),
        receipt(price=True),
        receipt(price=0),
        receipt(currency="gems"),
        receipt(0, 500, "free", "claimed"),
        receipt(0, False, "free", "claimed"),
    ],
)
def test_invalid_slot_price_or_currency_cannot_enter_history(store, bad_item):
    assert store.observe(run_result([bad_item]))["items"] == []


def test_slot_conflict_is_rejected_without_partially_committing_new_rows(store):
    store.observe(run_result([receipt()]))
    before = store.path.read_bytes()
    with pytest.raises(ShopDailyHistoryConflictError):
        store.observe(run_result([receipt(2, 1000), receipt(price=800)]))
    assert store.path.read_bytes() == before
    assert store.snapshot()["gold_spent"] == 500
    with pytest.raises(ShopDailyHistoryConflictError):
        store.observe(run_result([receipt(1, 100, "gems", "skipped_gems")]))


def test_verified_acceptance_backfills_missing_calibration_and_merges_slots(store, acceptance_path):
    store.observe(run_result([receipt(2, 1000), receipt(3, 1500), receipt(4, 2000)]))
    report_before = acceptance_path.read_bytes()
    for _index in range(2):
        imported = store.import_verified_acceptance(acceptance_path)
        assert (
            imported["free_claimed"],
            imported["gold_purchased"],
            imported["gold_spent"],
            imported["gems_skipped"],
        ) == (1, 4, 5000, 1)
    assert acceptance_path.read_bytes() == report_before
    assert imported["items"][0]["sources"][0]["kind"] == "verified_acceptance"
    restored = ShopDailyHistoryStore(store.data_root, store.clock)
    assert restored.snapshot() == imported


@pytest.mark.parametrize(
    "mutation",
    [
        "status",
        "counts",
        "price",
        "balance",
        "gem_balance",
        "slot_states",
        "timestamp",
        "missing_proof",
        "escape_image",
        "wrong_hash",
    ],
)
def test_verified_acceptance_rejects_invalid_or_inconsistent_proof(store, acceptance_path, mutation):
    report = json.loads(acceptance_path.read_text(encoding="utf-8"))
    details = report["today_acceptance"]
    if mutation == "status":
        report["status"] = "REVIEW"
    elif mutation == "counts":
        details["gold_offers_purchased"] = 3
    elif mutation == "price":
        details["gold_prices"][0] = 800
    elif mutation == "balance":
        details["gold_after"] += 1
    elif mutation == "gem_balance":
        details["gems_after"] -= 100
    elif mutation == "slot_states":
        details["slot_states"]["4"] = "unknown"
    elif mutation == "timestamp":
        report["verified_at"] = "2026-10-06T02:56:17"
    elif mutation == "missing_proof":
        report.pop("native_images")
    elif mutation == "escape_image":
        report["native_images"]["../outside.png"] = "a" * 64
    elif mutation == "wrong_hash":
        report["native_images"]["daily-shop-before.png"] = "a" * 64
    acceptance_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises((ValueError, OSError)):
        store.import_verified_acceptance(acceptance_path)
    assert store.snapshot()["items"] == []


def test_verified_acceptance_corrupted_native_image_rejected(store, acceptance_path):
    (acceptance_path.parent / "daily-shop-after.png").write_bytes(b"changed proof")
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        store.import_verified_acceptance(acceptance_path)
    assert store.snapshot()["gold_spent"] == 0


def test_existing_run_results_can_be_replayed_without_overwriting_zero_run(store):
    for name, items in [
        ("20261006-022049-324475", [receipt(2, 1000), receipt(3, 1500)]),
        ("20261006-024622-116654", [receipt(4, 2000), receipt(5, 100, "gems", "skipped_gems")]),
        ("20261006-025028-512915", [receipt(0, None, "purchased", "already_purchased", None)]),
    ]:
        path = store.path.parent / name / "result.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"items": items, "gold_spent": 0}), encoding="utf-8")
    report = store.import_results()
    assert report == {"imported": 2, "ignored": 1, "errors": []}
    assert store.snapshot()["gold_spent"] == 4500
    assert store.import_results() == {"imported": 0, "ignored": 3, "errors": []}


def test_invalid_history_is_preserved_and_valid_backup_recovers(store):
    store.observe(run_result([receipt()]))
    store.observe(run_result([receipt(2, 1000)]))
    store.path.write_text("broken", encoding="utf-8")
    assert store.snapshot()["gold_spent"] == 500
    assert store.path.read_text() == "broken"


def test_two_store_instances_merge_under_their_own_file_lock(store):
    other = ShopDailyHistoryStore(store.data_root, store.clock)
    with ThreadPoolExecutor(max_workers=2) as executor:
        pending = [
            executor.submit(store.observe, run_result([receipt()])),
            executor.submit(other.observe, run_result([receipt(2, 1000)])),
        ]
        for future in pending:
            future.result()
    assert store.snapshot()["gold_spent"] == 1500
    assert store.lock_path.name == "shop-daily-history.lock"
    assert not (store.data_root / "work" / "cn-runner.lock").exists()
