"""Purchased daily-shop pages return safely without borrowing modal backgrounds."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from pyclashbot.bot.coords import CN_PAGE_RETURN_COORDS, CN_PAGE_ROIS
from pyclashbot.detection import cn_page_navigation as page_module
from pyclashbot.detection.cn_page_navigation import cn_navigation_step, learned_pages

FIXTURES = Path(__file__).with_name("fixtures")


def _frame(name):
    source = cv2.imread(str(FIXTURES / name))
    assert source is not None, name
    assert source.shape == (633, 419, 3)
    return source


def test_purchased_daily_shop_returns_by_the_named_battle_tab():
    source = _frame("cn_pages/daily_shop_purchased_return.png")
    broad_page = next(page for page in learned_pages() if page["name"] == "daily_shop_return")
    recorded = page_module._page_step(source, broad_page)
    assert recorded is not None and recorded.page == "daily_shop_return"
    assert recorded.route == "shop" and recorded.target == CN_PAGE_RETURN_COORDS["shop"] == (243, 601)
    assert len(recorded.scores) == 2

    step = cn_navigation_step(source)
    assert step is not None and step.route == "shop" and step.target is not None
    x1, y1, x2, y2 = CN_PAGE_ROIS["collection_nav_battle"]
    assert x1 <= step.target[0] < x2 and y1 <= step.target[1] < y2


@pytest.mark.parametrize("roi", ["shop_category_header", "shop_label"])
def test_daily_shop_return_requires_both_independent_cues(roi):
    source = _frame("cn_pages/daily_shop_purchased_return.png")
    x1, y1, x2, y2 = CN_PAGE_ROIS[roi]
    source[y1:y2, x1:x2] = 0
    assert cn_navigation_step(source) is None


def test_daily_shop_dimmed_under_an_unknown_overlay_authorizes_no_navigation():
    source = _frame("cn_pages/daily_shop_purchased_return.png")
    assert cn_navigation_step((source * 0.9).astype(np.uint8)) is None


@pytest.mark.parametrize("name", ["live-free-open", "live-gold-confirm", "live-gold-wide-confirm", "live-gem-confirm"])
def test_daily_purchase_modals_do_not_authorize_the_broad_shop_return(name):
    source = _frame(f"cn_shop_daily/{name}.png")
    broad_page = next(page for page in learned_pages() if page["name"] == "daily_shop_return")
    assert page_module._page_step(source, broad_page) is None
    step = cn_navigation_step(source)
    assert step is None or step.route != "shop"
