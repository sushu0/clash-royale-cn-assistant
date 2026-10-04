"""Statistics survive restart, partial writes and replay without fabricating wins."""

import json

import pytest

from pyclashbot.utils.battle_history import BattleHistory, summarize


def event(battle=1, result="胜利", session="s1", **kwargs):
    return dict(
        event="battle_end",
        session=session,
        battle=battle,
        result=result,
        time=f"2026-09-29 01:00:{battle:02}",
        policy_version="v4",
        mode="classic_1v1",
        confirmed=3,
        attempts=4,
        **kwargs,
    )


def write(path, rows):
    path.write_bytes(b"".join(json.dumps(row, ensure_ascii=False).encode() + b"\n" for row in rows))


@pytest.fixture
def history(tmp_path):
    store = BattleHistory(tmp_path / "history.sqlite3")
    yield store
    store.close()


def test_empty_rate_is_unknown_not_zero(history, tmp_path):
    assert not history.ingest(tmp_path / "missing.jsonl", "567")
    assert history.snapshot()["total"]["win_rate"] is None


def test_random_results_use_finished_id_and_do_not_mix_fixed_deck_history(history, tmp_path):
    random_source = tmp_path / "random.jsonl"
    random_row = {
        "event": "battle_finished",
        "session": "random-a",
        "battle": 2,
        "finished_battle": 1,
        "time": "2026-09-30 18:00:09",
        "policy": "random-mastery-claim-all-v6-20260930",
        "outcome": "失败",
        "cards_confirmed": 12,
        "card_attempts": 13,
        "evidence": {"path": "result.png"},
    }
    write(
        random_source,
        [{**random_row, "event": "battle_started"}, random_row, random_row, {**random_row, "event": "cycle_complete"}],
    )
    history.ingest(random_source, "random")
    fixed_source = tmp_path / "fixed.jsonl"
    write(fixed_source, [event()])
    history.ingest(fixed_source, "567")
    snapshot = history.snapshot("random")
    assert snapshot["total"]["total"] == snapshot["total"]["losses"] == 1
    assert snapshot["records"][0]["battle"] == 1
    assert snapshot["records"][0]["confirmed"] == 12
    assert snapshot["records"][0]["attempts"] == 13
    assert snapshot["records"][0]["policy"] == random_row["policy"]
    assert snapshot["records"][0]["mode"] == "classic_1v1"
    assert history.snapshot("567")["total"]["wins"] == 1
    assert history.snapshot("all")["total"]["total"] == 2


def test_unknown_and_draw_remain_in_denominator_and_replays_do_not_duplicate(history, tmp_path):
    source = tmp_path / "trace.jsonl"
    rows = [event(), event(2, "失败"), event(3, "未知"), event(4, "平局")]
    write(source, rows + rows)
    history.ingest(source, "567")
    history.ingest(source, "567")
    result = history.snapshot()["total"]
    assert result["total"] == 4 and result["win_rate"] == 0.25
    assert result["unknown"] == result["draws"] == result["losses"] == result["wins"] == 1


def test_restart_and_same_battle_number_in_new_session(tmp_path):
    source, db = tmp_path / "trace.jsonl", tmp_path / "history.sqlite3"
    write(source, [event()])
    store = BattleHistory(db)
    store.ingest(source, "567")
    store.close()
    write(source, [event(), event(session="s2")])
    store = BattleHistory(db)
    try:
        store.ingest(source, "567")
        assert store.snapshot()["total"]["total"] == 2
        assert store.snapshot()["session"]["total"] == 1
    finally:
        store.close()


def test_legacy_results_use_timestamp_identity_without_inventing_policy(history, tmp_path):
    source = tmp_path / "legacy.jsonl"
    row = event()
    row.pop("session")
    row.pop("policy_version")
    other = {**row, "time": "2026-09-25 12:00:00", "result": "未知"}
    write(source, [row, row, other])
    history.ingest(source, "hog")
    snapshot = history.snapshot("hog")
    assert snapshot["total"]["total"] == 2
    assert snapshot["total"]["unknown"] == 1
    assert snapshot["versions"][0]["policy"] == "未记录版本"
    assert snapshot["malformed_lines"] == 0


