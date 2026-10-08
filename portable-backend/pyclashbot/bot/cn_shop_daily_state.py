# ruff: noqa: RUF001
"""Bounded, cancellable daily-shop purchases from verified Chinese frames.

The caller owns the physical device lock. Each transaction is attempted once;
an uncertain receipt stops the run rather than repeating a possible purchase.
"""

from __future__ import annotations

import copy
import time
from pathlib import Path
from typing import TypedDict

import cv2

from pyclashbot.bot.cn_1v1_loop import ChineseVision
from pyclashbot.bot.coords import (
    CN_SHOP_DAILY_FREE_GOLD_CONFIRM,
    CN_SHOP_DAILY_SCROLL_DOWN,
    CN_SHOP_DAILY_SCROLL_FINE_DOWN,
    CN_SHOP_DAILY_SCROLL_FINE_MS,
    CN_SHOP_DAILY_SCROLL_FINE_UP,
    CN_SHOP_DAILY_SCROLL_MS,
)
from pyclashbot.bot.nav import PAGE_CN_MAIN, PAGE_SHOP, navigate_main_page
from pyclashbot.detection.cn_page_navigation import cn_navigation_step
from pyclashbot.detection.cn_shop_daily import (
    analyze_shop_frame,
    confirmation,
    insufficient_gold,
    read_gold_balance,
    reward_state,
)

MAX_NAVIGATION_STEPS = 6
MAX_SEARCH_SWIPES = 28
MAX_DAILY_SWIPES = 8
MAX_DAILY_NORMALIZE_SWIPES = 8
MAX_TRANSITION_OBSERVATIONS = 18
MAX_REWARD_INPUTS = 20
MAX_UNKNOWN_OBSERVATIONS = 3
MAX_RUN_SECONDS = 240
OBSERVATION_INTERVAL = 0.5


class DailyShopResult(TypedDict):
    state: str
    status: str
    free_claimed: int
    gold_purchased: int
    gems_skipped: int
    gold_spent: int
    message: str
    items: list[dict[str, object]]


class _CancelledError(Exception):
    pass


class _StoppedError(Exception):
    pass


