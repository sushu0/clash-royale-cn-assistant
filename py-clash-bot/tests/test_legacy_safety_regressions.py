"""Offline failure boundaries for legacy navigation, input, deck and war paths."""

from pathlib import Path
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from pyclashbot.bot import card_detection, deck, fight, nav, recorder, war
from pyclashbot.bot import card_mastery_state as mastery
from pyclashbot.bot.coords import CN_RANDOM_DECK_ROIS, CN_RANDOM_HAND_ROIS
from pyclashbot.detection import cn_threats, image_rec


class FakeEmulator:
    def __init__(self, frames=None):
        self.clicks = []
        self.frames = frames or [np.zeros((633, 419, 3), np.uint8)]
        self.reads = 0

    def click(self, *coord):
        self.clicks.append(coord)

    def screenshot(self):
        frame = self.frames[min(self.reads, len(self.frames) - 1)]
        self.reads += 1
        return frame.copy()


@pytest.fixture
def logger():
    return Mock()


@pytest.mark.parametrize("result", ["restart", False, None])
def test_navigation_failure_never_clicks_deck_button(monkeypatch, logger, result):
    emulator = FakeEmulator()
    monkeypatch.setattr(nav, "get_to_card_page_from_clash_main", lambda *_: result)
    assert nav._navigate_to_deck_selection(emulator, logger) is False
    assert emulator.clicks == []


def test_signed_brightness_changes_choose_larger_change(monkeypatch):
    baseline = np.full((633, 419, 3), 100, np.uint8)
    frame = baseline.copy()
    frame[200:375, 100:140] -= 1
    frame[200:375, 275:315] += 10
    monkeypatch.setattr(card_detection, "bridge_iar", baseline)
    monkeypatch.setattr(card_detection, "battle_iar", frame)
    magnitude, lane = card_detection.switch_side()
    assert lane == "right"
    assert magnitude == pytest.approx(10 * np.sqrt(40 * 175 * 3))
    frame[200:375, 275:315] = 90
    assert card_detection.switch_side()[0] == pytest.approx(magnitude)


def test_unknown_card_has_no_placement(monkeypatch, logger):
    monkeypatch.setattr(card_detection, "identify_hand_cards", lambda *_: "UNKNOWN")
    assert card_detection.get_play_coords_for_card(FakeEmulator(), logger, 0) == ("UNKNOWN", None)


@pytest.mark.parametrize("random_mode", [False, True])
def test_unknown_card_never_sends_input_or_records_a_play(monkeypatch, logger, random_mode):
    emulator = FakeEmulator()
    monkeypatch.setattr(fight, "check_if_in_battle", lambda *_: True)
    monkeypatch.setattr(fight, "check_which_cards_are_available", lambda *_, **__: [0])
    monkeypatch.setattr(fight, "get_play_coords_for_card", lambda *_: ("UNKNOWN", None))
    if random_mode:
        result = fight.play_random_available_card(emulator, logger, True, 1)
    else:
        strategy = fight.BattleStrategy()
        strategy.start_battle()
        result = fight.play_a_card(emulator, logger, True, strategy)
    assert result is False
    assert emulator.clicks == []
    logger.add_card_played.assert_not_called()


@pytest.mark.parametrize("confirmed", [False, True])
def test_deployment_requires_independent_elixir_and_portrait_evidence(monkeypatch, logger, confirmed):
    before = np.zeros((633, 419, 3), np.uint8)
    after = before.copy()
    if confirmed:
        x1, y1, x2, y2 = CN_RANDOM_HAND_ROIS[0]
        after[y1:y2, x1:x2] = 90
    emulator = FakeEmulator([before, after])
    reads = iter([8, 4 if confirmed else 8] + [8] * 10)
    monkeypatch.setattr(fight, "_read_elixir", lambda _: next(reads))
    monkeypatch.setattr(fight, "identify_random_hand", lambda _: [{"card": "hog", "available": True}] * 4)
    ticks = iter(np.arange(0, 10, 0.5))
    monkeypatch.setattr(fight.time, "monotonic", lambda: float(next(ticks)))
    monkeypatch.setattr(fight.time, "sleep", lambda _: None)
    begin, finish = Mock(return_value=3), Mock()
    monkeypatch.setattr(fight, "begin_play_attempt", begin)
    monkeypatch.setattr(fight, "finish_play_attempt", finish)
    assert (
        fight.deploy_and_confirm(emulator, logger, 0, "hog", (113, 285), elapsed_s=3, recording_flag=True) is confirmed
    )
    assert len(emulator.clicks) == 2
    assert logger.add_card_played.call_count == int(confirmed)
    assert finish.call_args.kwargs["confirmed"] is confirmed


