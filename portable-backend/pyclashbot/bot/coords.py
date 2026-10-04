# --- Clash main / global ---
CLASH_MAIN_DEADSPACE_COORD = (35, 500)

# --- Nav ---
CLASH_MAIN_OPTIONS_BURGER_BUTTON = (390, 62)
BATTLE_LOG_BUTTON = (241, 43)
CARD_PAGE_ICON_FROM_CLASH_MAIN = (108, 598)
CARD_PAGE_ICON_FROM_CARD_PAGE = (147, 598)
CARD_PAGE_EXIT_BUTTON_COORDS = (248, 603)
OK_BUTTON_COORDS_IN_TROPHY_REWARD_PAGE = (209, 599)
REWARD_LEFT_CHOICE_COORD = (112, 363)
REWARD_RIGHT_CHOICE_COORD = (318, 375)
DECK_TABS_REGION = (0, 80, 416, 146)
DECKS_PAGE_BUTTON_COORDS = (125, 60)

# --- Fight ---
CLOSE_BATTLE_LOG_BUTTON = (365, 72)
HAND_CARDS_COORDS = [
    (142, 561),
    (210, 563),
    (272, 561),
    (341, 563),
]
# Measured against a 419x633 Tencent-client 1v1 frame. The first point was
# validated with a deployed Cannon; the others are open tiles on the same side.
CN_FRIENDLY_DROP_POINTS: tuple[tuple[int, int], ...] = (
    (105, 325),
    (310, 325),
    (135, 350),
    (285, 350),
)
# Small mirrored placement set for the 4.0 double-air 567 policy, 419x633.
CN_567_POINTS = {
    "front": {"left": (115, 290), "right": (303, 290)},
    "defend": {"left": (137, 349), "right": (281, 349)},
    "deep": {"left": (165, 425), "right": (253, 425)},
    "support": {"left": (75, 355), "right": (343, 355)},
    "back": {"left": (165, 460), "right": (253, 460)},
}
CN_CLASSIC_MODE_ICON_ROI = (296, 478, 334, 519)
CN_567_ALLY_ROI = (45, 190, 374, 470)
# Conservative interior of the observed 2.5-5 tile rocket annulus. Arena tiles
# are about 17-18 px; never use the melee/dead-zone placement as air coverage.
CN_567_ROCKET_DISTANCE_BAND = (50, 80)
# Lane-aligned rear positions for a confirmed evolved Bomber. Both avoid the
# princess tower footprint. The deeper point also keeps support behind a tank.
CN_567_BOMBER_LINE_POINTS = {
    "front": {"left": (115, 340), "right": (303, 340)},
    "back": {"left": (115, 445), "right": (303, 445)},
}
CN_DECK_PREVIEW = (100, 490)
CN_DECK_CLOSE = (210, 46)
CN_567_DECK_ROIS = tuple((x, y, x + 60, y + 66) for y in (162, 306) for x in (49, 138, 225, 311))
# Tencent 2.6 Hog cycle role-specific placements, calibrated on the same arena.
CN_HOG_BRIDGE_POINTS = {"left": (113, 285), "right": (303, 285)}
CN_HOG_SUPPORT_POINTS = {"left": (113, 300), "right": (303, 300)}
CN_HOG_CANNON_POINTS = {"left": (173, 330), "right": (245, 330)}
# V5 candidate: observed Cannon placement ring is about 90 px in the fixed
# Tencent frame. Apply coverage only after the interception window; keep the
# established early central lure positions. Enemy markers need a small ground
# projection because the existing reader returns plaque center plus 16 px.
CN_HOG_CANNON_COVERAGE_RADIUS = 90
CN_HOG_CANNON_LATE_PRESSURE_Y = 350
CN_HOG_CANNON_TARGET_OFFSET_Y = 10
CN_HOG_MUSKETEER_POINTS = {"left": (69, 393), "right": (348, 393)}
CN_HOG_STALL_POINTS = {"left": (137, 349), "right": (282, 349)}
CN_HOG_KITE_POINTS = {"left": (232, 348), "right": (187, 348)}
CN_HOG_BACK_POINTS = {"left": (169, 467), "right": (250, 467)}
CN_HOG_LANE_X = {"left": 115, "right": 303}
CN_HOG_LOG_Y_LIMITS = (315, 465)
CN_HOG_ELIXIR_X_COORDS = (149, 165, 188, 212, 240, 262, 287, 314, 339, 364)
CN_HOG_ELIXIR_Y = 613
CN_RESULT_LOSS_YELLOW_ROI = (165, 52, 245, 86)
CN_BATTLE_CLOCK_ROI = (349, 16, 412, 39)
CN_REWARD_BACKGROUND_ROI = (20, 25, 395, 110)
# Four-star Tencent reward frames: pink sky above a teal checkerboard floor.
# Both left and right samples are required to avoid animated cards and HUD art.
CN_FOUR_STAR_REWARD_BG_POINTS = ((35, 100), (380, 100), (35, 500), (380, 500))
CN_REWARD_FLOOR_ROI = (0, 460, 419, 615)
CN_REWARD_FLOOR_SEARCH_ROI = (0, 380, 419, 580)
CN_REWARD_UNOPENED_CHEST_ROI = (127, 260, 299, 392)
CN_REWARD_UNOPENED_CHEST_SEARCH_ROI = (80, 220, 340, 445)
CN_REWARD_PURPLE_FLOOR_SEARCH_ROI = (0, 380, 419, 620)
CN_REWARD_PUZZLE_TITLE_ROI = (150, 140, 270, 210)
CN_REWARD_UNLOCKED_ROI = (145, 370, 270, 425)
CN_HOG_DEFENSE_ROI = (43, 230, 377, 480)
CN_HOG_FAR_WARNING_ROI = (43, 170, 377, 270)
CN_HOG_EARLY_AIR_ROI = (43, 185, 377, 270)
CN_HOG_EARLY_HOG_ROI = (43, 175, 377, 305)
CN_HOG_LANE_SPLIT_X = 209
CN_HOG_ENEMY_TOWER_HEALTH_ROIS = {"left": (86, 81, 154, 101), "right": (274, 81, 342, 101)}
# Narrow pink-fill rows inside the visible purple tower health troughs.
CN_HOG_ENEMY_TOWER_FILL_ROIS = {"left": (100, 94, 151, 98), "right": (288, 94, 339, 98)}
# Two clean blue health-bar rows on the friendly princess towers.
CN_HOG_OWN_TOWER_FILL_ROIS = {"left": (100, 394, 151, 396), "right": (288, 394, 339, 396)}
CN_HOG_ENEMY_PRINCESS_TOWER_POINTS = {"left": (115, 130), "right": (303, 130)}
# Keep the setup Musketeer behind either lane's Cannon so a single splash
# attack cannot hit both 36 pixels apart (pilot 10, battle 5).
CN_HOG_DUAL_LANE_MUSKETEER_POINT = (209, 392)
CN_POST_WIN_REWARD_TAP = (209, 329)
CN_HOG_ELITE_ABILITY_ROI = (325, 450, 382, 504)
CN_HOG_ELITE_ABILITY_TAP = (352, 477)
CN_HOG_DEEP_MUSKETEER_POINTS = {"left": (152, 431), "right": (267, 431)}
CN_HOG_CENTRAL_MUSKETEER_POINTS = {"left": (178, 368), "right": (241, 368)}
CN_HOG_BRIDGE_MUSKETEER_POINTS = {"left": (137, 349), "right": (282, 349)}
CN_HOG_DEEP_STALL_POINTS = {"left": (166, 426), "right": (253, 426)}
# Relative cheap-card placement after enemies approach our towers. These
# conservative footprint boxes exclude both princess towers and the king
# tower; nearby open tiles remain legal whether a princess tower is intact or
# destroyed. Coordinates stay inside the visible friendly arena.
CN_HOG_STALL_TARGET_Y_OFFSET = 20
CN_HOG_STALL_TARGET_MIN_Y = 350
CN_HOG_STALL_SAFE_BOUNDS = (65, 300, 354, 466)
CN_HOG_STALL_TOWER_MARGIN = 12
CN_HOG_FRIENDLY_TOWER_BOXES = {
    "left": (92, 356, 145, 425),
    "right": (278, 356, 331, 425),
    "king": (178, 408, 240, 482),
}
CN_HOG_DEEP_KITE_POINTS = {"left": (183, 404), "right": (235, 404)}
CN_HOG_FIREBALL_GROUND_OFFSET_Y = 10
CN_HOG_FIREBALL_MAX_Y = 477
CLOSE_THIS_CHALLENGE_PAGE_BUTTON = (27, 22)
QUICKMATCH_BUTTON_COORD = (274, 353)  # coord of the quickmatch button after you click the battle button
EMOTE_BUTTON_COORD = (67, 521)
EMOTE_ICON_COORDS = [
    (124, 419),
    (182, 420),
    (255, 411),
    (312, 423),
    (133, 471),
    (188, 472),
    (243, 469),
    (308, 470),
]