def test_incomplete_utf8_line_is_retried_then_counts_once(history, tmp_path):
    source = tmp_path / "trace.jsonl"
    data = json.dumps(event(), ensure_ascii=False).encode() + b"\n"
    position = data.index("胜利".encode()) + 1
    source.write_bytes(data[:position])
    history.ingest(source, "567")
    assert history.snapshot()["total"]["total"] == 0
    with source.open("ab") as stream:
        stream.write(data[position:])
    history.ingest(source, "567")
    assert history.snapshot()["total"]["wins"] == 1
    assert history.snapshot()["malformed_lines"] == 0


def test_truncation_and_rotation_preserve_old_games_and_ingest_new(history, tmp_path):
    source = tmp_path / "trace.jsonl"
    write(source, [event(), event(2)])
    history.ingest(source, "567")
    write(source, [event(session="s2")])
    history.ingest(source, "567")
    rotated = tmp_path / "replacement.jsonl"
    write(rotated, [event(session="s3")])
    rotated.replace(source)
    history.ingest(source, "567")
    assert history.snapshot()["total"]["total"] == 4


def test_bad_complete_lines_are_reported_but_not_counted(history, tmp_path):
    source = tmp_path / "trace.jsonl"
    source.write_bytes(b"{invalid}\nnull\n" + json.dumps(event()).encode() + b"\n")
    history.ingest(source, "567")
    assert history.snapshot()["malformed_lines"] == 2
    assert history.snapshot()["total"]["total"] == 1


def test_conflicting_results_are_unknown_not_extra_games(history, tmp_path):
    source = tmp_path / "trace.jsonl"
    write(source, [event(), event(result="失败")])
    history.ingest(source, "567")
    snapshot = history.snapshot()
    assert snapshot["conflicts"] == 1
    assert snapshot["total"]["total"] == snapshot["total"]["unknown"] == 1
    assert snapshot["total"]["wins"] == 0


def test_scope_and_version_are_separate_and_in_progress_session_starts_at_zero(history, tmp_path):
    source = tmp_path / "trace.jsonl"
    rows = [event()]
    rows.append({**event(2, "失败"), "policy_version": "v3"})
    write(source, rows)
    history.ingest(source, "567")
    other = tmp_path / "hog.jsonl"
    write(other, [event(), {**event(session="s2"), "event": "battle_start", "time": "2026-09-29 02:00:00"}])
    history.ingest(other, "hog")
    assert history.snapshot("all")["total"]["total"] == 3
    assert history.snapshot("hog")["session"]["total"] == 0
    assert len(history.snapshot("567")["versions"]) == 2


def test_recent_twenty_are_chronological_and_unknown_breaks_streak(history, tmp_path):
    source = tmp_path / "trace.jsonl"
    write(source, [event(i, "失败" if i <= 5 else "胜利") for i in range(1, 26)])
    while history.ingest(source, "567", max_bytes=100):
        pass
    snapshot = history.snapshot()
    assert snapshot["recent"]["wins"] == snapshot["recent"]["total"] == 20
    assert snapshot["total"]["best_win_streak"] == snapshot["total"]["streak"] == 20
    assert snapshot["records"][0]["battle"] == 25
    assert summarize([{"result": r} for r in ["胜利", "胜利", "未知", "失败"]])["streak"] == 1


@pytest.mark.parametrize("battle", [0, -1, True, "1", None])
def test_invalid_battle_ids_are_never_counted(history, tmp_path, battle):
    source = tmp_path / "trace.jsonl"
    write(source, [{**event(), "battle": battle}])
    history.ingest(source, "567")
    assert history.snapshot()["total"]["total"] == 0