def test_recorder_freezes_pre_input_frame_and_excludes_unknown_attempt(tmp_path):
    rec = recorder.FightPackRecorder()
    rec.dir = str(tmp_path)
    rec._frame_count = 4
    unknown = rec.begin_play_attempt(0, 113, 285, 3)
    confirmed = rec.begin_play_attempt(1, 113, 300, 5)
    rec._frame_count = 10
    rec.finish_play_attempt(unknown, confirmed=False, method="timeout")
    rec.finish_play_attempt(confirmed, confirmed=True, method="elixir_drop_and_portrait")
    rec.finish_play_attempt(confirmed, confirmed=True, method="replayed")
    assert len(rec._plays) == 1
    assert rec._plays[0]["frame_index"] == 4
    assert [row["status"] for row in rec._attempts] == ["unknown", "confirmed"]
    rec._write_attempts()
    rec._write_plays()
    assert len((tmp_path / "attempts.jsonl").read_text().splitlines()) == 2
    assert len((tmp_path / "plays.jsonl").read_text().splitlines()) == 1


def test_attempt_is_durable_before_input_and_unknown_never_becomes_training_data(tmp_path):
    # Test dependency stays scoped to this fixture or mock.
    import json  # noqa: PLC0415

    rec = recorder.FightPackRecorder()
    rec.dir = str(tmp_path)
    attempt = rec.begin_play_attempt(0, 113, 285, 3)
    assert json.loads((tmp_path / "attempt-events.jsonl").read_text())["status"] == "attempted"
    rec.finish_play_attempt(attempt, confirmed=False, method="capture_failed")
    assert not (tmp_path / "plays.jsonl").exists()
    assert len((tmp_path / "attempt-events.jsonl").read_text().splitlines()) == 2


def test_unsaved_capture_does_not_increment_frame_count(tmp_path, monkeypatch):
    rec = recorder.FightPackRecorder()
    rec.frames_source = "png"
    rec._frames_dir = str(tmp_path)
    monkeypatch.setattr(recorder.cv2, "imwrite", lambda *_: False)
    rec._write_frame(np.zeros((633, 419, 3), np.uint8))
    assert rec._frame_count == 0
    assert rec._capture_errors == 1


@pytest.mark.parametrize(
    "observed,elixir",
    [
        ({"card": "hog", "available": False}, 8),
        ({"card": "knight", "available": True}, 8),
        ({"card": "hog", "available": True}, 3),
        ({"card": None, "available": True}, 8),
    ],
)
def test_stale_unavailable_or_unaffordable_hand_does_not_send_input(monkeypatch, logger, observed, elixir):
    emulator = FakeEmulator()
    monkeypatch.setattr(fight, "_read_elixir", lambda *_: elixir)
    monkeypatch.setattr(fight, "identify_random_hand", lambda _: [observed] * 4)
    assert not fight.deploy_and_confirm(emulator, logger, 0, "hog", (113, 285), elapsed_s=3)
    assert emulator.clicks == []


@pytest.mark.parametrize("random_mode", [False, True])
def test_new_battle_clears_previous_slot_history(monkeypatch, logger, random_mode):
    fight.last_three_cards.extend([0, 1, 2])
    monkeypatch.setattr(fight, "create_default_bridge_iar", lambda *_: None)
    monkeypatch.setattr(fight, "check_for_in_battle_with_delay", lambda *_: False)
    monkeypatch.setattr(fight, "check_if_battle_has_ended", lambda *_: True)
    monkeypatch.setattr(fight.time, "sleep", lambda _: None)
    logger.get_cards_played.return_value = 0
    if random_mode:
        assert fight._random_fight_loop(FakeEmulator(), logger)
    else:
        assert fight._fight_loop(FakeEmulator(), logger, False)
    assert not fight.last_three_cards