# --- Deck ---
# Tencent random-deck/mastery flow, measured on live 419x633 frames.
CN_RANDOM_DECK_OPTIONS = (55, 108)
CN_RANDOM_WAND = (132, 191)
CN_RANDOM_DECK_LINK = (132, 349)
# Role-specific random-deck placements, fixed 419x633 friendly arena.
CN_RANDOM_POLICY_POINTS = {
    "back": {"left": (169, 467), "right": (250, 467)},
    "support": {"left": (69, 393), "right": (348, 393)},
    "support_front": {"left": (69, 335), "right": (348, 335)},
    "push_support": {"left": (113, 315), "right": (303, 315)},
    "back_support": {"left": (113, 467), "right": (303, 467)},
    "intercept": {"left": (137, 349), "right": (282, 349)},
    "bridge": {"left": (113, 285), "right": (303, 285)},
    "building": {"left": (173, 330), "right": (245, 330)},
    "siege": {"left": (120, 311), "right": (298, 311)},
    "remote": {"left": (115, 145), "right": (303, 145)},
}
CN_RANDOM_CONFIRM = (275, 392)
CN_RANDOM_INTERCEPT_BOUNDS = (65, 295, 354, 466)
CN_RANDOM_INTERCEPT_OFFSET_Y = 18
CN_RANDOM_TOWER_MARGIN = 12
# Remote cards and crown-target spells use the current surviving attack object.
# The king point is used only when a caller supplies explicit king evidence.
CN_RANDOM_ENEMY_KING_POINT = (209, 81)
CN_RANDOM_BUILDING_COVERAGE = {
    "cannon": 90,
    "bomb_tower": 90,
    "tesla": 95,
    "inferno_tower": 105,
    "goblin_cage": 85,
    "tombstone": 80,
    "furnace": 80,
    "goblin_hut": 80,
    "barbarian_hut": 80,
}
CN_RANDOM_SUPPORT_Y_OFFSET = 30
CARD_MASTERY_REWARD_COORDS = ((200, 316), (200, 403), (200, 488))
CARD_MASTERY_DEADSPACE_COORD = (14, 278)
CARD_MASTERY_PROGRESS_ROI = (325, 425, 382, 456)
CN_RANDOM_MASTERY = (358, 442)
CN_RANDOM_DECK_TAB = (132, 67)
CN_RANDOM_MODAL_CLOSE = (356, 106)
CN_RANDOM_DETAIL_CLOSE = (354, 87)
CN_RANDOM_LOCKED_DETAIL_CLOSE = (354, 127)
CN_RANDOM_FIRST_MASTERY_CARD = (99, 167)
CN_RANDOM_MASTERY_SCROLL_START = (300, 425)
CN_RANDOM_MASTERY_SCROLL_END = (300, 335)
CN_RANDOM_MASTERY_SCROLL_MS = 1600
CN_RANDOM_DECK_ROIS = tuple((x, y, x + 52, y + 58) for y in (164, 309) for x in (52, 138, 224, 311))
CN_RANDOM_HAND_ROIS = tuple((x - 22, 533, x + 22, 584) for x in (142, 210, 272, 341))
CN_RANDOM_CONSUMED_SLOT_ROIS = tuple((x + 5, 547, x + 49, 577) for x in (115, 182, 249, 316))
CN_RANDOM_SPELL_POINTS = {"left": (115, 140), "right": (303, 140)}
CN_RANDOM_UI_ROIS = {
    "deck": (169, 97, 313, 126),
    "collection": (215, 48, 352, 85),
    "deck_menu": (100, 176, 161, 207),
    "deck_confirm": (169, 198, 248, 222),
    "mastery_list": (170, 96, 253, 121),
    "mastery_detail": (168, 120, 254, 147),
    "mastery_locked": (168, 159, 254, 186),
    "mastery_reward_continue": (194, 588, 230, 606),
    "mastery_reward_coin": (180, 137, 242, 165),
    "mastery_reward_background": (295, 265, 400, 380),
}
CN_RANDOM_MASTERY_LIST_ROI = (62, 125, 356, 462)
CN_RANDOM_MASTERY_COLUMNS = (99, 172, 246, 318)
CN_RANDOM_MASTERY_CLAIM_ROI = (65, 285, 354, 535)
CN_RANDOM_MASTERY_FOOTER_ROI = (68, 472, 331, 520)
CN_RANDOM_CLAIM_ALL_BUTTON_ROI = (170, 476, 249, 505)
CN_RANDOM_CLAIM_ALL = (209, 491)
CN_RANDOM_REWARD_CONTINUE = (209, 600)
CN_RANDOM_REWARD_AMOUNT_ROI = (140, 320, 280, 354)
CN_RANDOM_REWARD_QUANTITY_SEARCH_ROI = (133, 313, 287, 361)
CN_RANDOM_CARD_AVAILABLE_ROIS = tuple(
    (x, y, x + 20, y + 20) for x, y in ((133, 582), (199, 583), (266, 583), (334, 582))
)

