"""Actual daily-choice frames are handled before each loop's normal actions."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from pyclashbot.bot import cn_1v1_loop as one_module
from pyclashbot.bot.cn_1v1_loop import ChineseOneVOneLoop, ChineseVision, RecoveryExhausted
from pyclashbot.bot.cn_random_mastery_loop import RandomMasteryLoop
from pyclashbot.bot.coords import CN_DAILY_GIFT_COSMETIC_CHOICE, CN_POST_WIN_REWARD_TAP

FIXTURES = Path(__file__).with_name("fixtures")
GIFT = "cn_daily_gift/daily_gift_choice_20261004.png"
LOBBY = "cn_567/classic1v1_lobby.png"
REWARD = "cn_rewards/purple_reveal.png"
FOUR_STAR = "cn_rewards/four_star_chest.png"


def frame(name):
    result = cv2.imread(str(FIXTURES / name))
    assert result is not None, f"Missing captured screenshot: {name}"
    return result


@pytest.fixture(autouse=True)
def frozen_time(monkeypatch):
    # Both loop modules share the time module; suppress real waits only.
    clock = SimpleNamespace(now=101.0)
    monkeypatch.setattr(one_module.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(one_module.time, "sleep", lambda _: None)
    return clock


def random_runner(snapshots):
    runner = RandomMasteryLoop.__new__(RandomMasteryLoop)
    runner.stop_path = Mock(exists=Mock(return_value=False))
    runner._capture_frame = Mock(side_effect=snapshots)
    runner.vision = Mock(wraps=ChineseVision())
    runner.logger = Mock()
    runner._event = Mock()
    runner._save = Mock(return_value={"fixture": True})
    runner._tap = Mock()
    return runner


def one_runner():
    runner = ChineseOneVOneLoop.__new__(ChineseOneVOneLoop)
    runner.vision = Mock(wraps=ChineseVision())
    runner.logger = Mock()
    runner._trace = Mock()
    runner._save_evidence = Mock(return_value={"fixture": True})
    runner._tap = Mock()
    runner._recover = Mock()
    runner.state = "lobby"
    runner.state_since = 100.0
    runner.last_unknown_evidence = 100.0
    runner.reward_pending = False
    runner.reward_taps = 0
    runner.four_star_reward_seen = False
    runner.last_reward_tap_at = 100.0
    runner.last_four_star_tap_at = 0.0
    runner.battle_confirmations = 0
    runner.completed = 99
    runner.strategy_name = "hog"
    # These reward tests resume an already verified mode; the initial menu
    # causality contract is covered by test_cn_classic_mode_gate.py.
    runner._classic_menu_verified = True
    return runner


@pytest.mark.parametrize("destination", [LOBBY, REWARD])
def test_random_loop_returns_fresh_frame_after_daily_choice(destination):
    gift, following = frame(GIFT), frame(destination)
    final = following if destination == LOBBY else frame(LOBBY)
    snapshots = [gift, following] if destination == LOBBY else [gift, following, final]
    runner = random_runner(snapshots)
    assert runner._frame() is final
    assert runner._capture_frame.call_count == len(snapshots)
    assert runner._tap.call_args_list[0].args == (CN_DAILY_GIFT_COSMETIC_CHOICE, 1.5)
    assert runner._save.call_args_list[0].args[1] is gift
    assert all(call.args[0] is not gift for call in runner.vision.find.call_args_list)
    event = runner._event.call_args_list[0].args[0]
    values = runner._event.call_args_list[0].kwargs
    assert event == "daily_gift_choice"
    assert values["choice"] == "我想变好看" and values["attempt"] == 1
    assert runner._daily_gift_attempts == 0
    assert not runner._daily_reward_pending
    if destination == REWARD:
        assert runner._tap.call_args_list[1].args == (CN_POST_WIN_REWARD_TAP, 1.5)
        assert runner._save.call_args_list[1].args[1] is following


def test_random_loop_reobserves_every_repeat_and_stops_after_three_choices():
    snapshots = [frame(GIFT) for _ in range(4)]
    runner = random_runner(snapshots)
    with pytest.raises(RecoveryExhausted, match="连续3次"):
        runner._frame()
    assert runner._capture_frame.call_count == 4
    assert runner._tap.call_count == 3
    assert [call.kwargs["attempt"] for call in runner._event.call_args_list] == [1, 2, 3]
    assert [id(call.args[1]) for call in runner._save.call_args_list] == [id(item) for item in snapshots[:3]]
    runner.vision.find.assert_not_called()


def test_random_loop_unknown_after_choice_is_returned_without_a_generic_tap():
    unknown = np.full((633, 419, 3), (20, 100, 40), dtype=np.uint8)
    runner = random_runner([frame(GIFT), unknown])
    assert runner._frame() is unknown
    assert runner.vision.classify(unknown)[0] == "unknown"
    runner._tap.assert_called_once_with(CN_DAILY_GIFT_COSMETIC_CHOICE, 1.5)


def test_random_loop_daily_attempt_budget_resets_after_leaving_the_popup():
    first_lobby, next_lobby = frame(LOBBY), frame(LOBBY)
    runner = random_runner([frame(GIFT), first_lobby, frame(GIFT), next_lobby])
    assert runner._frame() is first_lobby
    assert runner._frame() is next_lobby
    assert [call.kwargs["attempt"] for call in runner._event.call_args_list] == [1, 1]


def test_random_loop_stop_marker_prevents_daily_choice_input():
    runner = random_runner([frame(GIFT)])
    runner.stop_path.exists.return_value = True
    with pytest.raises(KeyboardInterrupt):
        runner._frame()
    runner._capture_frame.assert_not_called()
    runner._tap.assert_not_called()


def test_one_loop_daily_choice_returns_before_stale_screen_classification():
    gift = frame(GIFT)
    runner = one_runner()
    runner._step(gift)
    runner.vision.classify.assert_not_called()
    runner._tap.assert_called_once_with(CN_DAILY_GIFT_COSMETIC_CHOICE)
    assert runner._save_evidence.call_args.args[1] is gift
    event = runner._trace.call_args.args[0]
    assert event["event"] == "daily_gift_choice" and event["choice"] == "我想变好看"
    assert runner.reward_pending and runner.reward_taps == 0


@pytest.mark.parametrize("destination", [LOBBY, REWARD])
def test_one_loop_next_iteration_uses_new_captured_frame(destination):
    gift, following = frame(GIFT), frame(destination)
    runner = one_runner()
    screenshots = Mock(side_effect=[gift, following])
    runner._step(screenshots())
    runner._step(screenshots())
    assert screenshots.call_count == 2
    assert runner.vision.classify.call_count == 1
    assert runner.vision.classify.call_args.args[0] is following
    assert runner._tap.call_args_list[0].args == (CN_DAILY_GIFT_COSMETIC_CHOICE,)
    if destination == LOBBY:
        assert runner.state == "match" and not runner.reward_pending
    else:
        assert runner._tap.call_args_list[1].args == (CN_POST_WIN_REWARD_TAP,)
        assert runner.reward_pending and runner.reward_taps == 1
    assert runner._daily_gift_attempts == 0


def test_one_loop_continuous_daily_choice_has_three_input_limit():
    runner = one_runner()
    for _ in range(3):
        runner._step(frame(GIFT))
    with pytest.raises(RecoveryExhausted, match="连续3次"):
        runner._step(frame(GIFT))
    assert runner._tap.call_count == 3
    assert [call.args[0]["attempt"] for call in runner._trace.call_args_list] == [1, 2, 3]
    runner.vision.classify.assert_not_called()


def test_one_loop_unknown_after_daily_choice_cannot_authorize_reward_input():
    runner = one_runner()
    runner._step(frame(GIFT))
    unknown = np.zeros((633, 419, 3), dtype=np.uint8)
    runner._step(unknown)
    runner._tap.assert_called_once_with(CN_DAILY_GIFT_COSMETIC_CHOICE)
    assert runner.vision.classify.call_args.args[0] is unknown
    assert runner.vision.reward_continuation.call_count == 1
    assert runner.reward_pending


def test_one_loop_daily_attempt_budget_resets_after_popup_departure():
    runner = one_runner()
    runner._step(frame(GIFT))
    runner._step(np.zeros((633, 419, 3), dtype=np.uint8))
    runner._step(frame(GIFT))
    assert [call.args[0]["attempt"] for call in runner._trace.call_args_list] == [1, 1]
    assert runner._tap.call_count == 2


def test_random_loop_daily_context_authorizes_only_verified_four_star_continuation():
    gift, reward, lobby = frame(GIFT), frame(FOUR_STAR), frame(LOBBY)
    runner = random_runner([gift, reward, lobby])
    runner.pending_mastery, runner.pending_claim_all, runner.pending_battle = True, True, False
    runner.completed, runner.generated, runner.closed_loops = 19, 20, 18
    assert ChineseVision().classify(reward)[0] == "unknown"
    assert runner._frame() is lobby
    assert [call.args for call in runner._tap.call_args_list] == [
        (CN_DAILY_GIFT_COSMETIC_CHOICE, 1.5),
        (CN_POST_WIN_REWARD_TAP, 5),
    ]
    assert runner._capture_frame.call_count == 3
    assert runner._save.call_args_list[1].args[1] is reward
    assert not runner._daily_reward_pending
    assert (runner.pending_mastery, runner.pending_claim_all, runner.pending_battle) == (True, True, False)
    assert (runner.completed, runner.generated, runner.closed_loops) == (19, 20, 18)


def test_random_loop_four_star_frame_without_daily_context_has_no_input():
    reward = frame(FOUR_STAR)
    runner = random_runner([reward])
    assert runner._frame() is reward
    runner._tap.assert_not_called()


def test_random_loop_daily_reward_input_has_forty_tap_cap():
    runner = random_runner([frame(GIFT), *[frame(REWARD) for _ in range(41)]])
    with pytest.raises(RecoveryExhausted, match="连续40次"):
        runner._frame()
    assert runner._capture_frame.call_count == 42
    assert runner._tap.call_count == 41  # One authorized choice plus 40 rewards.
    assert runner._daily_reward_taps == 40


def test_random_loop_daily_reward_context_expires_before_any_new_input(frozen_time):
    runner = random_runner([frame(GIFT), frame(REWARD)])

    def wait_after_choice(*_):
        frozen_time.now = 221.0

    runner._tap.side_effect = wait_after_choice
    with pytest.raises(RecoveryExhausted, match="120秒"):
        runner._frame()
    runner._tap.assert_called_once_with(CN_DAILY_GIFT_COSMETIC_CHOICE, 1.5)
    assert runner._event.call_args.args[0] == "daily_gift_reward_timeout"


@pytest.mark.parametrize("destination", ["cn_random_mastery/deck.png", "cn_random_mastery/collection.png"])
def test_random_loop_verified_card_page_clears_daily_context(destination):
    following = frame(destination)
    runner = random_runner([frame(GIFT), following])
    assert runner._frame() is following
    assert not runner._daily_reward_pending
    runner._tap.assert_called_once_with(CN_DAILY_GIFT_COSMETIC_CHOICE, 1.5)


def test_one_loop_daily_context_unlocks_existing_four_star_predicate_and_tap_throttle(frozen_time):
    runner = one_runner()
    runner._step(frame(GIFT))
    reward = frame(FOUR_STAR)
    assert ChineseVision().classify(reward)[0] == "unknown"
    runner._step(reward)
    assert runner._tap.call_count == 2
    assert runner._tap.call_args.args == (CN_POST_WIN_REWARD_TAP,)
    assert runner.reward_pending and runner.four_star_reward_seen
    frozen_time.now = 104.0
    runner._step(frame(FOUR_STAR))
    assert runner._tap.call_count == 2
    frozen_time.now = 107.0
    runner._step(frame(FOUR_STAR))
    assert runner._tap.call_count == 3


def test_one_loop_daily_unknown_waits_then_recovers_without_reward_input(frozen_time):
    runner = one_runner()
    runner._step(frame(GIFT))
    unknown = np.zeros((633, 419, 3), dtype=np.uint8)
    frozen_time.now = 145.9
    runner._step(unknown)
    runner._recover.assert_not_called()
    frozen_time.now = 146.0
    runner._step(unknown)
    runner._recover.assert_called_once_with("奖励后未知画面停留超过45秒")
    runner._tap.assert_called_once_with(CN_DAILY_GIFT_COSMETIC_CHOICE)


def test_one_loop_daily_choice_preserves_existing_battle_reward_context():
    runner = one_runner()
    runner.reward_pending = True
    runner.reward_taps = 7
    runner.four_star_reward_seen = True
    runner.last_four_star_tap_at = 99.0
    runner._step(frame(GIFT))
    assert runner._daily_reward_had_existing_context
    assert runner.reward_taps == 7 and runner.four_star_reward_seen
    assert runner.last_four_star_tap_at == 99.0


def test_one_loop_known_navigation_departure_clears_only_daily_reward_context(monkeypatch):
    runner = one_runner()
    following = frame("cn_pages/collection_emotes.png")
    navigation = Mock()
    runner.device = Mock()
    monkeypatch.setattr(one_module, "recover_cn_page_once", navigation)
    runner._step(frame(GIFT))
    runner._step(following)
    assert not runner._daily_reward_pending and not runner.reward_pending
    navigation.assert_called_once()
    assert navigation.call_args.kwargs["frame"] is following
    runner._tap.assert_called_once_with(CN_DAILY_GIFT_COSMETIC_CHOICE)


def test_one_loop_known_page_keeps_reward_context_that_predates_daily_choice(monkeypatch):
    runner = one_runner()
    runner.reward_pending, runner.reward_taps = True, 7
    navigation = Mock()
    monkeypatch.setattr(one_module, "recover_cn_page_once", navigation)
    runner._step(frame(GIFT))
    runner._step(frame("cn_pages/collection_emotes.png"))
    assert not runner._daily_reward_pending
    assert runner.reward_pending and runner.reward_taps == 7
    navigation.assert_not_called()
    runner._tap.assert_called_once_with(CN_DAILY_GIFT_COSMETIC_CHOICE)


def test_one_loop_daily_four_star_reward_preserves_existing_forty_input_cap():
    runner = one_runner()
    runner._step(frame(GIFT))
    runner.reward_taps = 40
    runner.four_star_reward_seen = True
    runner._step(frame(FOUR_STAR))
    runner._tap.assert_called_once_with(CN_DAILY_GIFT_COSMETIC_CHOICE)
    runner._recover.assert_called_once_with("即时奖励画面超出预期步骤")