def test_randomization_unknown_page_cannot_succeed_via_return_to_main(monkeypatch, logger):
    monkeypatch.setattr(deck, "_navigate_to_deck_selection", lambda *_: True)
    monkeypatch.setattr(deck, "_select_requested_deck", lambda *_: True)
    for function in (
        "check_if_on_trophy_road_deck_page",
        "check_if_on_classic_2v2_deck_page",
        "check_if_on_classic_1v1_deck_page",
    ):
        monkeypatch.setattr(deck, function, lambda *_: False)
    monkeypatch.setattr(deck, "return_to_clash_main_from_card_page", lambda *_: True)
    assert deck.randomize_deck(FakeEmulator(), logger, 7) is False
    logger.add_card_randomization.assert_not_called()


def test_requested_deck_cannot_be_substituted(monkeypatch, logger):
    monkeypatch.setattr(deck, "is_single_deck_layout_by_pixel", lambda *_: True)
    assert deck._select_requested_deck(FakeEmulator(), logger, 2) is False
    assert deck._select_requested_deck(FakeEmulator(), logger, 1) is True


def test_requested_second_page_tab_is_used(monkeypatch, logger):
    emulator = FakeEmulator()
    monkeypatch.setattr(deck, "is_single_deck_layout_by_pixel", lambda *_: False)
    paths = []

    def match(_image, folder, **_):
        paths.append(folder)
        return (20, 100)

    monkeypatch.setattr(deck, "find_image", match)
    switched = Mock(return_value=True)
    monkeypatch.setattr(deck, "switch_deck_page", switched)
    monkeypatch.setattr(deck.time, "sleep", lambda _: None)
    assert deck._select_requested_deck(emulator, logger, 7)
    switched.assert_called_once()
    assert paths[-1] == "deck_tabs/deck_7"


def test_randomization_requires_changed_stable_portraits(monkeypatch):
    before = np.zeros((633, 419, 3), np.uint8)
    after = before.copy()
    x1, y1, x2, y2 = CN_RANDOM_DECK_ROIS[0]
    after[y1:y2, x1:x2] = 150
    monkeypatch.setattr(deck, "is_deck_full", lambda *_: True)
    monkeypatch.setattr(deck.time, "sleep", lambda _: None)
    assert not deck._verify_randomized_deck(FakeEmulator([before]), before)
    assert deck._verify_randomized_deck(FakeEmulator([after]), before)
    assert not deck._verify_randomized_deck(FakeEmulator([after, before]), before)


def test_mastery_child_failure_never_counts_reward(monkeypatch, logger):
    monkeypatch.setattr(mastery, "get_to_card_page_from_clash_main", lambda *_: "good")
    monkeypatch.setattr(mastery, "card_mastery_rewards_exist_with_delay", lambda *_: True)
    monkeypatch.setattr(mastery, "collect_first_mastery_reward", lambda *_, **__: False)
    monkeypatch.setattr(mastery.time, "sleep", lambda _: None)
    assert mastery.collect_card_mastery_rewards(FakeEmulator(), logger) is False
    logger.add_card_mastery_reward_collection.assert_not_called()


def test_mastery_persistent_icon_with_no_progress_is_not_counted(monkeypatch, logger):
    monkeypatch.setattr(mastery, "get_to_card_page_from_clash_main", lambda *_: "good")
    monkeypatch.setattr(mastery, "card_mastery_rewards_exist_with_delay", lambda *_: True)
    monkeypatch.setattr(mastery, "card_mastery_rewards_exist", lambda *_: True)
    monkeypatch.setattr(mastery, "collect_first_mastery_reward", lambda *_, **__: True)
    monkeypatch.setattr(mastery.time, "sleep", lambda _: None)
    assert mastery.collect_card_mastery_rewards(FakeEmulator(), logger) is False
    logger.add_card_mastery_reward_collection.assert_not_called()


