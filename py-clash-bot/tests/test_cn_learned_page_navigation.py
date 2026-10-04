"""Observed pages recover by one safe input, while battle/rewards stay untouched."""

from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from pyclashbot.bot import nav
from pyclashbot.bot.coords import CN_PAGE_ROIS
from pyclashbot.bot.state_detect import check_if_on_cn_learned_page
from pyclashbot.detection import cn_page_navigation as page_module
from pyclashbot.detection.cn_daily_gift import daily_gift_action
from pyclashbot.detection.cn_page_navigation import cn_game_exit_cancel, cn_navigation_step, learned_pages

FIXTURES = Path(__file__).with_name("fixtures")


class Logger:
    def change_status(self, status):
        pass

    def log(self, message):
        pass


def frame(name):
    source = cv2.imread(str(FIXTURES / name))
    assert source is not None, name
    return source


@pytest.mark.parametrize("page", learned_pages(), ids=lambda page: page["name"])
def test_every_saved_page_recovers_by_its_recorded_route(page):
    for name in [page.get("fixture_source", page["source"]), *page.get("variants", [])]:
        source = frame(f"cn_pages/{name}")
        step = cn_navigation_step(source)
        assert step is not None and step.route == page["route"], name
        assert len(step.scores) >= 2


@pytest.mark.parametrize("page", learned_pages(), ids=lambda page: page["name"])
def test_every_saved_page_dimmed_under_an_unrecognized_overlay_authorizes_no_navigation(page):
    source = frame(f"cn_pages/{page.get('fixture_source', page['source'])}")
    assert cn_navigation_step((source * 0.9).astype(np.uint8)) is None


@pytest.mark.parametrize(
    "name",
    ["collection_badges", "collection_card_forms", "collection_emotes", "collection_mastery", "collection_tower_skins"],
)
def test_observed_collection_categories_and_scroll_return_to_battle(name):
    step = cn_navigation_step(frame(f"cn_pages/{name}.png"))
    assert step is not None and step.page == name
    assert step.route == "collection"
    assert step.target is not None
    assert 235 <= step.target[0] <= 250 and 595 <= step.target[1] <= 610
    assert len(step.scores) == 3


def test_actual_second_error_survives_scrolled_away_category_header():
    source = frame("cn_pages/report_badges_scrolled.png")
    step = cn_navigation_step(source)
    assert step is not None and step.page == "collection_scrolled"
    assert step.route == "collection" and len(step.scores) == 2
    assert check_if_on_cn_learned_page(SimpleNamespace(screenshot=lambda: source))


@pytest.mark.parametrize("name", ["elite_info", "elite_gameplay_info"])
def test_observed_elite_dialog_returns_by_close_button(name):
    step = cn_navigation_step(frame(f"cn_pages/{name}.png"))
    assert step is not None and step.route == "elite_close" and step.target == (358, 62)


@pytest.mark.parametrize("offset", [-10, 0, 10])
def test_modes_return_arrow_is_located_on_same_fresh_frame(offset):
    source = frame("cn_pages/game_modes_top.png")
    shifted = cv2.warpAffine(source, np.asarray([[1, 0, 0], [0, 1, offset]], dtype=np.float32), (419, 633))
    step = cn_navigation_step(shifted)
    assert step is not None and step.page == "game_modes"
    assert step.target == (209, 100 + offset)


@pytest.mark.parametrize(
    "name",
    [
        "cn_random_mastery/mastery_locked.png",
        "cn_random_mastery/mastery_reward_coin.png",
        "cn_random_mastery/late_post_battle_reward.png",
        "cn_567/classic1v1_lobby.png",
        "cn_567/classic2v2_lobby.png",
        "cn_567/classic_loss.png",
        "cn_results/win_two_zero.png",
        "cn_results/loss_with_blue_crown.png",
        "cn_daily_gift/daily_gift_choice_20261004.png",
        "cn_battle_cues/real_enemies_at_friendly_tower.png",
        "cn_battle_cues/empty_lanes.png",
        "cn_random_hand/live_hand_0.png",
        "cn_random_hand/live_hand_1.png",
        "cn_random_hand/live_hand_2.png",
    ],
)
def test_battle_result_reward_and_other_modal_frames_do_not_trigger_navigation(name):
    assert cn_navigation_step(frame(name)) is None


