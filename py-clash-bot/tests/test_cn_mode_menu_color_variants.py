"""Real blue and purple drawers retain two-cue and Classic-row safeguards."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from pyclashbot.bot.coords import CN_PAGE_ROIS
from pyclashbot.detection.cn_page_navigation import cn_classic_mode_point, cn_navigation_step

FIXTURES = Path(__file__).with_name("fixtures") / "cn_pages"


def frame(name):
    source = cv2.imread(str(FIXTURES / name))
    assert source is not None, name
    return source


@pytest.mark.parametrize("name", ["game_modes_top.png", "game_modes_blue_top.png"])
@pytest.mark.parametrize("offset", [-10, 0, 10])
def test_observed_drawer_palettes_locate_the_fresh_arrow(name, offset):
    source = frame(name)
    shifted = cv2.warpAffine(source, np.asarray([[1, 0, 0], [0, 1, offset]], dtype=np.float32), (419, 633))
    step = cn_navigation_step(shifted)
    assert step is not None and step.page == "game_modes" and step.route == "mode_arrow"
    assert step.target == (209, 100 + offset) and len(step.scores) == 2


@pytest.mark.parametrize("factor", [0.0, 0.35, 0.65, 0.8, 0.9, 0.94])
def test_blue_drawer_dimmed_by_an_unknown_overlay_never_authorizes_input(factor):
    source = frame("game_modes_blue_top.png")
    assert cn_navigation_step((source * factor).astype(np.uint8)) is None


@pytest.mark.parametrize("missing_cue", ["mode_title_search", "mode_arrow"])
def test_blue_drawer_requires_both_independent_regions(missing_cue):
    source = frame("game_modes_blue_top.png")
    x1, y1, x2, y2 = CN_PAGE_ROIS[missing_cue]
    source[y1:y2, x1:x2] = 0
    assert cn_navigation_step(source) is None
    assert cn_classic_mode_point(source) is None


def test_real_blue_drawer_without_classic_row_cannot_authorize_a_mode_selection():
    source = frame("game_modes_blue_top.png")
    step = cn_navigation_step(source)
    assert step is not None
    assert step.page == "game_modes"
    assert cn_classic_mode_point(source) is None
