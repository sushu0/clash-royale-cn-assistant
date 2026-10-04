# ruff: noqa: RUF001
# Native Chinese punctuation and multiplication glyphs are intentional UI/OCR text.
"""Live Chinese UI regressions: modal darkness, changed cards, no false claims."""

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from pyclashbot.bot.cn_random_mastery_loop import RandomMasteryLoop
from pyclashbot.bot.coords import CN_RANDOM_MASTERY, CN_RANDOM_MODAL_CLOSE, CN_RANDOM_REWARD_CONTINUE
from pyclashbot.detection.cn_random_ui import (
    changed_deck_slots,
    deck_portraits,
    mastery_card_points,
    mastery_claim_points,
    mastery_footer_state,
    mastery_footer_text_state,
    random_ui_is,
)

FIXTURES = Path(__file__).with_name("fixtures") / "cn_random_mastery"


def frame(name):
    return cv2.imread(str(FIXTURES / f"{name}.png"))


@pytest.mark.parametrize(
    "name", ["deck", "deck_menu", "deck_confirm", "mastery_list", "mastery_detail", "mastery_locked"]
)
def test_known_pages_and_dimmed_modal_background(name):
    source = frame(name)
    assert random_ui_is(source, name)
    assert not random_ui_is((source * 0.35).astype(np.uint8), name)
    assert not random_ui_is(np.zeros_like(source), name)
    assert not random_ui_is(source[:600], name)


@pytest.mark.parametrize("name", ["deck_menu", "deck_confirm", "mastery_list", "mastery_detail", "mastery_locked"])
def test_overlay_cannot_be_mistaken_for_deck(name):
    assert not random_ui_is(frame(name), "deck")


@pytest.mark.parametrize(
    "name", ["deck", "deck_menu", "deck_confirm", "mastery_list", "mastery_detail", "mastery_locked"]
)
def test_incomplete_tasks_and_other_pages_have_no_claim_control(name):
    assert mastery_claim_points(frame(name)) == []


def test_game_generated_deck_actually_changed():
    before = deck_portraits(frame("previous_deck"))
    after = deck_portraits(frame("deck"))
    assert changed_deck_slots(before, before) == 0
    assert changed_deck_slots(before, after) >= 6


def test_mastery_has_three_full_rows_and_four_columns():
    points = mastery_card_points(frame("mastery_list"))
    assert len(points) == 12
    assert len({x for x, _ in points}) == 4
    assert len({y for _, y in points}) == 3


def test_mastery_last_row_does_not_click_blank_cells():
    points = mastery_card_points(frame("mastery_last_row"))
    last_y = max(y for _, y in points)
    assert [(x, y) for x, y in points if y == last_y] == [(99, last_y)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("领取全部", "claim_all"),
        ("领 取 全 部", "claim_all"),
        ("完成 卡牌大师任务， 解锁更多奖励！", "none"),
        ("领取", "unknown"),
        ("升级", "unknown"),
        ("", "unknown"),
    ],
)
def test_only_claim_all_label_allows_bulk_collection(text, expected):
    assert mastery_footer_text_state(text) == expected


def test_no_reward_footer_exits_without_visiting_cards_or_scrolling():
    source = frame("mastery_list")
    assert mastery_footer_state(source) == "none"
    runner = RandomMasteryLoop.__new__(RandomMasteryLoop)
    runner.device = SimpleNamespace()
    runner.logger = logging.getLogger("footer-test")
    runner.total_claimed = 0
    runner.pending_claim_all = False
    runner._require = lambda _: source
    calls = []
    events = []
    runner._tap = lambda point, *args: calls.append(point)
    runner._save = lambda *args: {"fixture": "mastery_list"}
    runner._event = lambda event, **values: events.append({"event": event, **values})
    runner._mastery()
    assert calls == [CN_RANDOM_MASTERY, CN_RANDOM_MODAL_CLOSE]
    assert any(
        event["event"] == "mastery_checked" and event["no_rewards_remaining"] and event["per_card_checked"] is False
        for event in events
    )


def test_real_claim_all_button_needs_no_ocr_and_rejects_blank_color():
    # Test dependency stays scoped to this fixture or mock.
    from pyclashbot.bot.coords import (  # noqa: PLC0415
        CN_RANDOM_CLAIM_ALL,
        CN_RANDOM_CLAIM_ALL_BUTTON_ROI,
    )

    # Test dependency stays scoped to this fixture or mock.
    from pyclashbot.bot.find import (  # noqa: PLC0415
        find_cn_mastery_claim_all,
    )

    source = frame("mastery_claim_all")
    assert mastery_footer_state(source) == "claim_all"
    assert find_cn_mastery_claim_all(None, source) == CN_RANDOM_CLAIM_ALL
    blank_label = source.copy()
    x1, y1, x2, y2 = CN_RANDOM_CLAIM_ALL_BUTTON_ROI
    blank_label[y1:y2, x1:x2] = source[y1 + 2, x1 + 2]
    assert mastery_footer_state(blank_label) == "unknown"
    assert find_cn_mastery_claim_all(None, blank_label) is None
    assert mastery_footer_state((source * 0.35).astype(np.uint8)) == "unknown"