class _DailyShopFlow:
    def __init__(self, emulator, logger, cancel_event, on_update, evidence_dir):
        self.emulator = emulator
        self.logger = logger
        self.cancel_event = cancel_event
        self.on_update = on_update
        self.evidence_dir = Path(evidence_dir) if evidence_dir is not None else None
        self.started = time.monotonic()
        self.sequence = 0
        self.anchor_y = None
        self.last_visible = []
        self.scroll_direction = None
        self.records = {}
        self.unknown_observations = {}
        self.pending = None
        self.result: DailyShopResult = {
            "state": "running",
            "status": "正在识别商店",
            "free_claimed": 0,
            "gold_purchased": 0,
            "gems_skipped": 0,
            "gold_spent": 0,
            "message": "正在检查每日精选中的免费和金币商品。",
            "items": [],
        }

    def _check(self):
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise _CancelledError
        if time.monotonic() - self.started >= MAX_RUN_SECONDS:
            raise _StoppedError("每日精选操作超过时间预算，已停止；不会重复购买未确认的商品。")

    def _publish(self, status=None, message=None):
        if status is not None:
            self.result["status"] = status
            self.logger.change_status(status)
        if message is not None:
            self.result["message"] = message
        self.result["items"] = [copy.deepcopy(self.records[key]) for key in sorted(self.records)]
        if self.on_update is not None:
            self.on_update(copy.deepcopy(self.result))

    def _pause(self):
        self._check()
        if self.cancel_event is not None:
            self.cancel_event.wait(OBSERVATION_INTERVAL)
        else:
            time.sleep(OBSERVATION_INTERVAL)
        self._check()

    def _frame(self, label):
        self._check()
        frame = self.emulator.screenshot()
        self._check()
        self.sequence += 1
        if self.evidence_dir is not None:
            self.evidence_dir.mkdir(parents=True, exist_ok=True)
            path = self.evidence_dir / f"{self.sequence:03d}-{label}.png"
            if not cv2.imwrite(str(path), frame):
                raise _StoppedError("无法保存购买证据，已停止操作。")
        self._publish()
        return frame

    def _tap(self, point):
        self._check()
        if point is None:
            raise _StoppedError("没有识别到可用的操作按钮，已停止。")
        self.emulator.click(*point)
        self._check()

    def _swipe(self, direction, *, duration=CN_SHOP_DAILY_SCROLL_MS):
        self._check()
        self.scroll_direction = "down" if direction[3] < direction[1] else "up"
        if callable(getattr(self.emulator, "adb", None)):
            coordinates = " ".join(str(value) for value in direction)
            self.emulator.adb(f"shell input swipe {coordinates} {duration}")
        else:
            self.emulator.swipe(*direction)
        self._pause()

    def _analyze(self, frame):
        observed = analyze_shop_frame(frame)
        if not observed.get("valid"):
            raise _StoppedError("游戏截图分辨率或格式不符合校准要求，已停止。")
        if not observed.get("shop_verified"):
            return observed
        anchor_verified = True
        if observed.get("daily_header") is not None:
            self.anchor_y = observed.get("daily_anchor_y")
        elif self.anchor_y is not None:
            shifts = []
            columns = set()
            for item in observed.get("visible_items", []):
                previous = self._previous_portrait(item)
                if previous is not None:
                    shifts.append(self._bottom(item) - self._bottom(previous))
                    columns.add(item["column"])
            if not shifts or (self.scroll_direction is None and len(columns) < 2):
                # A top-row portrait can disappear under the sticky header.
                # Its independently detected panel bottom and unchanged price
                # still track a short movement in the requested direction.
                shifts = []
                columns = set()
                for item in observed.get("visible_items", []):
                    matches = [
                        old
                        for old in self.last_visible
                        if old["column"] == item["column"]
                        and old["currency"] == item["currency"]
                        and old.get("price") == item.get("price")
                    ]
                    matches = [old for old in matches if self._allowed_shift(self._bottom(item) - self._bottom(old))]
                    if len(matches) == 1:
                        shifts.append(self._bottom(item) - self._bottom(matches[0]))
                        columns.add(item["column"])
                if len(columns) < 2:
                    shifts = []
            if shifts and max(shifts) - min(shifts) <= 8:
                self.anchor_y += sorted(shifts)[len(shifts) // 2]
            elif self.scroll_direction is not None:
                raise _StoppedError("滚动后未能确认每日精选商品的移动位置，已停止操作。")
            else:
                # A settling scroll or post-purchase reflow can move the grid
                # without another swipe. Keep the last good positions when
                # fewer than two columns prove that small common movement.
                # Such a frame cannot authorize newly exposed daily slots.
                anchor_verified = False
        if self.anchor_y is not None and observed.get("daily_header") is None:
            observed = analyze_shop_frame(frame, daily_anchor_y=self.anchor_y)
        if not anchor_verified:
            known_slots = {item["slot"] for item in self.last_visible}
            observed["visible_items"] = [
                item for item in observed.get("visible_items", []) if item.get("slot") in known_slots
            ]
        self.scroll_direction = None
        visible = [item.copy() for item in observed.get("visible_items", []) if item.get("slot") in range(6)]
        if anchor_verified and visible:
            self.last_visible = visible
        return observed

    def _previous_portrait(self, item):
        identity = item.get("item_id")
        if identity is None:
            return None
        matches = []
        for old in self.last_visible:
            if old["column"] != item["column"] or old.get("item_id") is None:
                continue
            if not self._allowed_shift(self._bottom(item) - self._bottom(old)):
                continue
            if identity == old["item_id"]:
                matches.append(old)
                continue
            if old["currency"] != item["currency"] or old.get("price") != item.get("price"):
                continue
            try:
                distance = (int(identity, 16) ^ int(old["item_id"], 16)).bit_count()
            except ValueError:
                continue
            if len(identity) == len(old["item_id"]) == 16 and distance <= 6:
                matches.append(old)
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _bottom(item):
        return item["bbox"][3] if item.get("bbox") else item["price_y"]

    def _allowed_shift(self, shift):
        if self.scroll_direction is None:
            return -16 <= shift <= 16
        return -180 <= shift <= 2 if self.scroll_direction == "down" else -2 <= shift <= 180

    def _enter_shop(self):
        # The calibrated Chinese lobby recognizer excludes learned overlays.
        vision = None
        for _ in range(MAX_NAVIGATION_STEPS):
            frame = self._frame("navigation")
            observed = self._analyze(frame)
            if observed.get("shop_verified"):
                return frame, observed
            dialog = confirmation(frame)
            if (
                dialog is not None
                and dialog.get("confirm") == CN_SHOP_DAILY_FREE_GOLD_CONFIRM
                and dialog.get("currency") == "free"
                and dialog.get("price") == 0
            ):
                # Recover only this fully calibrated, still-unclaimed gift
                # modal. A fresh identical observation authorizes its close,
                # not a purchase or a success receipt.
                fresh = self._frame("navigation-confirm-recheck")
                checked = confirmation(fresh)
                if checked != dialog:
                    raise _StoppedError("免费商品弹窗在关闭前发生变化，已停止操作。")
                self._publish("正在关闭已识别的免费商品弹窗")
                return self._close_confirmation(checked)
            step = cn_navigation_step(frame)
            if step is not None:
                if step.idle_only or step.unowned_only or step.target is None:
                    raise _StoppedError("当前页面需要独立的任务上下文，已停止每日精选操作。")
                self._publish("正在返回主菜单")
                self._check()
                if not navigate_main_page(self.emulator, self.logger, f"cn_learned_{step.route}", PAGE_CN_MAIN):
                    # A known nested page can require another fresh return step.
                    self._check()
                    continue
                self._check()
                continue
            if vision is None:
                vision = ChineseVision()
            kind = vision.classify(frame)[0]
            if kind != "lobby":
                raise _StoppedError("当前游戏页面不是已验证的主菜单或商店，已停止操作。")
            self._publish("正在进入商店")
            self._check()
            if not navigate_main_page(self.emulator, self.logger, PAGE_CN_MAIN, PAGE_SHOP):
                raise _StoppedError("进入商店后未取得页面识别证据，已停止操作。")
            self._check()
        raise _StoppedError("未能在有限步骤内进入商店，已停止操作。")

    def _find_daily(self, frame, observed):
        self._publish("正在查找每日精选")
        # If starting in the clipped daily grid, expose its header first. An
        # unseen header never authorizes a card purchase in another category.
        for attempt in range(MAX_SEARCH_SWIPES):
            if not observed.get("shop_verified"):
                raise _StoppedError("查找每日精选时出现未识别页面，已停止操作。")
            if observed.get("daily_header") is not None:
                return self._normalize_daily(frame, observed)
            fine = attempt < 3 and observed.get("visible_items")
            direction = CN_SHOP_DAILY_SCROLL_FINE_UP if fine else CN_SHOP_DAILY_SCROLL_DOWN
            self._swipe(direction, duration=CN_SHOP_DAILY_SCROLL_FINE_MS if fine else CN_SHOP_DAILY_SCROLL_MS)
            frame = self._frame("find-daily")
            observed = self._analyze(frame)
        raise _StoppedError("未能找到每日精选标题，已停止；没有购买其他商店商品。")

    def _normalize_daily(self, frame, observed):
        for _ in range(MAX_DAILY_NORMALIZE_SWIPES):
            if not observed.get("shop_verified"):
                raise _StoppedError("调整每日精选位置时出现未识别页面，已停止。")
            if self.anchor_y is not None and self.anchor_y <= 280:
                return frame, observed
            self._publish("正在定位每日精选第一行")
            self._swipe(CN_SHOP_DAILY_SCROLL_FINE_DOWN, duration=CN_SHOP_DAILY_SCROLL_FINE_MS)
            frame = self._frame("daily-position")
            observed = self._analyze(frame)
        raise _StoppedError("未能在有限步骤内定位每日精选商品，已停止。")

    def _record(self, item, state, message):
        slot = item["slot"]
        self.records[slot] = {
            "slot": slot,
            "currency": item["currency"],
            "price": item.get("price"),
            "state": state,
            "message": message,
        }
        self._publish()

    def _confirmed(self, item, evidence):
        if item["currency"] == "free":
            self.result["free_claimed"] += 1
            state, message = "claimed", "免费商品已领取"
        else:
            self.result["gold_purchased"] += 1
            self.result["gold_spent"] += item["price"]
            state, message = "purchased", "金币商品已购买"
        self._record(item, state, message)
        self.records[item["slot"]]["evidence"] = evidence
        self.pending = None
        self._publish()

    def _receipt(self, item, observed, balance_before, frame, reward_seen):
        if reward_seen:
            return "recognized_reward"
        if not observed.get("shop_verified"):
            return None
        current = next((row for row in observed.get("visible_items", []) if row.get("slot") == item["slot"]), None)
        if current is not None and current["currency"] == "purchased":
            return "purchased_marker"
        balance_after = read_gold_balance(frame)
        if item["currency"] == "gold" and balance_before is not None and balance_after is not None:
            if balance_before - balance_after == item["price"]:
                return "verified_gold_decrease"
        return None

    def _close_confirmation(self, dialog):
        self._tap(dialog.get("cancel"))
        for _ in range(MAX_TRANSITION_OBSERVATIONS):
            self._pause()
            frame = self._frame("cancel-confirmation")
            observed = self._analyze(frame)
            if observed.get("shop_verified"):
                return frame, observed
        raise _StoppedError("关闭购买弹窗后未能确认返回商店，已停止。")

    def _purchase(self, item, balance_before):
        label = "免费商品" if item["currency"] == "free" else f"{item['price']} 金币商品"
        self._publish(f"正在处理第 {item['slot'] + 1} 格{label}")
        self.pending = item.copy()
        self._record(item, "opened", "已打开商品，等待购买确认")
        self._tap(item["center"])
        confirmed = False
        reward_seen = False
        reward_inputs = 0
        for _ in range(MAX_TRANSITION_OBSERVATIONS + MAX_REWARD_INPUTS):
            self._pause()
            frame = self._frame("transaction")
            observed = self._analyze(frame)
            dialog = confirmation(frame)
            if dialog is not None and not confirmed:
                if dialog.get("currency") != item["currency"] or dialog.get("price") != item.get("price"):
                    if dialog.get("currency") == "gems":
                        self.result["gems_skipped"] += 1
                    self._record(item, "skipped_currency_changed", "弹窗币种或价格与商品不符，已跳过")
                    closed = self._close_confirmation(dialog)
                    self.pending = None
                    return closed
                if insufficient_gold(frame):
                    self._record(item, "insufficient_gold", "金币不足，已跳过")
                    closed = self._close_confirmation(dialog)
                    self.pending = None
                    return closed
                # A fresh second frame fences currency changes and modal
                # interference immediately before spending any gold.
                fresh = self._frame("confirm-recheck")
                checked = confirmation(fresh)
                if checked is None:
                    raise _StoppedError("购买确认按钮消失，结果未确认，已停止。")
                if checked.get("currency") != item["currency"] or checked.get("price") != item.get("price"):
                    if checked.get("currency") == "gems":
                        self.result["gems_skipped"] += 1
                    self._record(item, "skipped_currency_changed", "确认前币种或价格发生变化，已跳过")
                    closed = self._close_confirmation(checked)
                    self.pending = None
                    return closed
                if insufficient_gold(fresh):
                    self._record(item, "insufficient_gold", "金币不足，已跳过")
                    closed = self._close_confirmation(checked)
                    self.pending = None
                    return closed
                self._publish(f"已核对第 {item['slot'] + 1} 格{label}，正在确认")
                self._tap(checked.get("confirm"))
                confirmed = True
                self._record(item, "awaiting_receipt", "已发送确认，等待实际购买结果")
                continue
            reward = reward_state(frame)
            if reward is not None and (confirmed or item["currency"] == "free"):
                reward_seen = True
                if reward.get("continue") is not None:
                    if reward_inputs >= MAX_REWARD_INPUTS:
                        raise _StoppedError("领取动画超过有限操作预算，已停止。")
                    self._tap(reward["continue"])
                    reward_inputs += 1
                continue
            receipt = self._receipt(item, observed, balance_before, frame, reward_seen)
            if receipt is not None and observed.get("shop_verified"):
                self._confirmed(item, receipt)
                return frame, observed
            # Unknown screens are observed without a fallback tap. A remaining
            # dialog after confirm also never receives a repeated confirm tap.
        self._record(item, "unverified_attempt", "未取得购买或领取成功证据，已停止；不会重复购买")
        raise _StoppedError("商品操作结果未能确认，已停止；不会重复购买该商品。")

    def run(self):
        frame, observed = self._enter_shop()
        frame, observed = self._find_daily(frame, observed)
        daily_swipes = 0
        while True:
            self._check()
            if not observed.get("shop_verified"):
                raise _StoppedError("每日精选页面被其他窗口遮挡，已停止操作。")
            candidates = [item for item in observed.get("visible_items", []) if item.get("slot") in range(6)]
            candidate = None
            reobserve_unknown = False
            for item in sorted(candidates, key=lambda row: row["slot"]):
                if item["slot"] in self.records:
                    continue
                currency = item["currency"]
                if currency == "gems":
                    self.result["gems_skipped"] += 1
                    self._record(item, "skipped_gems", "宝石商品已跳过")
                elif currency == "purchased":
                    self._record(item, "already_purchased", "商品此前已购买或领取")
                elif currency not in {"free", "gold"} or item.get("price") is None:
                    count = self.unknown_observations.get(item["slot"], 0) + 1
                    self.unknown_observations[item["slot"]] = count
                    if count < MAX_UNKNOWN_OBSERVATIONS:
                        reobserve_unknown = True
                    else:
                        self._record(item, "skipped_unknown", "商品币种或价格未确认，已跳过")
                else:
                    balance = read_gold_balance(frame)
                    if currency == "gold" and balance is not None and balance < item["price"]:
                        self._record(item, "insufficient_gold", "金币不足，已跳过")
                    else:
                        candidate = item
                        break
            if candidate is not None:
                # Reobserve the current card before opening it; no prior frame
                # remains action authority after another transaction or scroll.
                frame = self._frame("item-recheck")
                observed = self._analyze(frame)
                fresh = next(
                    (item for item in observed.get("visible_items", []) if item.get("slot") == candidate["slot"]), None
                )
                if not observed.get("shop_verified") or fresh is None:
                    raise _StoppedError("商品点击前未能再次确认页面与位置，已停止。")
                if fresh["currency"] != candidate["currency"] or fresh.get("price") != candidate.get("price"):
                    continue
                frame, observed = self._purchase(fresh, read_gold_balance(frame))
                continue
            if reobserve_unknown:
                self._publish("正在再次核对每日精选商品价格")
                self._pause()
                frame = self._frame("unknown-price-recheck")
                observed = self._analyze(frame)
                continue
            if len(self.records) == 6:
                partial = any(
                    item["state"] in {"skipped_unknown", "insufficient_gold", "skipped_currency_changed"}
                    for item in self.records.values()
                )
                self.result["state"] = "partial" if partial else "completed"
                self._publish(
                    "每日精选处理完成", "已检查全部 6 格每日精选；免费和金币商品的实际处理结果已记录，宝石商品已跳过。"
                )
                return self.result
            if daily_swipes >= MAX_DAILY_SWIPES or observed.get("daily_end"):
                raise _StoppedError("每日精选中有商品未能完整识别，已停止；没有操作相邻商店区域。")
            self._publish("正在检查每日精选下一行")
            self._swipe(CN_SHOP_DAILY_SCROLL_FINE_DOWN, duration=CN_SHOP_DAILY_SCROLL_FINE_MS)
            daily_swipes += 1
            frame = self._frame("daily-next-row")
            observed = self._analyze(frame)


def run_shop_daily(emulator, logger, *, cancel_event, on_update=None, evidence_dir=None) -> DailyShopResult:
    """Buy only verified free/gold daily offers while the caller owns the device."""
    flow = _DailyShopFlow(emulator, logger, cancel_event, on_update, evidence_dir)
    try:
        return flow.run()
    except _CancelledError:
        flow.result["state"] = "cancelled"
        message = "每日精选操作已取消。"
        if flow.pending is not None:
            flow._record(flow.pending, "cancelled_unverified", "取消时商品结果尚未确认，不会继续点击或重复购买")
            message += "取消时的商品结果尚未确认，已保留记录。"
        flow._publish("每日精选操作已取消", message)
    except _StoppedError as error:
        flow.result["state"] = "partial" if flow.records else "failed"
        if flow.pending is not None and flow.records[flow.pending["slot"]]["state"] not in {
            "unverified_attempt",
            "cancelled_unverified",
        }:
            flow._record(flow.pending, "unverified_attempt", "操作结果未确认，已停止；不会重复购买")
        flow._publish("每日精选操作已停止", str(error))
    return flow.result