def test_mastery_total_collection_budget_stops_a_persistent_icon(monkeypatch, logger):
    monkeypatch.setattr(mastery, "get_to_card_page_from_clash_main", lambda *_: "good")
    monkeypatch.setattr(mastery, "card_mastery_rewards_exist_with_delay", lambda *_: True)
    monkeypatch.setattr(mastery, "card_mastery_rewards_exist", lambda *_: True)
    monkeypatch.setattr(mastery, "collect_first_mastery_reward", lambda *_, **__: True)
    monkeypatch.setattr(mastery, "_mastery_progress", lambda *_: True)
    monkeypatch.setattr(mastery, "_MAX_COLLECTIONS", 2)
    monkeypatch.setattr(mastery.time, "sleep", lambda _: None)
    assert mastery.collect_card_mastery_rewards(FakeEmulator(), logger) is False
    assert logger.add_card_mastery_reward_collection.call_count == 2


def test_war_deck_generation_failure_stops_flow(monkeypatch, logger):
    monkeypatch.setattr(war, "which_war_decks_exist", lambda *_: {})
    make = Mock(return_value=False)
    monkeypatch.setattr(war, "make_war_deck", make)
    assert war._ensure_all_war_decks(FakeEmulator(), logger) is False
    make.assert_called_once()


def test_war_uses_confirmed_available_hand_path(monkeypatch, logger):
    monkeypatch.setattr(war, "create_default_bridge_iar", lambda *_: None)
    in_battle = iter([True, False])
    monkeypatch.setattr(war, "check_for_in_battle_with_delay", lambda *_: next(in_battle))
    monkeypatch.setattr(war, "check_if_battle_has_ended", lambda *_: True)
    play = Mock(return_value=False)
    monkeypatch.setattr(war, "play_a_card", play)
    monkeypatch.setattr(war.time, "sleep", lambda _: None)
    emulator = FakeEmulator()
    assert war.war_battle_loop(emulator, logger)
    play.assert_called_once()
    assert emulator.clicks == []


def test_war_lost_detection_requires_recovery_instead_of_reporting_success(monkeypatch, logger):
    monkeypatch.setattr(war, "create_default_bridge_iar", lambda *_: None)
    monkeypatch.setattr(war, "check_for_in_battle_with_delay", lambda *_: False)
    monkeypatch.setattr(war, "check_if_battle_has_ended", lambda *_: False)
    monkeypatch.setattr(war.time, "sleep", lambda _: None)
    assert not war.war_battle_loop(FakeEmulator(), logger)


def test_parallel_template_results_and_logs_bind_the_right_filename(tmp_path, monkeypatch, capsys):
    for name in ("z_fast.png", "a_slow.png"):
        (tmp_path / name).write_bytes(b"fixture")
    monkeypatch.setattr(image_rec, "_reference_gray", lambda path, *_: np.full((2, 2), int("fast" in path), np.uint8))
    original_sleep = __import__("time").sleep

    def compare(_image, template, _tolerance):
        if template[0, 0] == 0:
            original_sleep(0.03)
            return None
        return [3, 7]

    monkeypatch.setattr(image_rec, "compare_images", compare)
    image = np.zeros((15, 15, 3), np.uint8)
    locations, names = image_rec.find_references(image, str(tmp_path))
    assert names == ["a_slow.png", "z_fast.png"]
    assert locations == [None, [3, 7]]
    assert image_rec.find_image(image, str(tmp_path)) == (7, 3)
    assert "z_fast.png" in capsys.readouterr().out


def test_empty_template_folder_returns_no_match(tmp_path):
    assert image_rec.find_references(np.zeros((5, 5, 3), np.uint8), str(tmp_path)) == ([], [])


def test_template_conversion_uses_opencv_bgr_weights():
    image = np.array([[[255, 0, 0], [0, 0, 255]]], np.uint8)
    assert np.array_equal(image_rec._as_gray(image), cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))
    assert image_rec._as_gray(image)[0, 0] < image_rec._as_gray(image)[0, 1]