@pytest.mark.parametrize(
    "path",
    sorted((FIXTURES / "cn_battle_cues").glob("*.png")) + sorted((FIXTURES / "cn_random_hand").glob("*.png")),
    ids=lambda path: f"{path.parent.name}/{path.stem}",
)
def test_existing_real_battle_corpus_never_returns_a_navigation_action(path):
    assert cn_navigation_step(cv2.imread(str(path))) is None
    assert cn_game_exit_cancel(cv2.imread(str(path))) is None


def test_small_game_exit_detector_cancels_without_consulting_other_page_routes(monkeypatch):
    exit_frame = frame("cn_pages/news_list.png")
    step = cn_game_exit_cancel(exit_frame)
    assert step is not None and step.route == "exit_game_cancel" and step.target == (143, 392)
    monkeypatch.setattr(page_module, "cn_navigation_step", lambda source: pytest.fail("Do not scan the full atlas"))
    assert cn_game_exit_cancel(exit_frame) == step
    assert cn_game_exit_cancel(frame("cn_pages/spectate_exit_confirm.png")) is None


def test_manifest_cannot_redirect_game_exit_cancel_to_the_confirmation_button(monkeypatch):
    page = dict(next(page for page in learned_pages() if page["route"] == "exit_game_cancel"))
    page["target_cue"] = 3
    monkeypatch.setattr(page_module, "learned_pages", lambda: (page,))
    assert cn_game_exit_cancel(frame("cn_pages/news_list.png")) is None


def test_game_exit_dialog_cancel_is_independent_of_an_active_battle_background():
    source = frame("cn_random_hand/live_hand_0.png")
    dialog = frame("cn_pages/news_list.png")
    source[193:451, 47:371] = dialog[193:451, 47:371]
    step = cn_game_exit_cancel(source)
    assert step is not None and step.target == (143, 392)


def test_legacy_owned_mastery_detail_remains_a_recognized_chrome_without_claim_input():
    source = frame("cn_random_mastery/mastery_detail.png")
    step = cn_navigation_step(source)
    assert step is not None and step.route == "card_mastery_close" and step.target == (354, 87)


@pytest.mark.parametrize(
    "name",
    [
        "cn_pages/random_deck_confirmation.png",
        "cn_random_mastery/deck_confirm.png",
        "cn_pages/delete_deck_confirmation.png",
    ],
)
def test_unowned_deck_confirmation_cancel_is_opt_in_and_never_an_exit_game_dialog(name, monkeypatch):
    source = frame(name)
    step = cn_navigation_step(source)
    assert step is not None and step.unowned_only and step.target == (143, 392)
    assert cn_game_exit_cancel(source) is None
    clicks = []
    device = SimpleNamespace(screenshot=lambda: source, click=lambda *point: clicks.append(point))
    monkeypatch.setattr(nav.time, "sleep", lambda seconds: None)
    assert nav.recover_cn_page_once(device, Logger()) is None
    assert clicks == []
    assert nav.recover_cn_page_once(device, Logger(), allow_unowned_confirmation=True) == step.page
    assert clicks == [(143, 392)]


def test_hero_card_chrome_does_not_bind_level_digits_or_progress_value():
    source = frame("cn_pages/hero_information.png")
    source[64:77, 240:254] = 0
    source[85:108, 240:280] = 0
    step = cn_navigation_step(source)
    assert step is not None and step.route == "hero_info_close" and step.target == (351, 30)


@pytest.mark.parametrize("name", ["locked_tower_card_menu", "tower_video", "tower_stats", "tower_description"])
def test_tower_level_color_variants_use_glyph_shape_and_a_bright_exact_close(name):
    source = frame(f"cn_pages/{name}.png")
    step = cn_navigation_step(source)
    assert step is not None and step.route == "tower_info_close" and step.target == (354, 40)
    assert cn_navigation_step((source * 0.9).astype(np.uint8)) is None


def test_unowned_hero_without_progress_bar_has_the_same_safe_close():
    source = frame("cn_pages/locked_hero_information.png")
    step = cn_navigation_step(source)
    assert step is not None and step.route == "hero_info_close" and step.target == (351, 30)