DECK_OPTIONS_BUTTON_COORDS = (53, 106)
RANDOMIZE_DECK_BUTTON_COORDS = (125, 188)
RANDOMIZE_DECK_CONFIRM_BUTTON_COORDS = (280, 390)

# Unified deck-randomization flow (same buttons for Trophy Road / Classic 1v1 / 2v2).
# Randomizing a full deck pops a "replace deck?" confirm dialog; a partial deck does not.
DECK_PAGE_OPTIONS_BUTTON_COORDS = (57, 104)
RANDOMIZE_DECK_BUTTON_COORD = (117, 186)
CONFIRM_RANDOMIZE_DECK_BUTTON_COORD = (252, 388)

# --- Upgrade ---
UPGRADE_POINTS = [
    (53, 263),  # 1
    (140, 263),  # 2
    (225, 263),  # 3
    (312, 263),  # 4
    (52, 403),  # 5
    (139, 402),  # 6
    (225, 402),  # 7
    (311, 402),  # 8
]
FIRST_UPGRADE_BUTTON_COORD = (241, 542)
SECOND_UPGRADE_BUTTON_COORD = (241, 478)
DEADSPACE_COORD = (10, 323)
CLOSE_CARD_PAGE_COORD = (355, 238)
UPGRADE_PIXEL_TOLERANCE = 30
COIN_INSUFFICIENT_COORD = (359, 210)  # close button of gold popup
COIN_INSUFFICIENT_BGR = (49, 53, 254)
UPGRADE_RETURN_TO_MAIN_COORD_1 = (211, 607)
UPGRADE_RETURN_TO_MAIN_COORD_2 = (243, 600)
CARD_PAGE_OK_BUTTON_COORDS = (194, 597)
CHAMPION_UPGRADE_BUTTON_COORD = (236, 542)
PRINCESS_CARD_BUTTON_COORD = (322, 537)
PRINCESS_INFO_BUTTON_COORD_LOCATION_1 = (212, 607)
PRINCESS_UPGRADE_BUTTON_COORD_LOCATION_1 = (337, 309)
PRINCESS_UPGRADE_BUTTON_COORD_LOCATION_2 = (337, 518)
UPGRADE_PRINCESS_BUTTON_2_COORD = (243, 583)
CONFIRM_UPGRADE_PRINCESS_BUTTON_COORD = (225, 501)
PRINCESS_CARD_PAGE_OK_BUTTON_COORD = (209, 608)

