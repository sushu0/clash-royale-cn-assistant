"""The exact recorded Global Challenge advert authorizes its Close button only."""

from itertools import chain, repeat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import pytest

from pyclashbot.bot import cn_random_mastery_loop as module
from pyclashbot.bot.cn_1v1_loop import ChineseVision, RecoveryExhausted
from pyclashbot.bot.cn_random_mastery_loop import RandomMasteryLoop
from pyclashbot.detection.cn_page_navigation import cn_global_challenge_promotion_close
from pyclashbot.emulators.base import CLASH_ROYALE_PACKAGE

FIXTURES = Path(__file__).with_name("fixtures")


def image(name):
    result = cv2.imread(str(FIXTURES / name))
    assert result is not None, name
    return result


def advert():
    return image("cn_pages/global_challenge_promotion_20261007.png")


def lobby():
    return image("cn_pre_match/failed_lobby_20261006.png")


@pytest.fixture
def clock(monkeypatch):
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(module.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: setattr(clock, "now", clock.now + seconds))
    return clock


def runner_for(snapshots, tmp_path, clock):
    runner = RandomMasteryLoop.__new__(RandomMasteryLoop)
    runner.stop_path = tmp_path / "STOP"
    runner._capture_frame = Mock(side_effect=snapshots)
    runner.vision = ChineseVision()
    runner.device = SimpleNamespace(
        adb=Mock(), start_app=Mock(), click=Mock(), foreground_package=Mock(return_value=CLASH_ROYALE_PACKAGE)
    )
    runner.logger, runner._event, runner._save = Mock(), Mock(), Mock(return_value={"fixture": True})
    runner._tap = Mock(side_effect=lambda point, seconds: setattr(clock, "now", clock.now + seconds))
    runner._checkpoint = Mock()
    runner.state = "returning"
    runner.pending_mastery, runner.pending_battle, runner.pending_claim_all = True, False, False
    runner.completed, runner.closed_loops, runner.generated, runner.total_claimed = 1841, 1840, 1855, 205
    runner.reward_claim_id = "original-claim-id"
    runner.reward_receipts = [{"id": "original-claim-id", "kind": "coins", "amount": 4000}]
    runner.recovery_attempts = 1
    return runner


def preserved(runner):
    assert (runner.completed, runner.closed_loops, runner.generated, runner.total_claimed) == (1841, 1840, 1855, 205)
    assert runner.reward_claim_id == "original-claim-id"
    assert runner.reward_receipts == [{"id": "original-claim-id", "kind": "coins", "amount": 4000}]
    assert runner.recovery_attempts == 1
    runner._checkpoint.assert_not_called()
    runner.device.adb.assert_not_called()
    runner.device.start_app.assert_not_called()
    runner.device.click.assert_not_called()


def test_real_advert_has_only_the_red_close_target_then_fresh_lobby(tmp_path, clock):
    source, fresh = advert(), lobby()
    step = cn_global_challenge_promotion_close(source)
    assert step is not None
    assert step.target == (388, 65)
    runner = runner_for([source, fresh], tmp_path, clock)
    assert runner._frame() is fresh
    runner._tap.assert_called_once_with((388, 65), 0.8)
    assert runner._capture_frame.call_count == 2
    assert runner._event.call_args.args == ("global_challenge_promotion_close_attempt",)
    assert runner._global_challenge_promotion_close_attempts == 0
    preserved(runner)


@pytest.mark.parametrize("mastery", [False, True])
def test_startup_can_close_an_exact_ad_without_claiming_or_buying(mastery, tmp_path, clock):
    source, fresh = advert(), lobby()
    runner = runner_for([source, fresh], tmp_path, clock)
    runner.state = "starting"
    runner.pending_mastery = mastery
    runner._awaiting_relaunch_observation = True
    assert runner._startup_frame() is fresh
    runner._tap.assert_called_once_with((388, 65), 0.8)
    assert runner.pending_mastery is mastery
    preserved(runner)


