"""Malformed nested events are isolated and version lineage stays inspectable."""

import json

import pytest

from pyclashbot.utils.battle_history import BattleHistory


def result(session="20261004-000001", battle=1, **values):
    return {
        "event": "battle_finished",
        "session": session,
        "battle": battle,
        "finished_battle": battle,
        "policy": "same-wrapper",
        "mode": "classic_1v1",
        "time": f"2026-10-04 00:00:{battle:02d}",
        "outcome": "胜利",
        "cards_confirmed": 3,
        "card_attempts": 4,
        **values,
    }


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(json.dumps(row, ensure_ascii=False).encode("utf-8") + b"\n" for row in rows))


@pytest.fixture
def history(tmp_path):
    store = BattleHistory(tmp_path / "history.sqlite3")
    yield store
    store.close()


@pytest.mark.parametrize(
    "bad",
    [
        {"event": "play", "policy_observation": []},
        {"event": "play", "policy_observation": "bad"},
        {"event": "battle_finished", "evidence": []},
        {"event": "battle_finished", "evidence": {"path": []}},
        {"event": "battle_finished", "evidence": {"sha256": {"bad": True}}},
        {"event": "battle_finished", "experiment": {"strategy_hash": []}},
        {"event": "battle_finished", "experiment": "bad"},
    ],
)
def test_bad_nested_fields_are_quarantined_and_following_result_is_indexed(history, tmp_path, bad):
    source = tmp_path / "outputs" / "random.jsonl"
    malformed = {**result(battle=2), **bad}
    write(source, [malformed, result()])
    history.ingest(source, "random")
    first = history.snapshot("random")
    assert first["malformed_lines"] == 1 and first["total"]["total"] == 1
    with source.open("ab") as stream:
        stream.write(json.dumps(result(battle=3)).encode("utf-8") + b"\n")
    history.ingest(source, "random")
    assert history.snapshot("random")["total"]["total"] == 2


@pytest.mark.parametrize(
    "receipts",
    [
        None,
        "bad",
        {},
        [None],
        ["bad"],
        [{"id": "r1", "kind": {"bad": True}, "amount": 1}],
        [{"id": "r1", "kind": ["coins"], "amount": 1}],
        [{"id": "r1", "kind": "coins", "amount": False}],
        [{"id": "r1", "kind": "coins", "amount": 1, "evidence": {"path": []}}],
    ],
)
def test_nested_reward_errors_never_freeze_ingestion(history, tmp_path, receipts):
    source = tmp_path / "outputs" / "rewards.jsonl"
    bad = {"event": "rewards_confirmed", "claim_id": "bad", "receipts": receipts}
    good = {
        "event": "rewards_confirmed",
        "claim_id": "good",
        "receipts": [{"id": "r2", "kind": "coins", "amount": 10, "evidence": {"path": "saved.png"}}],
    }
    write(source, [bad, good])
    history.ingest(source, "rewards")
    assert history.reward_snapshot()["rewards"] == 1
    assert history.reward_snapshot()["coins"] == 10
    assert history.snapshot("rewards")["malformed_lines"] >= 1


@pytest.mark.parametrize("event", ["play", "play_evidence", "action", "deployment_checked"])
def test_action_boolean_confirmation_is_valid_while_result_counts_are_integers(history, tmp_path, event):
    source = tmp_path / "outputs" / "random.jsonl"
    write(
        source,
        [
            {
                "event": event,
                "session": "20261004-000001",
                "time": "2026-10-04 00:00:00",
                "confirmed": True,
                "decision": {"card": "knight"},
            },
            result(),
        ],
    )
    history.ingest(source, "random")
    snapshot = history.snapshot("random")
    assert snapshot["malformed_lines"] == 0 and snapshot["total"]["total"] == 1
    write(source, [result(cards_confirmed=True)])
    history.ingest(source, "random")
    assert history.snapshot("random")["malformed_lines"] == 1


def test_same_wrapper_with_two_old_manifest_strategy_hashes_stays_two_versions(history, tmp_path):
    source = tmp_path / "outputs" / "random.jsonl"
    sessions = ("20261003-230001", "20261003-230002")
    for session, digest in zip(sessions, ("a" * 64, "b" * 64), strict=True):
        manifest = tmp_path / "work" / "random-mastery" / session / "manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps(
                {
                    "policy": "same-wrapper",
                    "sha256": {
                        "D:/old/location/pyclashbot/bot/random_deck_strategy.py": digest,
                        "D:/old/location/pyclashbot/detection/card.png": "c" * 64,
                    },
                }
            ),
            encoding="utf-8",
        )
    write(source, [result(session=session) for session in sessions])
    history.ingest(source, "random")
    snapshot = history.snapshot("random")
    assert snapshot["total"]["total"] == 2
    assert len(snapshot["versions"]) == 2
    assert {v["strategy_hash"] for v in snapshot["versions"]} == {"a" * 64, "b" * 64}
    assert all(v["total"] == 1 for v in snapshot["versions"])


def test_explicit_experiment_beats_manifests_and_does_not_merge_different_assets(history, tmp_path):
    source = tmp_path / "outputs" / "random.jsonl"
    base = {"rule_version": "rules-1", "strategy_hash": "a" * 64, "environment_hash": "b" * 64}
    write(
        source,
        [
            result(experiment={**base, "asset_hash": "c" * 64}),
            result(battle=2, experiment={**base, "asset_hash": "d" * 64}),
        ],
    )
    history.ingest(source, "random")
    versions = history.snapshot("random")["versions"]
    assert len(versions) == 2
    assert {v["asset_hash"] for v in versions} == {"c" * 64, "d" * 64}


def test_conflicting_lineage_for_same_game_is_not_silently_assigned_to_first_version(history, tmp_path):
    source = tmp_path / "outputs" / "random.jsonl"
    base = {"rule_version": "rules-1", "asset_hash": "c" * 64, "environment_hash": "d" * 64}
    write(
        source,
        [
            result(experiment={**base, "strategy_hash": "a" * 64}),
            result(experiment={**base, "strategy_hash": "b" * 64}),
        ],
    )
    history.ingest(source, "random")
    snapshot = history.snapshot("random")
    assert snapshot["total"]["total"] == 1
    assert snapshot["conflicts"] == 1
    assert snapshot["total"]["unknown"] == 1


def test_partial_utf8_result_waits_for_completion_and_replays_without_duplicate(history, tmp_path):
    source = tmp_path / "random.jsonl"
    encoded = json.dumps(result(), ensure_ascii=False).encode("utf-8") + b"\n"
    cut = encoded.index("胜利".encode()) + 1
    source.write_bytes(encoded[:cut])
    history.ingest(source, "random")
    assert history.snapshot("random")["total"]["total"] == 0
    assert history.snapshot("random")["malformed_lines"] == 0
    with source.open("ab") as stream:
        stream.write(encoded[cut:])
    history.ingest(source, "random")
    history.ingest(source, "random")
    assert history.snapshot("random")["total"]["wins"] == 1
    assert history.snapshot("random")["malformed_lines"] == 0