# --- Card mastery ---
CARD_MASTERY_RETURN_TO_MAIN_COORD = (243, 600)
CARD_MASTERY_OPTIONS_COORD = (362, 444)
CARD_MASTERY_TAB_COORD = (99, 166)
CARD_MASTERY_COLLECT_COORD = (260, 420)

# --- Misc fight call sites ---
START_FIGHT_BUTTON_COORD = (203, 487)
QUICKMATCH_POPUP_BUTTON_COORD = (280, 350)
MAG_DUMP_CARD_COORDS = [
    (137, 559),
    (206, 559),
    (274, 599),
    (336, 555),
]
BATTLE_WAIT_DEADSPACE_COORD = (20, 200)

# --- Account switch ---
SWITCH_ACCOUNT_BUTTON_COORD = (221, 468)
ACCOUNT_SLOT_CLICK_COORDS: dict[int, tuple[int, int]] = {
    1: (253, 380),
    2: (251, 476),
    3: (252, 572),
}

# --- Bottom nav (tap targets in the y≈600 bar) ---
BOTTOM_NAV_SHOP_TAB_COORD = (30, 600)
BOTTOM_NAV_CARD_TAB_COORD = (100, 600)
BOTTOM_NAV_CARD_TAB_FROM_MAIN_COORD = (100, 606)  # slightly lower y on the main-page card click
BOTTOM_NAV_BATTLE_TAB_COORD = (170, 600)
BOTTOM_NAV_MAIN_TAB_FROM_SHOP_COORD = (240, 600)
BOTTOM_NAV_MAIN_TAB_FROM_CARD_COORD = (250, 600)
BOTTOM_NAV_CLAN_CHAT_TAB_COORD = (280, 600)
BOTTOM_NAV_SOCIAL_TAB_COORD = (310, 600)  # consolidated from 309/310/315 — see PR body
# In-clan-chat: exit deadspace + tap-target for re-opening Social from inside clan chat.
CLAN_CHAT_EXIT_DEADSPACE_COORD = (200, 600)
CLAN_CHAT_TO_SOCIAL_COORD = (219, 605)

# --- Clan voyage ---
# Close button on the clan voyage popup that can block the main menu.
CLAN_VOYAGE_CLOSE_BUTTON_COORDS = [210, 600]

# --- War page ---
# War sits as a tab inside the Social hub (top row, x=210 y=105).
WAR_TAB_FROM_SOCIAL_COORD = (210, 105)
# When leaving war page, the bottom-nav row has shifted positions vs. main —
# tap deadspace first, then the war-page bottom-nav tap target.
WAR_EXIT_DEADSPACE_COORD = (210, 600)
BOTTOM_NAV_MAIN_TAB_FROM_WAR_COORD = (180, 600)
BOTTOM_NAV_CARD_TAB_FROM_WAR_COORD = (110, 600)
BOTTOM_NAV_SHOP_TAB_FROM_WAR_COORD = (35, 600)
BOTTOM_NAV_CLAN_CHAT_TAB_FROM_WAR_COORD = (265, 600)

# Make-war-deck flow: click the empty deck slot, then "Random Deck", then exit.
MAKE_WAR_DECK_1 = (80, 520)
MAKE_WAR_DECK_2 = (165, 520)
MAKE_WAR_DECK_3 = (250, 520)
MAKE_WAR_DECK_4 = (240, 520)
MAKE_RANDOM_WAR_DECK_BUTTON = (265, 490)
EXIT_MAKE_WAR_DECK_PAGE = (205, 40)

# War battle start + post-battle OK
START_WAR_BATTLE_BUTTON_COORDS = (280, 415)
OK_AFTER_WAR_BATTLE_COMPLETE_BUTTON_COORD = (205, 570)
# Playfield drop region during a war battle (LTRB → (left, top, right, bottom))
WAR_BATTLE_PLAYFIELD_LTRB = (55, 256, 360, 470)
# Full-board drop region for random/clean plays (LTRB), measured from a fight frame.
# Sits inside the rl-bot PLAY_REGION normalization rect, so it does not affect coord norm.
PLAYABLE_PLAY_REGION_LTRB = (59, 67, 355, 467)
# Safe deadspace tap on the war page (used to dismiss the battle-confirm overlay).
WAR_DEADSPACE_COORD = (20, 330)

# War boot: the clan-war results popup ("Your Clan didn't finish!" / reward chest)
# that can cover the main menu and intercept navigation to the war page.
WAR_BOOT_REWARD_COORD = (221, 382)  # the reward-chest "OPEN" button
SKIP_WAR_BOOT_BUTTON_COORDS = (208, 601)  # the bottom OK / skip button
CLAN_WAR_FINAL_RESULTS_POPUP_OK_BUTTON = (210, 526)  # OK button on the clan-war final-results popup

# --- Shop / daily free offer ---
CONFIRM_COLLECT_DAILY_FREE_OFFER_BUTTON_COORDS = (210, 440)
CONFIRM_FREE_REWARD_PURCHASE_1 = (207, 396)  # green FREE! button on the confirmation popup
SHOP_PAGE_DEADSPACE_COORD = (10, 280)
PAGINATE_SHOP_PAGE_BUTTON = (65, 600)

# --- Clan chat ---
CLAN_CHAT_FEED_SUBCROP = (0, 60, 419, 500)
CLAN_CHAT_FOOTER_SUBCROP = (0, 470, 280, 600)
CLAN_CHAT_REQUEST_PICKER_SUBCROP = (0, 70, 419, 600)
CLAN_CHAT_REQUEST_CARD_CLICK_OFFSET = (48, -40)
MORE_CLAN_CHAT_CARD_OPTIONS_SUBCROP = (17, 99, 76, 161)
REVEAL_MORE_CLAN_CHAT_CARD_OPTIONS_BUTTON_COORD = (50, 125)