def test_post_result_closes_ad_and_returns_to_stable_lobby_without_relaunch(tmp_path, clock):
    source, fresh = advert(), lobby()
    runner = runner_for(chain([source], repeat(fresh)), tmp_path, clock)
    runner._return_from_result(allow_restart=False)
    runner._tap.assert_called_once_with((388, 65), 0.8)
    assert runner._event.call_args.args == ("returned_lobby",)
    assert runner.pending_mastery
    preserved(runner)


def test_ad_close_can_reobserve_a_real_puzzle_before_returning_to_lobby(tmp_path, clock):
    source, fresh = advert(), lobby()
    reward = image("cn_puzzle_reward/puzzle_open_20261007.png")
    runner = runner_for(chain([source, reward], repeat(fresh)), tmp_path, clock)
    runner._return_from_result(allow_restart=False)
    assert runner._tap.call_args_list[0].args == ((388, 65), 0.8)
    assert runner._tap.call_count == 2
    assert any(call.args == ("post_battle_puzzle_reward",) for call in runner._event.call_args_list)
    assert runner._event.call_args.args == ("returned_lobby",)
    preserved(runner)


@pytest.mark.parametrize("blocked", ["pending_battle", "pending_claim_all", "matching", "battle", "foreign_app"])
def test_protected_transaction_or_foreign_app_preserves_ad_without_input(blocked, tmp_path, clock):
    runner = runner_for([advert()], tmp_path, clock)
    if blocked in ("matching", "battle"):
        runner.state = blocked
    elif blocked == "foreign_app":
        runner.device.foreground_package.return_value = "com.example.foreign"
    else:
        setattr(runner, blocked, True)
    with pytest.raises(RecoveryExhausted):
        runner._frame()
    runner._tap.assert_not_called()
    runner._event.assert_not_called()
    preserved(runner)


def test_fourth_consecutive_ad_pauses_after_exactly_three_close_attempts(tmp_path, clock):
    runner = runner_for(repeat(advert()), tmp_path, clock)
    with pytest.raises(RecoveryExhausted, match="连续3次"):
        runner._frame()
    assert [call.args for call in runner._tap.call_args_list] == [((388, 65), 0.8)] * 3
    assert runner._capture_frame.call_count == 4
    assert [call.kwargs["attempt"] for call in runner._event.call_args_list] == [1, 2, 3]
    preserved(runner)


def test_stop_before_capture_blocks_the_ad_and_every_input(tmp_path, clock):
    runner = runner_for([advert()], tmp_path, clock)
    runner.stop_path.write_text("stop", encoding="utf-8")
    with pytest.raises(KeyboardInterrupt):
        runner._frame()
    runner._capture_frame.assert_not_called()
    runner._tap.assert_not_called()
    preserved(runner)


def test_stop_after_evidence_is_enforced_by_the_original_tap_channel(tmp_path, clock):
    runner = runner_for([advert()], tmp_path, clock)
    runner._tap = RandomMasteryLoop._tap.__get__(runner)

    def stop(label, source):
        runner.stop_path.write_text("stop", encoding="utf-8")
        return {"fixture": True}

    runner._save.side_effect = stop
    with pytest.raises(KeyboardInterrupt):
        runner._frame()
    preserved(runner)


@pytest.mark.parametrize(
    "name",
    [
        "cn_pages/king_skin_promotion_20261006.png",
        "cn_pages/emote_offer_info.png",
        "cn_pages/shop_offer_info.png",
        "cn_shop_daily/live-gem-confirm.png",
        "cn_shop_daily/live-gold-confirm.png",
        "cn_shop_daily/live-gold-purchased-modal.png",
        "cn_shop_daily/live-free-reward-1.png",
        "cn_puzzle_reward/puzzle_open_20261007.png",
        "cn_daily_gift/loading_after_relaunch_20261006.png",
        "cn_daily_gift/black_daily_timeout_20261006.png",
    ],
)
def test_other_adverts_payments_rewards_or_unknown_frames_cannot_use_this_close(name):
    assert cn_global_challenge_promotion_close(image(name)) is None
