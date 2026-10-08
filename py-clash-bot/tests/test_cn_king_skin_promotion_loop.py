"""The exact free-standing King-skin promotion authorizes Close only."""

from itertools import chain, repeat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import pytest

from pyclashbot.bot import cn_random_mastery_loop as module
from pyclashbot.bot.cn_1v1_loop import ChineseVision, RecoveryExhausted
from pyclashbot.bot.cn_random_mastery_loop import RandomMasteryLoop
from pyclashbot.detection.cn_page_navigation import cn_king_skin_promotion_close
from pyclashbot.emulators.base import CLASH_ROYALE_PACKAGE

FIXTURES = Path(__file__).with_name("fixtures")
PROMOTIONS = (
    "king_skin_promotion_20261006.png",
    "king_skin_promotion_before_relaunch_20261006.png",
    "king_skin_promotion_current_20261006.png",
)


def frame(name):
    image = cv2.imread(str(FIXTURES / name))
    assert image is not None, name
    return image


def promotion(name=PROMOTIONS[0]):
    return frame(f"cn_pages/{name}")


def lobby():
    return frame("cn_pages/classic_glow_verified_lobby.png")


@pytest.fixture
def clock(monkeypatch):
    current = SimpleNamespace(now=500.0)
    monkeypatch.setattr(module.time, "monotonic", lambda: current.now)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: setattr(current, "now", current.now + seconds))
    return current


def runner_for(snapshots, tmp_path, clock):
    runner = RandomMasteryLoop.__new__(RandomMasteryLoop)
    runner.stop_path = tmp_path / "STOP"
    runner._capture_frame = Mock(side_effect=snapshots)
    runner.vision = ChineseVision()
    runner.device = SimpleNamespace(
        adb=Mock(return_value=SimpleNamespace(returncode=0)),
        start_app=Mock(),
        click=Mock(),
        foreground_package=Mock(return_value=CLASH_ROYALE_PACKAGE),
    )
    runner.logger, runner._event, runner._save = Mock(), Mock(), Mock(return_value={"fixture": True})
    runner._tap = Mock(side_effect=lambda point, delay: setattr(clock, "now", clock.now + delay))
    runner._checkpoint = Mock()
    runner.state = "returning"
    runner.pending_battle, runner.pending_mastery, runner.pending_claim_all = False, True, False
    runner.completed, runner.generated, runner.closed_loops, runner.total_claimed = 1598, 1611, 1597, 193
    runner.reward_claim_id = "saved-claim-id"
    runner.reward_receipts = [{"id": "saved-claim-id", "kind": "coins", "amount": 4000}]
    runner.recovery_attempts = 1
    return runner


def preserved(runner):
    assert (runner.completed, runner.generated, runner.closed_loops, runner.total_claimed) == (1598, 1611, 1597, 193)
    assert runner.reward_claim_id == "saved-claim-id"
    assert runner.reward_receipts == [{"id": "saved-claim-id", "kind": "coins", "amount": 4000}]
    assert runner.pending_mastery and runner.recovery_attempts == 1
    runner._checkpoint.assert_not_called()
    runner.device.start_app.assert_not_called()
    runner.device.adb.assert_not_called()
    runner.device.click.assert_not_called()


@pytest.mark.parametrize("name", PROMOTIONS)
def test_real_promotion_closes_once_then_returns_only_a_fresh_lobby(name, tmp_path, clock):
    source, fresh = promotion(name), lobby()
    step = cn_king_skin_promotion_close(source)
    assert step is not None
    target = step.target
    runner = runner_for([source, fresh], tmp_path, clock)
    assert runner._frame() is fresh
    runner._tap.assert_called_once_with(target, 0.8)
    assert runner._capture_frame.call_count == 2
    assert runner._event.call_args.args == ("king_skin_promotion_close_attempt",)
    assert runner._event.call_args.kwargs["attempt"] == 1
    assert runner._save.call_args.args[1] is source
    assert runner._king_skin_promotion_close_attempts == 0
    preserved(runner)


