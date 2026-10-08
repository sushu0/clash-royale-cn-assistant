"""Native Chinese daily-shop frames and adversarial payment regressions."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from pyclashbot.bot.coords import (
    CN_SHOP_DAILY_CONFIRM,
    CN_SHOP_DAILY_FIXED_ROIS,
    CN_SHOP_DAILY_FREE_CONFIRM,
    CN_SHOP_DAILY_FREE_GOLD_CANCEL,
    CN_SHOP_DAILY_FREE_GOLD_CONFIRM,
)
from pyclashbot.detection.cn_shop_daily import (
    analyze_shop_frame,
    confirmation,
    insufficient_gold,
    read_gold_balance,
    reward_state,
)

FIXTURES = Path(__file__).with_name("fixtures")
DAILY = FIXTURES / "cn_shop_daily"


def _frame(name="live-before"):
    frame = cv2.imread(str(DAILY / f"{name}.png"))
    assert frame is not None
    assert frame.shape == (633, 419, 3)
    return frame


def _by_slot(frame, anchor=83):
    observed = analyze_shop_frame(frame, daily_anchor_y=anchor)
    return {item["slot"]: item for item in observed["visible_items"]}


def test_actual_six_slots_select_free_and_all_four_gold_offers():
    items = _by_slot(_frame())
    assert set(items) == set(range(6))
    assert [(items[slot]["currency"], items[slot]["price"]) for slot in range(6)] == [
        ("free", 0),
        ("gold", 500),
        ("gold", 1000),
        ("gold", 1500),
        ("gold", 2000),
        ("gems", 100),
    ]
    assert sum(item["price"] for item in items.values() if item["currency"] == "gold") == 5000
    assert analyze_shop_frame(_frame(), daily_anchor_y=83)["daily_end"] is True


def test_price_icons_do_not_authorize_scope_without_seen_header():
    observed = analyze_shop_frame(_frame())
    assert observed["shop_verified"] is True
    assert observed["daily_header"] is None
    assert len(observed["visible_items"]) == 6
    assert all(item["slot"] is None for item in observed["visible_items"])
    assert observed["daily_end"] is False


def test_real_header_is_found_without_clicking_incomplete_products():
    observed = analyze_shop_frame(_frame("live-header"))
    assert observed["daily_header"] == (208, 494)
    assert observed["daily_anchor_y"] == 494
    assert observed["visible_items"] == []


def test_real_header_with_first_row_assigns_only_first_three_slots():
    observed = analyze_shop_frame(_frame("live-header-firstrow"))
    assert observed["daily_header"] == (208, 242)
    assert {item["slot"] for item in observed["visible_items"]} == {0, 1, 2}
    assert observed["daily_end"] is False


@pytest.mark.parametrize("name,anchor", [("live-daily-fine-3", 86), ("live-daily-fine-4", 7)])
def test_real_subpixel_scrolls_keep_all_six_currency_labels(name, anchor):
    items = _by_slot(_frame(name), anchor)
    assert [(items[slot]["currency"], items[slot]["price"]) for slot in range(6)] == [
        ("free", 0),
        ("gold", 500),
        ("gold", 1000),
        ("gold", 1500),
        ("gold", 2000),
        ("gems", 100),
    ]


def test_independent_first_row_scroll_handles_coin_shading():
    items = _by_slot(_frame("live-daily-fine-2"), 165)
    assert [(items[slot]["currency"], items[slot]["price"]) for slot in range(3)] == [
        ("free", 0),
        ("gold", 500),
        ("gold", 1000),
    ]


def test_known_paid_offer_page_above_daily_cannot_supply_a_daily_header():
    observed = analyze_shop_frame(_frame("live-header-grid"))
    assert observed["shop_verified"] is True
    assert observed["daily_header"] is None
    assert observed["visible_items"] == []


def test_independent_capture_after_cancel_preserves_currency_and_portrait_ids():
    before = _by_slot(_frame())
    after = _by_slot(_frame("live-gold-cancel"))
    assert [(after[slot]["currency"], after[slot]["price"]) for slot in range(6)] == [
        (before[slot]["currency"], before[slot]["price"]) for slot in range(6)
    ]
    assert [after[slot]["item_id"] for slot in range(6)] == [before[slot]["item_id"] for slot in range(6)]


def test_confirm_requires_independent_modal_and_payment_evidence():
    dialog = confirmation(_frame("live-gold-confirm"))
    assert dialog is not None
    assert dialog["currency"] == "gold"
    assert dialog["price"] == 500
    assert dialog["confirm"] == CN_SHOP_DAILY_CONFIRM
    assert analyze_shop_frame(_frame("live-gold-confirm"))["shop_verified"] is False
    assert confirmation(_frame()) is None


def test_four_digit_coin_popup_and_gem_popup_have_distinct_payment_types():
    gold = confirmation(_frame("live-gold-wide-confirm"))
    gems = confirmation(_frame("live-gem-confirm"))
    assert gold is not None and (gold["currency"], gold["price"]) == ("gold", 1000)
    assert gems is not None and (gems["currency"], gems["price"]) == ("gems", 100)


def test_free_gift_has_a_separate_calibrated_modal():
    gift = confirmation(_frame("live-free-open"))
    assert gift is not None
    assert (gift["currency"], gift["price"]) == ("free", 0)
    assert gift["confirm"] == CN_SHOP_DAILY_FREE_CONFIRM
    assert analyze_shop_frame(_frame("live-free-open"))["shop_verified"] is False


@pytest.mark.parametrize(
    "name",
    ["free_popup_title", "free_popup_close", "free_popup_corner", "free_popup_button_border", "free_popup_payment"],
)
def test_free_requires_all_of_its_own_modal_cues(name):
    frame = _frame("live-free-open")
    x1, y1, x2, y2 = CN_SHOP_DAILY_FIXED_ROIS[name]
    frame[y1:y2, x1:x2] = 0
    assert confirmation(frame) is None


@pytest.mark.parametrize("name", ["live-free-gold-open", "live-free-gold-open-fresh"])
def test_free_gold_bag_requires_its_native_modal_and_explicit_free_payment(name):
    frame = _frame(name)
    dialog = confirmation(frame)
    assert dialog == {
        "currency": "free",
        "price": 0,
        "confirm": CN_SHOP_DAILY_FREE_GOLD_CONFIRM,
        "cancel": CN_SHOP_DAILY_FREE_GOLD_CANCEL,
    }
    assert analyze_shop_frame(frame)["shop_verified"] is False
    assert read_gold_balance(frame) is None
    assert reward_state(frame) is None


@pytest.mark.parametrize(
    "name",
    [
        "free_gold_popup_title",
        "free_gold_popup_close",
        "free_gold_popup_corner",
        "free_gold_popup_bag",
        "free_gold_popup_button_border",
        "free_gold_popup_payment",
    ],
)
def test_free_gold_bag_requires_each_independent_cue(name):
    frame = _frame("live-free-gold-open-fresh")
    x1, y1, x2, y2 = CN_SHOP_DAILY_FIXED_ROIS[name]
    frame[y1:y2, x1:x2] = 0
    assert confirmation(frame) is None
    assert reward_state(frame) is None


def test_gold_gift_quantity_cannot_be_read_as_a_payment_price():
    frame = _frame("live-free-gold-open-fresh")
    frame[250:276, 180:238] = 0
    dialog = confirmation(frame)
    assert dialog is not None and (dialog["currency"], dialog["price"]) == ("free", 0)


@pytest.mark.parametrize("factor", [0.3, 0.8, 0.9])
def test_dimmed_gold_gift_modal_cannot_authorize_confirmation_or_return(factor):
    frame = (_frame("live-free-gold-open-fresh") * factor).astype(np.uint8)
    assert confirmation(frame) is None
    assert reward_state(frame) is None


def test_free_gold_button_color_without_free_label_is_insufficient():
    frame = _frame("live-free-gold-open-fresh")
    frame[386:414, 181:240] = (70, 220, 45)
    assert confirmation(frame) is None


@pytest.mark.parametrize(
    "name",
    [
        "live-free-reward-1",
        "live-free-reward-2",
        "live-free-reward-3",
        "live-free-reward-3-fresh",
        "live-free-reward-4",
    ],
)
def test_observed_free_gold_chest_reward_allows_only_a_reward_continuation(name):
    frame = _frame(name)
    reward = reward_state(frame)
    assert reward is not None and reward["kind"] == "chest"
    assert reward["continue"] is not None
    assert confirmation(frame) is None
    assert analyze_shop_frame(frame)["shop_verified"] is False


@pytest.mark.parametrize("name", ["reward_chest_background", "reward_chest_core", "reward_chest_footer"])
def test_chest_reward_requires_all_independent_cues(name):
    frame = _frame("live-free-reward-1")
    x1, y1, x2, y2 = CN_SHOP_DAILY_FIXED_ROIS[name]
    frame[y1:y2, x1:x2] = 0
    assert reward_state(frame) is None


def test_native_loot_summary_requires_its_summary_state():
    reward = reward_state(_frame("live-free-complete"))
    assert reward is not None and reward["kind"] == "complete"
    assert confirmation(_frame("live-free-complete")) is None


@pytest.mark.parametrize(
    "name", ["reward_complete_background", "reward_complete_core", "reward_complete_label", "reward_complete_footer"]
)
def test_missing_summary_evidence_does_not_authorize_continuation(name):
    frame = _frame("live-free-complete")
    x1, y1, x2, y2 = CN_SHOP_DAILY_FIXED_ROIS[name]
    frame[y1:y2, x1:x2] = 0
    assert reward_state(frame) is None


def test_native_gold_receipt_closes_its_modal_and_cannot_confirm_again():
    frame = _frame("live-gold-purchased-modal")
    reward = reward_state(frame)
    assert reward is not None and reward["kind"] == "purchased_card"
    assert reward["continue"] == (351, 202)
    assert confirmation(frame) is None
    assert analyze_shop_frame(frame)["shop_verified"] is False


@pytest.mark.parametrize(
    "name", ["popup_close", "popup_corner", "popup_card_label", "popup_purchased_label", "popup_purchased_check"]
)
def test_missing_gold_receipt_evidence_never_authorizes_close_or_confirm(name):
    frame = _frame("live-gold-purchased-modal")
    x1, y1, x2, y2 = CN_SHOP_DAILY_FIXED_ROIS[name]
    frame[y1:y2, x1:x2] = 0
    assert reward_state(frame) is None
    assert confirmation(frame) is None


def test_actual_free_and_gold_purchased_markers_are_distinct_positive_receipts():
    free = _by_slot(_frame("live-free-shop-return"), 237)
    gold = _by_slot(_frame("live-gold-shop-return"), 237)
    assert free[0]["currency"] == "purchased"
    assert free[1]["currency"] == "gold"
    assert gold[0]["currency"] == gold[1]["currency"] == "purchased"
    assert gold[2]["currency"] == "gold" and gold[2]["price"] == 1000
    assert read_gold_balance(_frame("live-free-shop-return")) == 71677
    assert read_gold_balance(_frame("live-gold-shop-return")) == 71177


def test_text_without_checkmark_does_not_count_as_already_purchased():
    frame = _frame("live-gold-shop-return")
    frame[431:460, 190:230] = 0
    assert _by_slot(frame, 237)[1]["currency"] == "unknown"


@pytest.mark.parametrize("name,anchor", [("live-paid-run-free-inertia", 93), ("live-paid-run-stable", 88)])
def test_real_subpixel_checks_keep_first_three_purchased_receipts(name, anchor):
    items = _by_slot(_frame(name), anchor)
    assert all(items[slot]["currency"] == "purchased" for slot in range(3))
    assert items[3]["currency"] == "gold" and items[3]["price"] == 1500
    assert items[4]["currency"] == "gold" and items[4]["price"] == 2000
    assert items[5]["currency"] == "gems" and items[5]["price"] == 100


def test_native_lower_purchased_card_keeps_its_label_and_check_evidence():
    items = _by_slot(_frame("live-paid-run-lower-purchased"), 15)
    assert all(items[slot]["currency"] == "purchased" for slot in range(4))
    assert items[4]["currency"] == "gold" and items[4]["price"] == 2000
    assert items[5]["currency"] == "gems" and items[5]["price"] == 100


@pytest.mark.parametrize("roi", [(42, 432, 92, 458), (35, 458, 108, 485)])
def test_new_check_variant_still_requires_both_label_and_checkmark(roi):
    frame = _frame("live-paid-run-lower-purchased")
    x1, y1, x2, y2 = roi
    frame[y1:y2, x1:x2] = 0
    assert _by_slot(frame, 15)[3]["currency"] == "unknown"


@pytest.mark.parametrize(
    "name", ["popup_close", "popup_corner", "popup_card_label", "popup_button_border", "popup_payment"]
)
def test_one_missing_modal_cue_blocks_purchase_confirmation(name):
    frame = _frame("live-gold-confirm")
    x1, y1, x2, y2 = CN_SHOP_DAILY_FIXED_ROIS[name]
    frame[y1:y2, x1:x2] = 0
    assert confirmation(frame) is None


def test_shop_background_behind_confirm_is_never_an_actionable_shop():
    frame = _frame("live-gold-confirm")
    assert analyze_shop_frame(frame, daily_anchor_y=83)["visible_items"] == []
    assert read_gold_balance(frame) is None


def test_known_gem_offer_never_misclassifies_as_gold_in_grayscale():
    frame = _frame()
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    assert analyze_shop_frame(gray, daily_anchor_y=83)["shop_verified"] is False
    assert _by_slot(frame)[5]["currency"] == "gems"


def test_missing_price_currency_is_unknown_and_cannot_supply_gold_price():
    frame = _frame()
    frame[299:327, 225:246] = (195, 175, 145)
    item = _by_slot(frame)[1]
    assert item["currency"] == "unknown"
    assert item["price"] is None


def test_price_digits_are_read_as_whole_amounts_without_prefix_matching():
    items = _by_slot(_frame())
    assert items[2]["price"] == 1000
    assert items[5]["price"] == 100
    assert read_gold_balance(_frame()) == 70078


def test_darkened_screen_does_not_authorize_items_or_confirmation():
    for name in ("live-before", "live-gold-confirm", "live-header"):
        dark = (_frame(name).astype(float) * 0.30).astype(np.uint8)
        assert analyze_shop_frame(dark, daily_anchor_y=83)["shop_verified"] is False
        assert confirmation(dark) is None


def test_small_native_render_noise_keeps_known_currency_and_prices():
    frame = _frame()
    noise = np.random.default_rng(20261006).normal(0, 2, frame.shape)
    noisy = np.clip(frame.astype(float) + noise, 0, 255).astype(np.uint8)
    items = _by_slot(noisy)
    assert [(items[slot]["currency"], items[slot]["price"]) for slot in range(6)] == [
        ("free", 0),
        ("gold", 500),
        ("gold", 1000),
        ("gold", 1500),
        ("gold", 2000),
        ("gems", 100),
    ]


@pytest.mark.parametrize(
    "bad",
    [
        None,
        np.zeros((632, 419, 3), dtype=np.uint8),
        np.zeros((633, 419, 3), dtype=np.float32),
        np.zeros((633, 419), dtype=np.uint8),
    ],
)
def test_uncalibrated_frames_fail_closed(bad):
    assert analyze_shop_frame(bad)["valid"] is False
    assert confirmation(bad) is None
    assert read_gold_balance(bad) is None
    assert reward_state(bad) is None
    assert insufficient_gold(bad) is False


@pytest.mark.parametrize(
    "name",
    [
        "shop_offers_top",
        "shop_offers_middle",
        "shop_offers_bottom",
        "shop_resources_top",
        "shop_resources_middle",
        "shop_resources_bottom",
        "shop_weekly",
        "classic_restored_lobby",
        "random_deck_confirmation",
        "spectate_exit_confirm",
        "daily_gift_info",
    ],
)
def test_other_real_pages_cannot_authorize_a_daily_slot_or_confirmation(name):
    frame = cv2.imread(str(FIXTURES / "cn_pages" / f"{name}.png"))
    assert frame is not None
    observed = analyze_shop_frame(frame)
    assert observed["daily_header"] is None
    assert all(item["slot"] is None for item in observed["visible_items"])
    assert confirmation(frame) is None
    assert reward_state(frame) is None
