import time

import numpy as np

from pyclashbot.bot.coords import (
    CARD_MASTERY_COLLECT_COORD,
    CARD_MASTERY_DEADSPACE_COORD,
    CARD_MASTERY_OPTIONS_COORD,
    CARD_MASTERY_PROGRESS_ROI,
    CARD_MASTERY_RETURN_TO_MAIN_COORD,
    CARD_MASTERY_REWARD_COORDS,
    CARD_MASTERY_TAB_COORD,
)
from pyclashbot.bot.nav import (
    get_to_card_page_from_clash_main,
    wait_for_clash_main_menu,
)
from pyclashbot.bot.state_detect import (
    card_mastery_rewards_exist,
    check_for_inventory_full_popup,
    check_if_on_card_page,
    check_if_on_clash_main_menu,
)
from pyclashbot.utils.logger import Logger

_COLLECTION_TIMEOUT_S = 180
_MAX_COLLECTIONS = 20


def card_mastery_state(emulator, logger):
    logger.change_status("Going to collect Card Mastery rewards")

    if check_if_on_clash_main_menu(emulator) is not True:
        logger.change_status("Not on main menu — cannot collect Card Mastery rewards")
        return False

    if collect_card_mastery_rewards(emulator, logger) is False:
        logger.change_status("Failed to collect Card Mastery rewards")
        return False

    return True


def collect_card_mastery_rewards(emulator, logger: Logger) -> bool:
    # get to card page
    logger.change_status("Collecting Card Mastery rewards...")
    if get_to_card_page_from_clash_main(emulator, logger) != "good":
        logger.change_status(
            "Failed to open card page for Card Mastery rewards",
        )
        return False
    time.sleep(3)

    deadline = time.monotonic() + _COLLECTION_TIMEOUT_S
    collections = 0
    if not card_mastery_rewards_exist_with_delay(emulator):
        logger.change_status("No Card Mastery rewards to collect.")
        time.sleep(1)

    else:
        # while card mastery icon exists:
        while card_mastery_rewards_exist_with_delay(emulator):
            if time.monotonic() >= deadline or collections >= _MAX_COLLECTIONS:
                logger.change_status("Card Mastery collection limit reached — requesting recovery")
                return False
            logger.change_status("Detected Card Mastery rewards")
            before = emulator.screenshot()
            if not collect_first_mastery_reward(emulator, deadline=deadline):
                logger.change_status("Card Mastery reward attempt failed — no reward counted")
                return False
            after = emulator.screenshot()
            if card_mastery_rewards_exist(emulator) and not _mastery_progress(before, after):
                logger.change_status("Card Mastery reward progress is unverified — no reward counted")
                return False
            logger.change_status("Collected a Card Mastery reward!")
            logger.add_card_mastery_reward_collection()
            collections += 1
            time.sleep(2)

    # get to clash main
    logger.change_status("Returning to main menu")
    emulator.click(CARD_MASTERY_RETURN_TO_MAIN_COORD[0], CARD_MASTERY_RETURN_TO_MAIN_COORD[1])

    # wait for main to appear
    if wait_for_clash_main_menu(emulator, logger) is False:
        logger.change_status(
            "Timed out returning to main menu from card page",
        )
        return False

    return True


def _mastery_progress(before, after) -> bool:
    if getattr(before, "shape", None) != (633, 419, 3) or getattr(after, "shape", None) != (633, 419, 3):
        return False
    x1, y1, x2, y2 = CARD_MASTERY_PROGRESS_ROI
    delta = np.abs(before[y1:y2, x1:x2].astype(float) - after[y1:y2, x1:x2].astype(float))
    return float(delta.mean()) > 5 and float(np.mean(np.max(delta, axis=2) > 20)) > 0.10


def collect_first_mastery_reward(emulator, *, deadline=None) -> bool:
    if not check_if_on_card_page(emulator) or not card_mastery_rewards_exist(emulator):
        return False
    deadline = min(deadline or float("inf"), time.monotonic() + 60)
    # click the card mastery reward icon
    emulator.click(CARD_MASTERY_OPTIONS_COORD[0], CARD_MASTERY_OPTIONS_COORD[1])
    time.sleep(0.5)

    # click first card
    emulator.click(CARD_MASTERY_TAB_COORD[0], CARD_MASTERY_TAB_COORD[1])
    time.sleep(0.5)

    # click rewards at specific Y positions
    if check_if_on_card_page(emulator):
        return False  # the reward detail did not open; do not click the deck behind it
    for coord in CARD_MASTERY_REWARD_COORDS:
        if time.monotonic() >= deadline:
            return False
        emulator.click(*coord)
        time.sleep(1)
        if check_for_inventory_full_popup(emulator):
            print("Inventory full popup detected!\nClicking it")
            emulator.click(CARD_MASTERY_COLLECT_COORD[0], CARD_MASTERY_COLLECT_COORD[1])
            time.sleep(1)

    # click deadspace
    while not check_if_on_card_page(emulator):
        if time.monotonic() >= deadline:
            print("Clicked deadspace after collecting card mastery reward for too long")
            return False
        emulator.click(*CARD_MASTERY_DEADSPACE_COORD)
        time.sleep(0.2)

    return True


def card_mastery_rewards_exist_with_delay(emulator):
    timeout = 2  # s
    start_time = time.monotonic()
    while time.monotonic() - start_time < timeout:
        if card_mastery_rewards_exist(emulator):
            return True
        time.sleep(0.05)

    return False


if __name__ == "__main__":
    collect_first_mastery_reward(1)