# --- Chinese daily gift choice (419 x 633 client, 2026-10-04 evidence) ---
CN_DAILY_GIFT_COSMETIC_CHOICE = (210, 434)
CN_DAILY_GIFT_TITLE_ROI = (75, 35, 325, 83)
CN_DAILY_GIFT_RICH_LABEL_ROI = (135, 170, 285, 215)
CN_DAILY_GIFT_LUCK_LABEL_ROI = (135, 307, 285, 352)
CN_DAILY_GIFT_COSMETIC_LABEL_ROI = (135, 440, 285, 484)
CN_DAILY_GIFT_COSMETIC_PANEL_ROI = (103, 382, 311, 485)

# --- Fight: champion ability ---
CHAMPION_ABILITY_DISMISS_COORD = (330, 460)

# --- Observed Tencent pages: one verified return action per fresh screenshot ---
CN_PAGE_BATTLE_TAB_FROM_COLLECTION = (243, 601)
CN_PAGE_BATTLE_TAB_FROM_SHOP = (243, 601)
CN_PAGE_BATTLE_TAB_FROM_SOCIAL = (174, 601)
CN_PAGE_BATTLE_TAB_FROM_EVENTS = (174, 601)
CN_PAGE_TOP_RIGHT_CLOSE = (387, 67)
CN_PAGE_MODAL_RIGHT_CLOSE = (365, 72)
CN_PAGE_TOP_LEFT_BACK = (29, 30)
CN_PAGE_CENTER_TOP_CLOSE = (210, 46)
CN_PAGE_ELITE_CLOSE = (358, 62)
CN_PAGE_MODE_ARROW = (210, 100)
CN_PAGE_LEADERBOARD_CLOSE = (364, 67)
CN_PAGE_BURGER_DISMISS = (25, 418)
CN_PAGE_PROFILE_CLOSE = (360, 62)
CN_PAGE_MEMBER_DISMISS = (25, 418)
CN_PAGE_SPECTATE_CONFIRM = (276, 392)
CN_PAGE_KEYEVENTS = {"android_back": 4, "profile_editor_back": 4, "duel_deck_back": 4}
CN_PAGE_TOURNAMENTS_BACK = (22, 16)
CN_PAGE_TOURNAMENT_HELP_CLOSE = (366, 113)
CN_PAGE_SETTINGS_CLOSE = (351, 133)
CN_PAGE_MORE_SETTINGS_CLOSE = (353, 173)
CN_PAGE_SHOP_INFO_CLOSE = (365, 159)
CN_PAGE_MARKET_CLOSE = (210, 602)
CN_PAGE_EMOTE_INFO_CLOSE = (365, 214)
CN_PAGE_CLAN_INTRO_CONFIRM = (210, 610)
CN_PAGE_CLAN_SEARCH_CLOSE = (351, 82)
CN_PAGE_CLAN_ADVANCED_CLOSE = (353, 193)
CN_PAGE_CLAN_EMBLEM_CLOSE = (351, 117)
CN_PAGE_FRIEND_CLOSE = (351, 86)
CN_PAGE_GAME_EXIT_CANCEL = (143, 392)
CN_PAGE_NEWS_CLOSE = (210, 601)
CN_PAGE_CARD_INFO_CLOSE = (351, 183)
CN_PAGE_CARD_MASTERY_CLOSE = (354, 87)
CN_PAGE_CARD_EDITOR_CONFIRM = (210, 609)
CN_PAGE_CARD_SKIN_CLOSE = (209, 154)
CN_PAGE_HERO_INFO_CLOSE = (351, 30)
CN_PAGE_DECK_CONFIRM_CANCEL = (143, 392)
CN_PAGE_TOWER_INFO_CLOSE = (354, 40)
CN_PAGE_AWAKENING_CLOSE = (356, 58)
CN_PAGE_PASS_CONFIRM = (210, 602)
CN_PAGE_DAILY_ACTIVITY_CONFIRM = (210, 601)
CN_PAGE_DAILY_ACTIVITY_HELP_CLOSE = (357, 56)
CN_PAGE_CUSTOM_BUNDLE_CLOSE = (359, 159)
CN_PAGE_CUSTOM_BUNDLE_CHOICES_CLOSE = (357, 146)
CN_PAGE_CUSTOM_BUNDLE_HELP_CLOSE = (364, 31)
CN_PAGE_CRL_RETURN = (155, 594)
CN_PAGE_CRL_RULES_CLOSE = (369, 119)
CN_PAGE_AWAKENING_MACHINE_CLOSE = (360, 116)
CN_PAGE_AWAKENING_MACHINE_SHEET_CLOSE = (350, 124)
CN_PAGE_RED_EVENT_CLOSE = (366, 21)
CN_PAGE_RED_EVENT_PRIZES_CLOSE = (348, 75)
CN_PAGE_GOBLIN_PREVIEW_CLOSE = (210, 616)
CN_PAGE_CROWN_TOOLTIP_CLOSE = (210, 424)
CN_PAGE_KING_LEVEL_CLOSE = (354, 33)
CN_PAGE_CLASSIC_INFO_CLOSE = (345, 253)
CN_PAGE_DAILY_GIFT_RECEIVED_CLOSE = (210, 606)
CN_PAGE_DAILY_GIFT_INFO_TOGGLE = (352, 67)
CN_PAGE_NEWS_VIDEO_CLOSE = (381, 64)
CN_CLASSIC_MODE_SELECTOR = (315, 493)
CN_CLASSIC_MODE_SCROLL_TO_TOP = (320, 355, 320, 455)
CN_CLASSIC_MODE_SCROLL_TO_BOTTOM = (320, 520, 320, 355)
CN_PAGE_RETURN_COORDS = {
    "collection": CN_PAGE_BATTLE_TAB_FROM_COLLECTION,
    "shop": CN_PAGE_BATTLE_TAB_FROM_SHOP,
    "social": CN_PAGE_BATTLE_TAB_FROM_SOCIAL,
    "events": CN_PAGE_BATTLE_TAB_FROM_EVENTS,
    "top_right": CN_PAGE_TOP_RIGHT_CLOSE,
    "modal_right": CN_PAGE_MODAL_RIGHT_CLOSE,
    "top_left": CN_PAGE_TOP_LEFT_BACK,
    "center_top": CN_PAGE_CENTER_TOP_CLOSE,
    "elite_close": CN_PAGE_ELITE_CLOSE,
    "mode_arrow": CN_PAGE_MODE_ARROW,
    "leaderboard_close": CN_PAGE_LEADERBOARD_CLOSE,
    "burger_dismiss": CN_PAGE_BURGER_DISMISS,
    "profile_close": CN_PAGE_PROFILE_CLOSE,
    "member_dismiss": CN_PAGE_MEMBER_DISMISS,
    "spectate_confirm": CN_PAGE_SPECTATE_CONFIRM,
    "tournaments_back": CN_PAGE_TOURNAMENTS_BACK,
    "tournament_help_close": CN_PAGE_TOURNAMENT_HELP_CLOSE,
    "settings_close": CN_PAGE_SETTINGS_CLOSE,
    "more_settings_close": CN_PAGE_MORE_SETTINGS_CLOSE,
    "shop_info_close": CN_PAGE_SHOP_INFO_CLOSE,
    "market_close": CN_PAGE_MARKET_CLOSE,
    "emote_info_close": CN_PAGE_EMOTE_INFO_CLOSE,
    "clan_intro_confirm": CN_PAGE_CLAN_INTRO_CONFIRM,
    "clan_search_close": CN_PAGE_CLAN_SEARCH_CLOSE,
    "clan_advanced_close": CN_PAGE_CLAN_ADVANCED_CLOSE,
    "clan_emblem_close": CN_PAGE_CLAN_EMBLEM_CLOSE,
    "friend_close": CN_PAGE_FRIEND_CLOSE,
    "exit_game_cancel": CN_PAGE_GAME_EXIT_CANCEL,
    "news_close": CN_PAGE_NEWS_CLOSE,
    "card_info_close": CN_PAGE_CARD_INFO_CLOSE,
    "card_mastery_close": CN_PAGE_CARD_MASTERY_CLOSE,
    "card_editor_confirm": CN_PAGE_CARD_EDITOR_CONFIRM,
    "card_skin_close": CN_PAGE_CARD_SKIN_CLOSE,
    "hero_info_close": CN_PAGE_HERO_INFO_CLOSE,
    "deck_confirm_cancel": CN_PAGE_DECK_CONFIRM_CANCEL,
    "tower_info_close": CN_PAGE_TOWER_INFO_CLOSE,
    "awakening_close": CN_PAGE_AWAKENING_CLOSE,
    "pass_confirm": CN_PAGE_PASS_CONFIRM,
    "daily_activity_confirm": CN_PAGE_DAILY_ACTIVITY_CONFIRM,
    "daily_activity_help_close": CN_PAGE_DAILY_ACTIVITY_HELP_CLOSE,
    "custom_bundle_close": CN_PAGE_CUSTOM_BUNDLE_CLOSE,
    "custom_bundle_choices_close": CN_PAGE_CUSTOM_BUNDLE_CHOICES_CLOSE,
    "custom_bundle_help_close": CN_PAGE_CUSTOM_BUNDLE_HELP_CLOSE,
    "crl_return": CN_PAGE_CRL_RETURN,
    "crl_rules_close": CN_PAGE_CRL_RULES_CLOSE,
    "awakening_machine_close": CN_PAGE_AWAKENING_MACHINE_CLOSE,
    "awakening_machine_sheet_close": CN_PAGE_AWAKENING_MACHINE_SHEET_CLOSE,
    "red_event_close": CN_PAGE_RED_EVENT_CLOSE,
    "red_event_prizes_close": CN_PAGE_RED_EVENT_PRIZES_CLOSE,
    "goblin_preview_close": CN_PAGE_GOBLIN_PREVIEW_CLOSE,
    "crown_tooltip_close": CN_PAGE_CROWN_TOOLTIP_CLOSE,
    "king_level_close": CN_PAGE_KING_LEVEL_CLOSE,
    "classic_info_close": CN_PAGE_CLASSIC_INFO_CLOSE,
    "daily_gift_received_close": CN_PAGE_DAILY_GIFT_RECEIVED_CLOSE,
    "daily_gift_info_toggle": CN_PAGE_DAILY_GIFT_INFO_TOGGLE,
    "news_video_close": CN_PAGE_NEWS_VIDEO_CLOSE,
}
CN_PAGE_ROIS = {
    "collection_nav_selected": (116, 585, 145, 621),
    "collection_nav_selected_search": (80, 553, 203, 633),
    "collection_nav_battle": (217, 582, 275, 625),
    "collection_nav_battle_search": (204, 555, 296, 633),
    "collection_header": (50, 43, 365, 152),
    "page_title": (70, 35, 350, 110),
    "page_title_upper": (65, 0, 355, 65),
    "page_upper_left": (0, 0, 70, 80),
    "page_upper_right": (345, 0, 419, 105),
    "page_body_top": (20, 120, 399, 210),
    "page_body_middle": (30, 260, 389, 360),
    "page_footer": (30, 525, 389, 633),
    "nav_left": (5, 571, 75, 633),
    "nav_middle": (120, 571, 280, 633),
    "nav_right": (280, 571, 415, 633),
    "elite_title": (105, 172, 315, 209),
    "elite_close": (345, 49, 370, 79),
    "mode_title": (161, 134, 261, 164),
    "mode_title_search": (140, 95, 285, 200),
    "mode_arrow": (173, 84, 246, 117),
    "mode_arrow_search": (145, 65, 275, 155),
    "battle_log_title": (158, 59, 262, 90),
    "battle_log_tabs": (53, 94, 261, 126),
    "battle_log_close": (353, 58, 379, 90),
    "leaderboard_title": (159, 54, 260, 85),
    "leaderboard_tabs": (54, 88, 363, 118),
    "leaderboard_close": (350, 52, 379, 85),
    "burger_header": (204, 25, 350, 61),
    "burger_footer": (204, 356, 350, 393),
    "profile_crown": (168, 19, 252, 80),
    "profile_close": (345, 49, 377, 82),
    "clan_title": (184, 56, 237, 83),
    "clan_tab": (53, 89, 155, 116),
    "member_labels": (121, 170, 179, 262),
    "member_profile_button": (168, 276, 252, 315),
    "royale_tv_title": (164, 58, 259, 88),
    "royale_tv_arrows": (40, 92, 80, 128),
    "spectate_next_top": (26, 75, 68, 90),
    "spectate_next_bottom": (26, 582, 68, 599),
    "spectate_confirm_message": (150, 299, 272, 320),
    "spectate_confirm_button": (235, 375, 315, 410),
    "tournaments_title": (139, 56, 280, 81),
    "tournaments_back": (5, 0, 41, 34),
    "tournament_help_title": (121, 100, 310, 128),
    "tournament_help_close": (352, 99, 379, 130),
    "tournament_create_title": (139, 60, 286, 87),
    "inbox_title": (176, 54, 247, 83),
    "settings_title": (184, 118, 235, 147),
    "settings_close": (337, 119, 365, 150),
    "more_settings_title": (167, 161, 259, 192),
    "more_settings_close": (338, 159, 368, 190),
    "shop_nav_selected": (42, 572, 99, 627),
    "shop_nav_selected_search": (25, 552, 120, 633),
    "shop_category_header": (40, 111, 379, 166),
    "shop_info_title": (172, 147, 246, 172),
    "shop_info_close": (357, 152, 372, 166),
    "offer_title_search": (140, 130, 280, 260),
    "offer_close_search": (335, 125, 396, 270),
    "market_title": (174, 97, 248, 121),
    "market_close": (168, 584, 252, 621),
    "market_voucher_info": (123, 374, 144, 398),
    "market_voucher_info_search": (80, 170, 148, 560),
    "emote_info_title": (172, 203, 246, 228),
    "emote_info_close": (357, 207, 372, 221),
    "market_voucher_icon": (98, 376, 118, 397),
    "clan_intro_title": (175, 104, 248, 145),
    "clan_intro_confirm": (168, 591, 252, 629),
    "clan_search_title": (78, 72, 294, 98),
    "clan_search_close": (338, 68, 364, 98),
    "clan_advanced_title": (81, 183, 148, 209),
    "clan_advanced_close": (339, 180, 367, 209),
    "clan_create_title": (134, 56, 285, 84),
    "clan_emblem_title": (169, 104, 252, 132),
    "clan_emblem_close": (338, 104, 364, 133),
    "social_nav_selected": (253, 573, 310, 625),
    "social_nav_selected_search": (242, 552, 335, 633),
    "social_nav_battle": (145, 582, 203, 625),
    "social_nav_battle_search": (132, 555, 224, 633),
    "social_heading": (58, 197, 105, 223),
    "social_filter_title": (229, 87, 301, 112),
    "social_filter_labels": (193, 128, 268, 187),
    "social_add_friend_title": (171, 84, 261, 115),
    "social_add_friend_close": (338, 72, 364, 100),
    "social_friend_profile_button": (66, 440, 152, 478),
    "social_friend_clan_button": (66, 483, 152, 521),
    "profile_editor_crown": (78, 19, 117, 54),
    "profile_editor_confirm": (164, 598, 253, 631),
    "friends_title": (190, 55, 237, 83),
    "classic_label_search": (40, 174, 260, 625),
    "classic_shield_search": (275, 174, 384, 625),
    "mode_top_marker": (58, 210, 143, 237),
    "mode_top_marker_search": (40, 174, 210, 285),
    "classic_label": (57, 416, 159, 445),
    "classic_shield": (291, 420, 348, 478),
    "deck_title": (100, 54, 169, 82),
    "deck_2v2_selectors": (170, 89, 252, 135),
    "game_exit_title": (75, 200, 339, 222),
    "game_exit_message": (83, 300, 337, 321),
    "game_exit_cancel": (103, 376, 183, 408),
    "game_exit_confirm": (236, 376, 315, 408),
    "news_list_tabs": (86, 54, 157, 86),
    "news_close": (163, 578, 258, 622),
    "news_article_label": (34, 89, 66, 112),
    "duel_deck_title": (165, 26, 263, 57),
    "card_info_rarity_label": (165, 269, 217, 288),
    "card_info_type_label": (253, 269, 290, 288),
    "card_info_close": (340, 170, 363, 196),
    "card_mastery_header": (174, 117, 252, 147),
    "card_mastery_close": (342, 74, 367, 100),
    "card_mastery_footer": (97, 567, 322, 600),
    "card_editor_library_title": (46, 497, 118, 523),
    "card_skin_arrow": (174, 140, 245, 171),
    "card_skin_equipped": (168, 588, 241, 625),
    "hero_level_unit": (254, 64, 266, 77),
    "hero_progress_edge": (173, 79, 184, 116),
    "hero_info_close": (339, 17, 364, 43),
    "deck_confirm_title": (171, 197, 246, 224),
    "deck_confirm_message": (146, 300, 273, 321),
    "collection_filter_title": (190, 226, 260, 253),
    "collection_filter_labels": (154, 494, 244, 522),
    "tower_level_unit": (254, 92, 269, 108),
    "tower_info_close": (342, 26, 367, 54),
    "tower_level_unit_search": (236, 89, 279, 113),
    "hero_level_unit_search": (235, 60, 278, 82),
    "awakening_title": (118, 203, 300, 226),
    "awakening_close": (344, 43, 370, 72),
    "collection_filter_title_search": (173, 215, 274, 270),
    "collection_filter_labels_search": (146, 255, 274, 548),
    "deck_action_add_label": (95, 73, 168, 102),
    "deck_action_link_label": (95, 334, 168, 366),
    "deck_clear_title": (171, 197, 246, 224),
    "mode_list_progress": (35, 174, 384, 625),
    "pass_header": (43, 32, 98, 52),
    "pass_footer_confirm": (168, 584, 252, 622),
    "daily_activity_shop_label": (51, 50, 89, 69),
    "daily_activity_footer_confirm": (159, 584, 261, 621),
    "daily_activity_help_title": (150, 241, 282, 264),
    "daily_activity_help_close": (344, 43, 371, 72),
    "daily_activity_shop_label_search": (40, 40, 100, 80),
    "daily_activity_help_title_search": (136, 227, 296, 277),
    "daily_activity_help_close_search": (331, 31, 384, 85),
    "daily_activity_info_anchor": (72, 72, 93, 97),
    "custom_bundle_root_title": (161, 140, 267, 165),
    "custom_bundle_root_close": (347, 145, 373, 173),
    "custom_bundle_choices_title": (151, 135, 266, 160),
    "custom_bundle_choices_close": (344, 133, 370, 160),
    "custom_bundle_help_title": (169, 18, 250, 45),
    "custom_bundle_help_close": (351, 18, 378, 46),
    "crl_header": (78, 152, 337, 263),
    "crl_return_button": (109, 576, 202, 615),
    "crl_rules_title": (168, 103, 255, 132),
    "crl_rules_close": (355, 103, 384, 134),
    "crl_shop_title": (139, 124, 280, 158),
    "crl_shop_champion_button": (213, 575, 312, 616),
    "awakening_machine_title": (140, 108, 284, 133),
    "awakening_machine_close": (347, 103, 374, 132),
    "awakening_machine_rules_title": (172, 115, 247, 139),
    "awakening_machine_prizes_title": (193, 115, 227, 139),
    "awakening_machine_records_title": (173, 115, 247, 140),
    "awakening_machine_sheet_close": (337, 110, 364, 139),
    "awakening_machine_item_title": (173, 205, 248, 229),
    "awakening_machine_item_close": (351, 200, 377, 229),
    "red_event_info_button": (48, 13, 67, 32),
    "red_event_info_button_search": (32, 0, 84, 53),
    "red_event_close": (354, 8, 380, 37),
    "red_event_close_search": (338, 0, 397, 53),
    "red_event_records_icon": (53, 120, 68, 143),
    "red_event_prizes_title": (178, 61, 244, 88),
    "red_event_prizes_close": (335, 60, 363, 89),
    "card_form_footer_tabs": (65, 586, 347, 624),
    "goblin_records_icon": (53, 56, 68, 79),
    "goblin_preview_crown": (181, 9, 239, 58),
    "goblin_preview_confirm": (160, 597, 258, 633),
    "goblin_preview_panel_edge": (42, 331, 378, 350),
    "crown_tooltip_title": (176, 195, 247, 211),
    "crown_tooltip_tip": (186, 375, 233, 399),
    "crown_tooltip_crown": (191, 409, 231, 437),
    "king_collection_title": (158, 23, 265, 47),
    "king_tower_title": (183, 25, 239, 47),
    "king_level_close": (342, 20, 367, 46),
    "classic_info_title": (171, 243, 251, 268),
    "classic_info_close": (332, 239, 359, 267),
    "daily_gift_received_title": (115, 43, 299, 71),
    "daily_gift_received_body": (172, 254, 316, 297),
    "daily_gift_received_confirm": (167, 587, 253, 627),
    "daily_gift_probability_title": (267, 99, 317, 116),
    "daily_gift_info_button": (339, 54, 365, 81),
    "news_native_close_edge": (235, 580, 254, 598),
    "news_video_title": (170, 55, 292, 77),
    "news_video_close": (368, 50, 395, 78),
}