@pytest.mark.parametrize("name", ["collection_filter_options", "awakening_filter_dialog", "awakening_filter_restored"])
def test_card_collection_filter_does_not_bind_checkbox_selection(name):
    step = cn_navigation_step(frame(f"cn_pages/{name}.png"))
    assert step is not None and step.page == "collection_filter_options" and step.target == (25, 418)


@pytest.mark.parametrize("name", ["daily_activity", "daily_activity_returned", "daily_activity_help_closed"])
def test_daily_activity_returns_without_touching_claimed_rewards_or_the_shop(name):
    source = frame(f"cn_pages/{name}.png")
    step = cn_navigation_step(source)
    assert step is not None and step.route == "daily_activity_confirm" and step.target == (210, 602)
    assert cn_navigation_step((source * 0.9).astype(np.uint8)) is None


@pytest.mark.parametrize("name", ["daily_activity_help", "daily_activity_help_second", "daily_activity_special_piece"])
def test_daily_activity_help_pages_use_the_close_control(name):
    step = cn_navigation_step(frame(f"cn_pages/{name}.png"))
    assert step is not None and step.route == "daily_activity_help_close" and step.target == (357, 57)


@pytest.mark.parametrize(
    ("name", "target"),
    [
        ("crl_support_shop_raw", (155, 595)),
        ("crl_support_shop_native", (155, 595)),
        ("crl_shop_bottom_native", (155, 595)),
        ("blue_backpack", (360, 117)),
        ("awakening_machine_info_bottom", (350, 124)),
        ("awakening_prizes_end", (350, 124)),
        ("awakening_records_bottom", (350, 124)),
        ("awakening_prize_detail", (364, 214)),
    ],
)
def test_event_shop_and_machine_pages_only_return_or_close_after_two_cues(name, target, monkeypatch):
    source = frame(f"cn_pages/{name}.png")
    step = cn_navigation_step(source)
    assert step is not None and step.target == target
    clicks = []
    device = SimpleNamespace(screenshot=lambda: source, click=lambda *point: clicks.append(point))
    monkeypatch.setattr(nav.time, "sleep", lambda seconds: None)
    assert nav.recover_cn_page_once(device, Logger()) == step.page
    assert clicks == [target]
    assert cn_navigation_step((source * 0.9).astype(np.uint8)) is None


@pytest.mark.parametrize("name", ["crl_support_shop", "awakening_machine", "awakening_machine_item_information"])
def test_event_title_without_its_bright_return_control_does_not_authorize_input(name):
    page = next(page for page in learned_pages() if page["name"] == name)
    source = frame(f"cn_pages/{page['source']}")
    cue = page["cues"][page["target_cue"]]
    x1, y1, x2, y2 = CN_PAGE_ROIS[cue["roi"]]
    source[y1:y2, x1:x2] = 0
    assert cn_navigation_step(source) is None


def test_already_received_daily_gift_returns_without_requesting_another_choice():
    source = frame("cn_pages/purple_cards_news.png")
    assert daily_gift_action(source) is None
    step = cn_navigation_step(source)
    assert step is not None and step.route == "daily_gift_received_close" and step.target == (210, 607)
    x1, y1, x2, y2 = CN_PAGE_ROIS["daily_gift_received_body"]
    source[y1:y2, x1:x2] = 0
    assert cn_navigation_step(source) is None


def test_daily_gift_probability_tooltip_closes_before_the_received_parent_page():
    source = frame("cn_pages/daily_gift_info.png")
    assert daily_gift_action(source) is None
    step = cn_navigation_step(source)
    assert step is not None and step.route == "daily_gift_info_toggle" and step.target == (352, 67)
    parent = cn_navigation_step(frame("cn_pages/daily_gift_info_closed.png"))
    assert parent is not None and parent.route == "daily_gift_received_close"


@pytest.mark.parametrize(
    "name", ["news_list_scrolled_native", "news_article_return_native", "news_article_bottom_native"]
)
def test_native_news_scrolling_and_pointer_over_the_footer_preserve_the_verified_return_center(name):
    step = cn_navigation_step(frame(f"cn_pages/{name}.png"))
    assert step is not None and step.route == "news_close" and step.target == (210, 601)