def test_saved_deck_frame_keeps_switch_deck_threshold_without_lowering():
    frame = cv2.imread(str(Path(__file__).parent / "fixtures/cn_567/wrong_hog_deck.png"))
    assert frame is not None
    # Test dependency stays scoped to this fixture or mock.
    from pyclashbot.bot.coords import (  # noqa: PLC0415
        DECK_TABS_REGION,
    )

    assert image_rec.find_image(frame, "deck_tabs/switch_deck", tolerance=0.98, subcrop=DECK_TABS_REGION) is not None


@pytest.mark.parametrize(
    "signal,accepted",
    [
        ({"confidence": 0.805, "confidence_threshold": 0.74}, True),
        ({"confidence": 0.805}, False),
        ({"confidence": 0.95}, True),
        ({"confidence": 0.99, "approved": False}, False),
        ({"confidence": float("nan"), "confidence_threshold": 0.74}, False),
        ({"confidence": 0.99, "confidence_threshold": -0.1}, False),
        ({"confidence": "high"}, False),
    ],
)
def test_detector_threshold_contract(signal, accepted):
    assert cn_threats.approved_threat(signal) is accepted


def test_saved_air_frame_flows_from_calibrated_detector_into_air_defense():
    # Test dependency stays scoped to this fixture or mock.
    from pyclashbot.bot.random_card_roles import (  # noqa: PLC0415
        role_for,
    )

    # Test dependency stays scoped to this fixture or mock.
    from pyclashbot.bot.random_deck_strategy import (  # noqa: PLC0415
        RandomDeckStrategy,
    )

    # Test dependency stays scoped to this fixture or mock.
    from pyclashbot.detection.cn_battle_cues import (  # noqa: PLC0415
        read_cn_battle_cues,
    )

    frame = cv2.imread(str(Path(__file__).parent / "fixtures/cn_threats/air_independent_deep.png"))
    assert frame is not None
    cues = read_cn_battle_cues(frame)
    assert any(0.74 <= item["confidence"] < 0.88 and cn_threats.approved_threat(item) for item in cues["threats"])
    cues["elixir"] = 5
    hand = [
        {"slot": slot, "card": name, "variant": name, "available": True, "cost": role_for(name).cost}
        for slot, name in enumerate(("cannon", "musketeer", "knight", "log"))
    ]
    decision = RandomDeckStrategy(0).decide(hand, cues, 20)
    assert decision.card == "musketeer"
    assert decision.category == "defense"


def test_missing_manifest_is_environment_fault_not_empty_threats(tmp_path, monkeypatch):
    monkeypatch.setattr(cn_threats, "_FOLDER", tmp_path)
    assert cn_threats.threat_template_health()["status"] == "invalid"
    with pytest.raises(cn_threats.ThreatTemplateError, match="manifest"):
        cn_threats.read_cn_threats(np.zeros((633, 419, 3), np.uint8), [])


def test_template_hash_tampering_is_reported(tmp_path, monkeypatch):
    # Test dependency stays scoped to this fixture or mock.
    import json  # noqa: PLC0415

    # Test dependency stays scoped to this fixture or mock.
    import shutil  # noqa: PLC0415

    source = Path(cn_threats._FOLDER)
    for file in source.glob("*"):
        if file.is_file():
            shutil.copy2(file, tmp_path / file.name)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    target = tmp_path / manifest[0]["file"]
    target.write_bytes(target.read_bytes() + b"modified")
    monkeypatch.setattr(cn_threats, "_FOLDER", tmp_path)
    health = cn_threats.threat_template_health(force=True)
    assert health["status"] == "invalid"
    assert "hash mismatch" in health["errors"][0]


@pytest.mark.parametrize(
    "field,value",
    [
        ("threshold", "high"),
        ("threshold", float("nan")),
        ("anchor_offset", None),
        ("enabled", "yes"),
        ("template_sha256", "bad"),
        ("file", "../outside.png"),
    ],
)
def test_bad_manifest_schema_is_reported_as_asset_fault(tmp_path, monkeypatch, field, value):
    # Test dependency stays scoped to this fixture or mock.
    import json  # noqa: PLC0415

    manifest = json.loads((Path(cn_threats._FOLDER) / "manifest.json").read_text())
    manifest[0][field] = value
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(cn_threats, "_FOLDER", tmp_path)
    assert cn_threats.threat_template_health(force=True)["status"] == "invalid"