def test_claim_all_total_commits_only_after_footer_reports_no_rewards():
    # Test dependency stays scoped to this fixture or mock.
    from pyclashbot.bot.coords import (  # noqa: PLC0415
        CN_RANDOM_CLAIM_ALL,
    )

    runner = RandomMasteryLoop.__new__(RandomMasteryLoop)
    frames = iter(
        [frame("deck"), frame("mastery_claim_all"), frame("mastery_claim_all"), frame("mastery_list"), frame("deck")]
    )
    runner._require = lambda _: next(frames)
    runner.device = SimpleNamespace()
    runner.logger = logging.getLogger("claim-footer-test")
    runner.pending_claim_all = False
    runner.total_claimed = 0
    calls, commits = [], []
    runner._tap = lambda point, *args: calls.append(point)
    runner._save = lambda *args: {}
    runner._event = lambda *args, **values: None
    runner._checkpoint = lambda: None

    def return_from_claim():
        assert runner.total_claimed == 0
        assert commits == []

    runner._claim_all_return = return_from_claim
    runner._commit_rewards = lambda: commits.append("confirmed")
    runner._mastery()
    assert calls == [CN_RANDOM_MASTERY, CN_RANDOM_CLAIM_ALL, CN_RANDOM_MODAL_CLOSE]
    assert commits == ["confirmed"] and runner.total_claimed == 1
    assert runner.pending_claim_all is False


def test_live_status_retries_a_brief_windows_reader_lock_without_duplicate_event(tmp_path, monkeypatch):
    runner = RandomMasteryLoop.__new__(RandomMasteryLoop)
    runner.session = "file-lock-test"
    runner.active_battle = 1
    runner.state = "mastery"
    runner.completed = runner.generated = runner.closed_loops = runner.total_claimed = 0
    runner.card_attempts = runner.cards_confirmed = 0
    runner.work = tmp_path
    runner.trace_path = tmp_path / "trace.jsonl"
    runner.status_path = tmp_path / "status.json"
    original = Path.replace
    failures = []

    def transient_replace(path, target):
        if target == runner.status_path and not failures:
            failures.append("reader-held-file")
            raise PermissionError("simulated Windows sharing violation")
        return original(path, target)

    monkeypatch.setattr(Path, "replace", transient_replace)
    runner._event("mastery_footer_checked", footer_state="none")
    assert failures == ["reader-held-file"]
    assert json.loads(runner.status_path.read_text())["last_event"] == "mastery_footer_checked"
    assert len(runner.trace_path.read_text().splitlines()) == 1


def test_real_claim_reward_continue_and_coin_reveal_return_to_list():
    runner = RandomMasteryLoop.__new__(RandomMasteryLoop)
    snapshots = iter([frame("mastery_reward_continue"), frame("mastery_reward_coin"), frame("mastery_list")])
    runner._frame = lambda: next(snapshots)
    calls = []
    runner._tap = lambda point, *args: calls.append(point)
    runner._save = lambda *args: {"fixture": True}
    runner._event = lambda *args, **kwargs: None
    runner._reward_intro = lambda: None
    runner._record_reward = lambda *args: True
    runner._claim_all_return()
    assert calls == [CN_RANDOM_REWARD_CONTINUE, CN_RANDOM_REWARD_CONTINUE]


def test_startup_waits_through_loading_frames(monkeypatch):
    runner = RandomMasteryLoop.__new__(RandomMasteryLoop)
    frames = iter([np.zeros((633, 419, 3), dtype=np.uint8), frame("deck")])
    runner._frame = lambda: next(frames)
    runner.vision = SimpleNamespace(classify=lambda _: ("unknown", None))
    runner.device = SimpleNamespace(foreground_package=lambda: "com.tencent.tmgp.supercell.clashroyale")
    monkeypatch.setattr("pyclashbot.bot.cn_random_mastery_loop.time.sleep", lambda _: None)
    assert np.array_equal(runner._startup_frame(), frame("deck"))


def test_resumed_result_does_not_start_another_match_or_reset_deployments(tmp_path, monkeypatch):
    runner = RandomMasteryLoop.__new__(RandomMasteryLoop)
    runner.pending_battle = True
    runner.completed = 5
    runner.generated = 6
    runner.consecutive = 2
    runner.cards_confirmed, runner.card_attempts = 7, 8
    runner.work = tmp_path
    runner._frame = lambda: frame("deck")
    runner.vision = SimpleNamespace(classify=lambda _: ("result", None), outcome=lambda _: "胜利")
    runner._tap = lambda *args: (_ for _ in ()).throw(AssertionError("must not start a new match"))
    runner._save = lambda *args: {"fixture": True}
    runner._checkpoint = lambda: None
    events = []
    runner._event = lambda event, **values: events.append(event)
    runner._return_from_result = lambda: None
    runner.logger = logging.getLogger("resume-test")
    monkeypatch.setattr("pyclashbot.bot.cn_random_mastery_loop.time.sleep", lambda _: None)
    runner._battle(resumed=True)
    assert runner.completed == 6 and runner.cards_confirmed == 7 and runner.card_attempts == 8
    assert runner.pending_mastery and not runner.pending_battle
    assert events.count("battle_finished") == 1