@pytest.mark.parametrize("name", ["news_esports_native", "news_esports_live_native"])
def test_native_sdk_live_player_closes_only_with_its_title_and_bright_close_control(name):
    step = cn_navigation_step(frame(f"cn_pages/{name}.png"))
    assert step is not None and step.route == "news_video_close" and step.target == (381, 64)


@pytest.mark.parametrize("factor", [0.0, 0.35, 0.65, 0.8, 0.88, 0.9, 0.94])
def test_background_dimmed_behind_an_unknown_dialog_is_not_a_navigation_page(factor):
    source = frame("cn_pages/collection_badges.png")
    assert cn_navigation_step((source * factor).astype(np.uint8)) is None


@pytest.mark.parametrize("name", ["shop_offers_top", "social_home", "game_modes_top"])
def test_shallow_global_dimming_does_not_authorize_a_return_input(name):
    source = frame(f"cn_pages/{name}.png")
    assert cn_navigation_step((source * 0.9).astype(np.uint8)) is None


@pytest.mark.parametrize("offset", [3, 5])
def test_small_normal_additive_color_drift_preserves_observed_collection(offset):
    source = frame("cn_pages/collection_badges.png")
    adjusted = np.clip(source.astype(np.int16) + offset, 0, 255).astype(np.uint8)
    assert cn_navigation_step(adjusted) is not None


@pytest.mark.parametrize("size", [3, 5, 8])
def test_corrupt_small_crops_cannot_recognize_a_real_battle(size, monkeypatch):
    source = frame("cn_random_hand/live_hand_0.png")
    template = page_module._template
    rois = {
        cue["template"]: cue
        for page in learned_pages()
        if page["name"] == "collection_scrolled"
        for cue in page["cues"]
    }

    def damaged(name):
        if name not in rois:
            return template(name)
        cue = rois[name]
        x1, y1, _, _ = CN_PAGE_ROIS[cue.get("search_roi", cue["roi"])]
        return source[y1 : y1 + size, x1 : x1 + size]

    monkeypatch.setattr(page_module, "_template", damaged)
    assert cn_navigation_step(source) is None


def test_one_similar_bottom_icon_without_second_independent_cue_is_rejected():
    source = frame("cn_pages/collection_badges.png")
    candidate = np.zeros_like(source)
    candidate[571:633, 75:206] = source[571:633, 75:206]
    assert cn_navigation_step(candidate) is None


@pytest.mark.parametrize("source", [None, np.zeros((632, 419, 3), np.uint8), np.zeros((633, 419, 3), float)])
def test_wrong_or_missing_screenshot_is_rejected(source):
    assert cn_navigation_step(source) is None


def test_recovery_issues_exactly_one_verified_step_and_no_blind_followup(monkeypatch):
    source = frame("cn_pages/report_badges_scrolled.png")
    clicks = []
    device = SimpleNamespace(screenshot=lambda: source, click=lambda *point: clicks.append(point))
    logger = Logger()
    monkeypatch.setattr(nav.time, "sleep", lambda seconds: None)
    assert nav.recover_cn_page_once(device, logger) == "collection_scrolled"
    step = cn_navigation_step(source)
    assert step is not None
    assert clicks == [step.target]
    device.screenshot = lambda: np.zeros_like(source)
    assert nav.recover_cn_page_once(device, logger) is None
    assert len(clicks) == 1


@pytest.mark.parametrize("name", ["spectate", "spectate_exit_confirm"])
def test_spectator_exit_requires_explicit_no_pending_battle_guard(name, monkeypatch):
    source = frame(f"cn_pages/{name}.png")
    step = cn_navigation_step(source)
    assert step is not None and step.idle_only
    clicks, keys = [], []
    device = SimpleNamespace(screenshot=lambda: source, click=lambda *point: clicks.append(point), adb=keys.append)
    monkeypatch.setattr(nav.time, "sleep", lambda seconds: None)
    assert nav.recover_cn_page_once(device, Logger()) is None
    assert clicks == [] and keys == []
    assert nav.recover_cn_page_once(device, Logger(), allow_spectator_exit=True) == name
    if name == "spectate":
        assert clicks == [] and keys == ["shell input keyevent 4"]
    else:
        assert clicks == [(276, 392)] and keys == []