@pytest.mark.parametrize("phase", ["startup", "returning"])
def test_known_promotion_closes_in_startup_or_post_result_without_a_relaunch(phase, tmp_path, clock):
    source, fresh = promotion(), lobby()
    runner = runner_for(chain([source], repeat(fresh)), tmp_path, clock)
    runner.state = "starting" if phase == "startup" else "returning"
    runner._awaiting_relaunch_observation = phase == "startup"
    if phase == "startup":
        assert runner._startup_frame() is fresh
        assert not runner._awaiting_relaunch_observation
    else:
        runner._return_from_result()
        assert runner._event.call_args.args == ("returned_lobby",)
    step = cn_king_skin_promotion_close(source)
    assert step is not None
    runner._tap.assert_called_once_with(step.target, 0.8)
    preserved(runner)


@pytest.mark.parametrize("blocked", ["pending_battle", "pending_claim_all", "matching", "battle"])
def test_owned_transaction_or_active_battle_preserves_the_ad_without_input(blocked, tmp_path, clock):
    runner = runner_for([promotion()], tmp_path, clock)
    if blocked in ("matching", "battle"):
        runner.state = blocked
    else:
        setattr(runner, blocked, True)
    with pytest.raises(RecoveryExhausted, match="断点"):
        runner._frame()
    runner._tap.assert_not_called()
    runner._event.assert_not_called()
    preserved(runner)


def test_fourth_observed_promotion_pauses_after_only_three_close_attempts(tmp_path, clock):
    source = promotion()
    runner = runner_for(repeat(source), tmp_path, clock)
    with pytest.raises(RecoveryExhausted, match="连续3次"):
        runner._frame()
    assert runner._tap.call_count == 3
    assert runner._capture_frame.call_count == 4
    assert [call.kwargs["attempt"] for call in runner._event.call_args_list] == [1, 2, 3]
    step = cn_king_skin_promotion_close(source)
    assert step is not None
    assert all(call.args == (step.target, 0.8) for call in runner._tap.call_args_list)
    preserved(runner)


def test_nonpromotion_resets_only_the_consecutive_ad_counter(tmp_path, clock):
    other = frame("cn_pages/shop_offer_info.png")
    runner = runner_for([other], tmp_path, clock)
    runner._king_skin_promotion_close_attempts = 3
    assert runner._frame() is other
    assert runner._king_skin_promotion_close_attempts == 0
    runner._tap.assert_not_called()
    preserved(runner)


def test_stop_before_screenshot_prevents_any_ad_detection_or_input(tmp_path, clock):
    runner = runner_for([promotion()], tmp_path, clock)
    runner.stop_path.write_text("stop", encoding="utf-8")
    with pytest.raises(KeyboardInterrupt):
        runner._frame()
    runner._capture_frame.assert_not_called()
    runner._tap.assert_not_called()
    preserved(runner)


def test_stop_between_evidence_and_close_is_enforced_by_the_existing_tap_gate(tmp_path, clock):
    runner = runner_for([promotion()], tmp_path, clock)
    runner._tap = RandomMasteryLoop._tap.__get__(runner)

    def stop_before_tap(label, source):
        runner.stop_path.write_text("stop", encoding="utf-8")
        return {"fixture": True}

    runner._save.side_effect = stop_before_tap
    with pytest.raises(KeyboardInterrupt):
        runner._frame()
    preserved(runner)


@pytest.mark.parametrize(
    "name",
    [
        "cn_pages/profile_king_skin.png",
        "cn_pages/shop_offer_info.png",
        "cn_pages/emote_offer_info.png",
        "cn_pages/goblin_king_preview.png",
        "cn_pages/daily_gift_info.png",
        "cn_shop_daily/live-gem-confirm.png",
        "cn_shop_daily/live-gold-confirm.png",
        "cn_shop_daily/live-gold-purchased-modal.png",
        "cn_shop_daily/live-free-open.png",
        "cn_shop_daily/live-free-reward-1.png",
        "cn_shop_daily/live-free-reward-4.png",
    ],
)
def test_other_ads_payments_and_rewards_cannot_trigger_the_promotion_close(name, tmp_path, clock):
    source = frame(name)
    assert cn_king_skin_promotion_close(source) is None
    runner = runner_for([source], tmp_path, clock)
    assert runner._frame() is source
    runner._tap.assert_not_called()
    preserved(runner)
