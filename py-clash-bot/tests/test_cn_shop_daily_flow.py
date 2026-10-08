"""Transaction regressions use fresh mocked screens and never contact a device."""

from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from pyclashbot.bot import cn_shop_daily_state as flow
from pyclashbot.bot.coords import CN_SHOP_DAILY_FREE_GOLD_CANCEL, CN_SHOP_DAILY_FREE_GOLD_CONFIRM


def item(slot, currency="purchased", price=None):
    return {
        "slot": slot,
        "row": slot // 3,
        "column": slot % 3,
        "currency": currency,
        "price": 0 if currency == "free" else price,
        "center": (70 + (slot % 3) * 139, 260 + (slot // 3) * 190),
        "price_y": 310 + (slot // 3) * 225,
        "item_id": f"card-{slot}",
    }


def shop(items=None, *, gold=10000, header=True, daily_end=True):
    return {
        "valid": True,
        "shop_verified": True,
        "daily_header": (209, 190) if header else None,
        "daily_anchor_y": 190 if header else None,
        "visible_items": items if items is not None else [item(slot) for slot in range(6)],
        "daily_end": daily_end,
        "gold": gold,
    }


def modal(currency="gold", price=500, *, insufficient=False):
    return {
        "valid": True,
        "shop_verified": False,
        "visible_items": [],
        "dialog": {"currency": currency, "price": price, "confirm": (210, 404), "cancel": (350, 125)},
        "insufficient": insufficient,
    }


@pytest.fixture
def harness(monkeypatch):
    states = {}
    frames = {}

    def register(name, state):
        frame = np.zeros((633, 419, 3), dtype=np.uint8)
        frame[0, 0, 0] = len(states) + 1
        states[int(frame[0, 0, 0])] = state
        frames[name] = frame
        return frame

    def state(frame):
        return states[int(frame[0, 0, 0])]

    def analyze(frame, daily_anchor_y=None):
        result = state(frame).copy()
        result["visible_items"] = [row.copy() for row in result.get("visible_items", [])]
        if daily_anchor_y is not None:
            result["daily_anchor_y"] = daily_anchor_y
        return result

    monkeypatch.setattr(flow, "analyze_shop_frame", analyze)
    monkeypatch.setattr(flow, "confirmation", lambda frame: state(frame).get("dialog"))
    monkeypatch.setattr(flow, "reward_state", lambda frame: state(frame).get("reward"))
    monkeypatch.setattr(flow, "read_gold_balance", lambda frame: state(frame).get("gold"))
    monkeypatch.setattr(flow, "insufficient_gold", lambda frame: state(frame).get("insufficient", False))
    monkeypatch.setattr(flow, "cn_navigation_step", lambda _frame: None)
    monkeypatch.setattr(flow, "OBSERVATION_INTERVAL", 0)

    def device(names):
        queue = iter([frames[name] for name in names])
        current = frames[names[-1]]

        def screenshot():
            nonlocal current
            current = next(queue, current)
            return current

        return SimpleNamespace(screenshot=Mock(side_effect=screenshot), click=Mock(), swipe=Mock())

    return SimpleNamespace(register=register, device=device, state=state)


def run(emulator, *, event=None, update=None):
    return flow.run_shop_daily(emulator, Mock(), cancel_event=event or Event(), on_update=update)


def test_cancelled_before_start_performs_no_screen_or_device_input(harness):
    harness.register("shop", shop())
    emulator = harness.device(["shop"])
    event = Event()
    event.set()
    result = run(emulator, event=event)
    assert result["state"] == "cancelled"
    emulator.screenshot.assert_not_called()
    emulator.click.assert_not_called()
    emulator.swipe.assert_not_called()


def test_gold_purchase_requires_fresh_confirm_and_success_receipt(harness):
    products = [item(0, "gold", 500), item(1, "gems", 100), *[item(slot) for slot in range(2, 6)]]
    harness.register("before", shop(products))
    harness.register("modal", modal())
    harness.register("after", shop(products, gold=9500))
    emulator = harness.device(["before", "before", "modal", "modal", "after"])
    updates = []
    result = run(emulator, update=updates.append)
    assert result["state"] == "completed"
    assert result["gold_purchased"] == 1 and result["gold_spent"] == 500
    assert result["free_claimed"] == 0 and result["gems_skipped"] == 1
    assert emulator.click.call_args_list[1].args == (210, 404)
    assert emulator.click.call_count == 2
    assert result["items"][0]["evidence"] == "verified_gold_decrease"
    assert len(updates) >= 8


@pytest.mark.parametrize("changed_on_recheck", [False, True])
def test_gem_currency_in_confirmation_is_cancelled_never_confirmed(harness, changed_on_recheck):
    products = [item(0, "gold", 500), *[item(slot) for slot in range(1, 6)]]
    harness.register("shop", shop(products))
    harness.register("gold", modal())
    harness.register("gems", modal("gems", 100))
    names = ["shop", "shop"] + (["gold", "gems"] if changed_on_recheck else ["gems"]) + ["shop"]
    emulator = harness.device(names)
    result = run(emulator)
    assert result["state"] == "partial"
    assert result["gold_purchased"] == result["gold_spent"] == 0
    assert result["gems_skipped"] == 1
    assert result["items"][0]["state"] == "skipped_currency_changed"
    assert [call.args for call in emulator.click.call_args_list] == [(70, 260), (350, 125)]


def test_existing_purchases_and_insufficient_balance_skip_without_clicking(harness):
    products = [item(0), item(1, "gold", 500), item(2, "free"), *[item(slot) for slot in range(3, 6)]]
    # Free already claimed state is explicitly purchased, never inferred from
    # absence of its old price.
    products[2] = item(2)
    harness.register("shop", shop(products, gold=400))
    emulator = harness.device(["shop"])
    result = run(emulator)
    assert result["state"] == "partial"
    assert result["items"][1]["state"] == "insufficient_gold"
    assert result["items"][0]["state"] == "already_purchased"
    assert result["gold_purchased"] == result["free_claimed"] == 0
    emulator.click.assert_not_called()


def test_insufficient_gold_popup_is_cancelled_without_topup(harness):
    products = [item(0, "gold", 500), *[item(slot) for slot in range(1, 6)]]
    harness.register("shop", shop(products, gold=None))
    harness.register("insufficient", modal(insufficient=True))
    emulator = harness.device(["shop", "shop", "insufficient", "shop"])
    result = run(emulator)
    assert result["items"][0]["state"] == "insufficient_gold"
    assert result["gold_purchased"] == 0
    assert [call.args for call in emulator.click.call_args_list] == [(70, 260), (350, 125)]


def test_unrecognized_modal_interference_before_opening_prevents_card_click(harness):
    products = [item(0, "gold", 500), *[item(slot) for slot in range(1, 6)]]
    harness.register("shop", shop(products))
    harness.register("unknown", {"valid": True, "shop_verified": False, "visible_items": []})
    emulator = harness.device(["shop", "unknown"])
    result = run(emulator)
    assert result["state"] == "failed"
    emulator.click.assert_not_called()


def test_confirmation_disappearing_on_recheck_prevents_spending(harness):
    products = [item(0, "gold", 500), *[item(slot) for slot in range(1, 6)]]
    harness.register("shop", shop(products))
    harness.register("modal", modal())
    harness.register("unknown", {"valid": True, "shop_verified": False, "visible_items": []})
    emulator = harness.device(["shop", "shop", "modal", "unknown"])
    result = run(emulator)
    assert result["state"] == "partial"
    assert result["gold_purchased"] == 0
    assert emulator.click.call_count == 1
    assert result["items"][0]["state"] == "unverified_attempt"


def test_missing_success_evidence_stops_without_rebuying(harness):
    products = [item(0, "gold", 500), *[item(slot) for slot in range(1, 6)]]
    harness.register("shop", shop(products))
    harness.register("modal", modal())
    emulator = harness.device(["shop", "shop", "modal", "modal", "shop"])
    result = run(emulator)
    assert result["state"] == "partial"
    assert result["gold_purchased"] == result["gold_spent"] == 0
    assert result["items"][0]["state"] == "unverified_attempt"
    assert emulator.click.call_count == 2
    emulator.swipe.assert_not_called()


def test_animated_unknown_price_is_reobserved_before_skipping(harness):
    products = [item(0, "gold", 500), *[item(slot) for slot in range(1, 6)]]
    unknown = [item(0, "unknown"), *[item(slot) for slot in range(1, 6)]]
    harness.register("unknown", shop(unknown))
    harness.register("before", shop(products))
    harness.register("modal", modal())
    harness.register("after", shop(products, gold=9500))
    emulator = harness.device(["unknown", "before", "before", "modal", "modal", "after"])
    result = run(emulator)
    assert result["state"] == "completed" and result["gold_purchased"] == 1
    assert emulator.click.call_count == 2


def test_persistently_unknown_currency_is_skipped_after_bounded_observations(harness):
    products = [item(0, "unknown"), *[item(slot) for slot in range(1, 6)]]
    harness.register("unknown", shop(products))
    emulator = harness.device(["unknown"])
    result = run(emulator)
    assert result["state"] == "partial" and result["gold_purchased"] == 0
    assert result["items"][0]["state"] == "skipped_unknown"
    assert emulator.screenshot.call_count == flow.MAX_UNKNOWN_OBSERVATIONS
    emulator.click.assert_not_called()


def test_free_reward_is_counted_only_after_verified_reward_and_return(harness):
    products = [item(0, "free"), *[item(slot) for slot in range(1, 6)]]
    harness.register("shop", shop(products))
    harness.register(
        "reward", {"valid": True, "shop_verified": False, "visible_items": [], "reward": {"continue": (209, 600)}}
    )
    harness.register("after", shop())
    emulator = harness.device(["shop", "shop", "reward", "after"])
    result = run(emulator)
    assert result["state"] == "completed" and result["free_claimed"] == 1
    assert result["gold_purchased"] == result["gold_spent"] == 0
    assert [call.args for call in emulator.click.call_args_list] == [(70, 260), (209, 600)]


def test_cancellation_between_dialog_observations_never_confirms(harness):
    products = [item(0, "gold", 500), *[item(slot) for slot in range(1, 6)]]
    harness.register("shop", shop(products))
    harness.register("modal", modal())
    emulator = harness.device(["shop", "shop", "modal", "modal"])
    event = Event()
    screenshot = emulator.screenshot.side_effect

    def cancelling_screen():
        frame = screenshot()
        if emulator.screenshot.call_count == 4:
            event.set()
        return frame

    emulator.screenshot.side_effect = cancelling_screen
    result = run(emulator, event=event)
    assert result["state"] == "cancelled"
    assert result["items"][0]["state"] == "cancelled_unverified"
    assert result["gold_purchased"] == 0
    assert emulator.click.call_count == 1


def test_cancellation_after_receipt_keeps_proven_count_and_stops_next_purchase(harness):
    products = [item(0, "gold", 500), item(1, "gold", 1000), *[item(slot) for slot in range(2, 6)]]
    harness.register("before", shop(products))
    harness.register("modal", modal())
    harness.register("after", shop(products, gold=9500))
    emulator = harness.device(["before", "before", "modal", "modal", "after"])
    event = Event()

    def stop_after_receipt(result):
        if result["gold_purchased"] == 1:
            event.set()

    result = run(emulator, event=event, update=stop_after_receipt)
    assert result["state"] == "cancelled"
    assert result["gold_purchased"] == 1 and result["gold_spent"] == 500
    assert result["items"][0]["evidence"] == "verified_gold_decrease"
    assert len(result["items"]) == 1
    assert emulator.click.call_count == 2


def test_other_shop_category_without_daily_header_never_authorizes_purchase(harness):
    harness.register("shop", shop([item(0, "gold", 500)], header=False, daily_end=False))
    emulator = harness.device(["shop"])
    result = run(emulator)
    assert result["state"] == "failed"
    emulator.click.assert_not_called()
    assert emulator.swipe.call_count == flow.MAX_SEARCH_SWIPES


def test_observed_daily_end_never_scrolls_into_next_category(harness):
    harness.register("shop", shop([item(0), item(1), item(2)]))
    emulator = harness.device(["shop"])
    result = run(emulator)
    assert result["state"] == "partial"
    emulator.click.assert_not_called()
    emulator.swipe.assert_not_called()


def test_battle_frame_never_receives_navigation_or_card_input(harness, monkeypatch):
    harness.register("battle", {"valid": True, "shop_verified": False, "visible_items": []})
    monkeypatch.setattr(flow, "ChineseVision", lambda: SimpleNamespace(classify=lambda _frame: ("battle", None)))
    navigation = Mock()
    monkeypatch.setattr(flow, "navigate_main_page", navigation)
    emulator = harness.device(["battle"])
    result = run(emulator)
    assert result["state"] == "failed"
    navigation.assert_not_called()
    emulator.click.assert_not_called()
    emulator.swipe.assert_not_called()


def test_header_low_on_screen_is_positioned_with_bounded_fine_swipes(harness):
    lower = shop([], daily_end=False)
    lower.update(daily_header=(209, 494), daily_anchor_y=494)
    middle = shop([], daily_end=False)
    middle.update(daily_header=(209, 294), daily_anchor_y=294)
    harness.register("lower", lower)
    harness.register("middle", middle)
    harness.register("ready", shop())
    emulator = harness.device(["lower", "middle", "ready"])
    result = run(emulator)
    assert result["state"] == "completed"
    assert [call.args for call in emulator.swipe.call_args_list] == [flow.CN_SHOP_DAILY_SCROLL_FINE_DOWN] * 2
    emulator.click.assert_not_called()


def test_hidden_portraits_track_two_columns_by_direction_and_panel_bottom(harness, monkeypatch):
    before = [item(slot) for slot in range(3)]
    for entry in before:
        entry["bbox"] = (0, 250, 110, 452)
    after = [item(slot) for slot in range(3)]
    for entry in after:
        entry.update(slot=None, row=None, item_id=None, price_y=210, bbox=(0, 150, 110, 352))
    harness.register("before", shop(before, daily_end=False))
    harness.register("after", shop(after, header=False, daily_end=False))
    analyze = flow.analyze_shop_frame

    def tracked(frame, daily_anchor_y=None):
        result = analyze(frame, daily_anchor_y)
        if daily_anchor_y is not None:
            assert daily_anchor_y == 90
            for entry in result["visible_items"]:
                entry.update(slot=entry["column"], row=0)
        return result

    monkeypatch.setattr(flow, "analyze_shop_frame", tracked)
    worker = flow._DailyShopFlow(harness.device(["before", "after"]), Mock(), Event(), None, None)
    worker._analyze(worker._frame("before"))
    worker._swipe(flow.CN_SHOP_DAILY_SCROLL_FINE_DOWN)
    observed = worker._analyze(worker._frame("after"))
    assert worker.anchor_y == 90
    assert [entry["slot"] for entry in observed["visible_items"]] == [0, 1, 2]


def test_one_column_cannot_authorize_a_lost_daily_scroll_anchor(harness):
    before = [item(0)]
    after = [item(0)]
    after[0].update(slot=None, row=None, item_id=None, price_y=210)
    harness.register("before", shop(before, daily_end=False))
    harness.register("after", shop(after, header=False, daily_end=False))
    emulator = harness.device(["before", "after"])
    worker = flow._DailyShopFlow(emulator, Mock(), Event(), None, None)
    worker._analyze(worker._frame("before"))
    worker._swipe(flow.CN_SHOP_DAILY_SCROLL_FINE_DOWN)
    with pytest.raises(flow._StoppedError, match="每日精选商品"):
        worker._analyze(worker._frame("after"))
    emulator.click.assert_not_called()


def test_real_shop_drift_after_scroll_and_purchase_retains_lower_daily_slots():
    """Replay the native 02:20 run that formerly lost its remembered anchor."""
    fixture_root = Path(__file__).with_name("fixtures") / "cn_shop_daily"
    worker = flow._DailyShopFlow(Mock(), Mock(), Event(), None, None)
    captures = (
        ("001-navigation", None, 237),
        ("007-transaction", None, 237),
        ("008-daily-next-row", "down", 169),
        ("009-daily-next-row", "down", 94),
        ("010-item-recheck", None, 89),
        ("016-transaction", None, 85),
        ("017-daily-next-row", "down", 16),
    )
    for name, direction, expected_anchor in captures:
        frame = cv2.imread(str(fixture_root / f"drift-{name}.png"))
        assert frame is not None, name
        worker.scroll_direction = direction
        observed = worker._analyze(frame)
        assert observed["shop_verified"] is True
        assert worker.anchor_y == expected_anchor, name
        assert worker.last_visible, name
        assert all(entry["slot"] in range(6) for entry in observed["visible_items"])
        if name in {"009-daily-next-row", "010-item-recheck", "016-transaction", "017-daily-next-row"}:
            by_slot = {entry["slot"]: entry for entry in observed["visible_items"]}
            assert (by_slot[4]["currency"], by_slot[4]["price"]) == ("gold", 2000), name
            assert (by_slot[5]["currency"], by_slot[5]["price"]) == ("gems", 100), name
            assert by_slot[4]["bbox"][3] <= 572
            assert by_slot[5]["bbox"][3] <= 572
    worker.emulator.click.assert_not_called()
    worker.emulator.adb.assert_not_called()
    worker.emulator.swipe.assert_not_called()


def test_idle_unmatched_marker_preserves_last_good_anchor_and_blocks_new_slots(harness, monkeypatch):
    before = [item(slot) for slot in range(3)]
    for entry in before:
        entry["bbox"] = (0, 250, 110, 452)
    harness.register("before", shop(before, daily_end=False))
    # One column alone cannot prove idle movement; a newly exposed row must
    # not become action authority from this observation.
    one = item(0)
    one.update(item_id=None, currency="unknown", price_y=210, bbox=(0, 150, 110, 352))
    new = item(3, "gold", 1500)
    harness.register("unmatched", shop([one, new], header=False, daily_end=False))
    analyze = flow.analyze_shop_frame

    def anchored(frame, daily_anchor_y=None):
        result = analyze(frame, daily_anchor_y)
        if daily_anchor_y is not None:
            result["visible_items"] = [new.copy()]
        return result

    monkeypatch.setattr(flow, "analyze_shop_frame", anchored)
    worker = flow._DailyShopFlow(harness.device(["before", "unmatched"]), Mock(), Event(), None, None)
    worker._analyze(worker._frame("before"))
    previous = worker.last_visible.copy()
    observed = worker._analyze(worker._frame("unmatched"))
    assert worker.anchor_y == 190
    assert observed["visible_items"] == []
    assert worker.last_visible == previous
    worker.emulator.click.assert_not_called()


def _native_daily_frame(name):
    fixture_root = Path(__file__).with_name("fixtures") / "cn_shop_daily"
    frame = cv2.imread(str(fixture_root / f"{name}.png"))
    assert frame is not None, name
    return frame


def test_native_free_gold_reentry_closes_only_after_fresh_modal_evidence(monkeypatch):
    monkeypatch.setattr(flow, "OBSERVATION_INTERVAL", 0)
    device = SimpleNamespace(
        screenshot=Mock(
            side_effect=[
                _native_daily_frame("live-free-gold-open"),
                _native_daily_frame("live-free-gold-open-fresh"),
                _native_daily_frame("live-header"),
            ]
        ),
        click=Mock(),
        swipe=Mock(),
    )
    worker = flow._DailyShopFlow(device, Mock(), Event(), None, None)
    _, observed = worker._enter_shop()
    assert observed["shop_verified"] is True
    device.click.assert_called_once_with(*CN_SHOP_DAILY_FREE_GOLD_CANCEL)
    device.swipe.assert_not_called()
    assert worker.result["free_claimed"] == worker.result["gold_purchased"] == worker.result["gold_spent"] == 0
    assert worker.pending is None and worker.records == {}


@pytest.mark.parametrize("changed", ["live-gem-confirm", "live-header"])
def test_native_free_gold_reentry_change_on_fresh_frame_sends_no_input(changed):
    device = SimpleNamespace(
        screenshot=Mock(side_effect=[_native_daily_frame("live-free-gold-open"), _native_daily_frame(changed)]),
        click=Mock(),
        swipe=Mock(),
    )
    worker = flow._DailyShopFlow(device, Mock(), Event(), None, None)
    with pytest.raises(flow._StoppedError, match="关闭前"):
        worker._enter_shop()
    device.click.assert_not_called()
    device.swipe.assert_not_called()


def test_unrecognized_free_gold_modal_cannot_authorize_navigation(monkeypatch):
    source = _native_daily_frame("live-free-gold-open")
    source[386:414, 181:240] = 0
    device = SimpleNamespace(screenshot=Mock(return_value=source), click=Mock(), swipe=Mock())
    monkeypatch.setattr(flow, "ChineseVision", lambda: SimpleNamespace(classify=lambda _: ("unknown", {})))
    worker = flow._DailyShopFlow(device, Mock(), Event(), None, None)
    with pytest.raises(flow._StoppedError, match="不是已验证"):
        worker._enter_shop()
    device.click.assert_not_called()
    device.swipe.assert_not_called()


def test_native_free_gold_cancel_event_on_recheck_prevents_close():
    event = Event()
    screenshots = iter([_native_daily_frame("live-free-gold-open"), _native_daily_frame("live-free-gold-open-fresh")])
    count = 0

    def screenshot():
        nonlocal count
        count += 1
        result = next(screenshots)
        if count == 2:
            event.set()
        return result

    device = SimpleNamespace(screenshot=Mock(side_effect=screenshot), click=Mock(), swipe=Mock())
    worker = flow._DailyShopFlow(device, Mock(), event, None, None)
    with pytest.raises(flow._CancelledError):
        worker._enter_shop()
    device.click.assert_not_called()
    device.swipe.assert_not_called()


def test_native_free_gold_transaction_waits_for_positive_purchased_marker(monkeypatch):
    monkeypatch.setattr(flow, "OBSERVATION_INTERVAL", 0)
    device = SimpleNamespace(
        screenshot=Mock(
            side_effect=[
                _native_daily_frame("live-free-gold-open"),
                _native_daily_frame("live-free-gold-open-fresh"),
                _native_daily_frame("live-free-shop-return"),
            ]
        ),
        click=Mock(),
        swipe=Mock(),
    )
    worker = flow._DailyShopFlow(device, Mock(), Event(), None, None)
    worker.anchor_y = 237
    _, observed = worker._purchase(item(0, "free"), 227358)
    assert observed["shop_verified"] is True
    assert [call.args for call in device.click.call_args_list] == [(70, 260), CN_SHOP_DAILY_FREE_GOLD_CONFIRM]
    assert worker.result["free_claimed"] == 1
    assert worker.result["gold_purchased"] == worker.result["gold_spent"] == 0
    assert worker.records[0]["evidence"] == "purchased_marker"
    device.swipe.assert_not_called()


def test_native_free_gold_confirmation_without_receipt_never_counts_or_repeats(monkeypatch):
    monkeypatch.setattr(flow, "OBSERVATION_INTERVAL", 0)
    source = _native_daily_frame("live-free-gold-open-fresh")
    device = SimpleNamespace(screenshot=Mock(return_value=source), click=Mock(), swipe=Mock())
    worker = flow._DailyShopFlow(device, Mock(), Event(), None, None)
    with pytest.raises(flow._StoppedError, match="结果未能确认"):
        worker._purchase(item(0, "free"), 227358)
    assert [call.args for call in device.click.call_args_list] == [(70, 260), CN_SHOP_DAILY_FREE_GOLD_CONFIRM]
    assert worker.result["free_claimed"] == worker.result["gold_purchased"] == worker.result["gold_spent"] == 0
    assert worker.records[0]["state"] == "unverified_attempt"
    device.swipe.assert_not_called()
