# ruff: noqa: RUF001
# Native Chinese punctuation and multiplication glyphs are intentional UI/OCR text.
"""Receipt totals require completion and survive replay without counting animations."""

import json

import pytest

from pyclashbot.utils.battle_history import BattleHistory
from pyclashbot.utils.mastery_rewards import (
    append_confirmed_rewards,
    confirmed_reward_event,
    parse_reward_quantity,
    reward_totals,
)


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("x1000", 1000),
        ("x40öo", 4000),
        ("xiooo", 1000),
        ("x30öo", 3000),
        ("× 2,000", 2000),
        ("3000", 3000),
        ("000", None),
        ("升级", None),
        ("x-1000", None),
        ("ilooö", None),
        ("Xiooö", 1000),
        ("*2000", 2000),
    ],
)
def test_quantity_field_ocr_and_invalid_labels(text, value):
    assert parse_reward_quantity(text) == value


def claim(identifier="claim-a"):
    return confirmed_reward_event(
        identifier,
        [
            {"id": "1:coins:1000", "kind": "coins", "amount": 1000},
            {"id": "1:coins:1000", "kind": "coins", "amount": 1000},
            {"id": "2:coins:1000", "kind": "coins", "amount": 1000},
            {"id": "3:gems:20", "kind": "gems", "amount": 20},
        ],
        session="sample",
        battle=1,
        stamp="2026-09-30 20:00:00",
        policy="random",
    )


def test_totals_count_distinct_items_and_coins_only_after_confirmation():
    event = claim()
    assert reward_totals([{"event": "reward_observed", "amount": 99999}]) == {
        "rewards": 0,
        "coins": 0,
        "unknown_coin_items": 0,
    }
    assert reward_totals([event, event]) == {"rewards": 3, "coins": 2000, "unknown_coin_items": 0}


def test_ledger_replay_is_idempotent(tmp_path):
    ledger = tmp_path / "rewards.jsonl"
    assert append_confirmed_rewards(ledger, claim())
    assert not append_confirmed_rewards(ledger, claim())
    assert len(ledger.read_text().splitlines()) == 1


def test_history_indexes_reward_items_without_inventing_battles(tmp_path):
    ledger = tmp_path / "rewards.jsonl"
    append_confirmed_rewards(ledger, claim())
    history = BattleHistory(tmp_path / "history.sqlite3")
    try:
        history.ingest(ledger, "rewards")
        history.ingest(ledger, "rewards")
        assert history.reward_snapshot() == {"rewards": 3, "coins": 2000, "unknown_coin_items": 0}
        assert history.snapshot("all")["total"]["total"] == 0
    finally:
        history.close()


def test_unknown_coin_quantity_is_explicit(tmp_path):
    ledger = tmp_path / "rewards.jsonl"
    event = confirmed_reward_event(
        "unknown-amount",
        [{"id": "1:coins", "kind": "coins", "amount": None}],
        session="sample",
        battle=1,
        stamp="2026-09-30",
        policy="random",
    )
    ledger.write_text(json.dumps(event) + "\n")
    history = BattleHistory(tmp_path / "history.sqlite3")
    try:
        history.ingest(ledger, "rewards")
        assert history.reward_snapshot() == {"rewards": 1, "coins": 0, "unknown_coin_items": 1}
    finally:
        history.close()


def test_quantity_correction_adds_coins_without_another_reward(tmp_path):
    event = confirmed_reward_event(
        "corrected",
        [{"id": "1:coins:unknown", "kind": "coins", "amount": None}],
        session="sample",
        battle=1,
        stamp="2026-09-30",
        policy="random",
    )
    correction = {
        "event": "reward_quantity_corrected",
        "claim_id": "corrected",
        "item_id": "1:coins:unknown",
        "amount": 1000,
    }
    assert reward_totals([event, correction, correction]) == {"rewards": 1, "coins": 1000, "unknown_coin_items": 0}
    ledger = tmp_path / "rewards.jsonl"
    ledger.write_text(json.dumps(event) + "\n" + json.dumps(correction) + "\n")
    history = BattleHistory(tmp_path / "history.sqlite3")
    try:
        history.ingest(ledger, "rewards")
        assert history.reward_snapshot() == {"rewards": 1, "coins": 1000, "unknown_coin_items": 0}
    finally:
        history.close()
