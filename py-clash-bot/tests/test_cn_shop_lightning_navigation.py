"""A verified lightning tab returns from Shop without taking purchase inputs."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from pyclashbot.bot import cn_random_mastery_loop as loop_module
from pyclashbot.bot.cn_1v1_loop import ChineseVision
from pyclashbot.bot.cn_random_mastery_loop import RandomMasteryLoop
from pyclashbot.bot.coords import CN_PAGE_ROIS
from pyclashbot.detection import cn_page_navigation as page_module
from pyclashbot.detection.cn_page_navigation import cn_navigation_step
from pyclashbot.emulators.base import CLASH_ROYALE_PACKAGE

FIXTURES = Path(__file__).with_name("fixtures")


def frame(name):
    source = cv2.imread(str(FIXTURES / name))
    assert source is not None, name
    return source


def shop_frame():
    return frame("cn_pages/shop_offers_lightning.png")


def test_real_failed_shop_frame_has_three_cues_and_only_a_bottom_navigation_target():
    step = cn_navigation_step(shop_frame())
    assert step is not None and step.page == "shop_offers_lightning" and step.route == "shop"
    assert len(step.scores) == 3 and step.target == (246, 603)


@pytest.mark.parametrize("factor", [0.0, 0.35, 0.8, 0.9, 0.94])
def test_shop_dimmed_under_an_unknown_modal_authorizes_no_navigation(factor):
    source = shop_frame()
    assert cn_navigation_step((source * factor).astype(np.uint8)) is None


@pytest.mark.parametrize("roi", ["shop_category_header", "shop_nav_selected", "collection_nav_battle"])
def test_each_independent_shop_navigation_cue_is_required(roi):
    source = shop_frame()
    x1, y1, x2, y2 = CN_PAGE_ROIS[roi]
    source[y1:y2, x1:x2] = 0
    page = next(page for page in page_module.learned_pages() if page["name"] == "shop_offers_lightning")
    assert page_module._page_step(source, page) is None
    # The previously dirty daily_shop_return route uses two separate cues.
    # Preserve that route while requiring all three cues for this new variant.
    if roi != "collection_nav_battle":
        assert cn_navigation_step(source) is None


@pytest.mark.parametrize(
    "name",
    [
        "live-gem-confirm",
        "live-gold-confirm",
        "live-gold-wide-confirm",
        "live-gold-purchased-modal",
        "live-free-open",
        "live-free-reward-1",
        "live-free-reward-2",
        "live-free-reward-3",
        "live-free-reward-4",
    ],
)
def test_real_purchase_and_reward_modals_cannot_be_treated_as_a_shop_return(name):
    step = cn_navigation_step(frame(f"cn_shop_daily/{name}.png"))
    assert step is None or step.route != "shop"


def runner_for(source, monkeypatch):
    monkeypatch.setattr(loop_module.time, "sleep", lambda seconds: None)
    lobby = frame("cn_pages/classic_glow_verified_lobby.png")
    runner = RandomMasteryLoop.__new__(RandomMasteryLoop)
    runner._frame = Mock(side_effect=[source, lobby])
    runner.vision = ChineseVision()
    runner.device = SimpleNamespace(
        click=Mock(),
        adb=Mock(),
        foreground_package=Mock(return_value=CLASH_ROYALE_PACKAGE),
        screenshot=Mock(side_effect=AssertionError("The supplied fresh frame must authorize the return")),
    )
    runner.logger, runner._event, runner._save = Mock(), Mock(), Mock(return_value={"fixture": True})
    runner._tap = Mock()
    runner.state = "generating_deck"
    runner.pending_mastery, runner.pending_claim_all, runner.pending_battle = True, False, False
    runner.reward_claim_id = "owned-reward-claim"
    runner.reward_receipts = [{"id": "saved-receipt", "kind": "coins", "amount": 4000}]
    runner.completed, runner.generated, runner.closed_loops, runner.total_claimed = 1475, 1488, 1474, 181
    return runner, lobby


def test_pending_mastery_startup_returns_once_and_preserves_its_receipts_and_checkpoint(monkeypatch):
    source = shop_frame()
    runner, lobby = runner_for(source, monkeypatch)
    assert runner._startup_frame() is lobby
    assert runner._frame.call_count == 2
    runner.device.click.assert_called_once_with(246, 603)
    runner.device.adb.assert_not_called()
    runner.device.screenshot.assert_not_called()
    runner._tap.assert_not_called()
    assert runner._event.call_args.args[0] == "known_page_return"
    assert runner._save.call_args.args[1] is source
    assert runner.pending_mastery and not runner.pending_claim_all and not runner.pending_battle
    assert runner.reward_claim_id == "owned-reward-claim"
    assert runner.reward_receipts == [{"id": "saved-receipt", "kind": "coins", "amount": 4000}]
    assert (runner.completed, runner.generated, runner.closed_loops, runner.total_claimed) == (1475, 1488, 1474, 181)


@pytest.mark.parametrize("blocked", ["pending_battle", "pending_claim_all", "matching", "battle"])
def test_shop_navigation_never_takes_over_an_owned_battle_or_claim_transaction(blocked, monkeypatch):
    source = shop_frame()
    runner, _ = runner_for(source, monkeypatch)
    if blocked in {"matching", "battle"}:
        runner.state = blocked
    else:
        setattr(runner, blocked, True)
    assert not runner._return_known_page(source, expected="startup")
    runner.device.click.assert_not_called()
    runner.device.adb.assert_not_called()
    runner._tap.assert_not_called()
    assert (runner.completed, runner.generated, runner.closed_loops, runner.total_claimed) == (1475, 1488, 1474, 181)
