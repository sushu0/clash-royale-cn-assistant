# ruff: noqa: RUF001
# Native Chinese punctuation and multiplication glyphs are intentional UI/OCR text.
"""Randomize, play Classic 1v1, use mastery Claim all, and repeat."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import cast

import cv2
import numpy as np

from pyclashbot.bot.cn_1v1_loop import TEMPLATES as BATTLE_TEMPLATE_ROOT
from pyclashbot.bot.cn_1v1_loop import ChineseVision, RecoveryExhausted, TimedAdbController, _LogAdapter
from pyclashbot.bot.coords import (
    CN_POST_WIN_REWARD_TAP,
    CN_RANDOM_CONFIRM,
    CN_RANDOM_DECK_OPTIONS,
    CN_RANDOM_DETAIL_CLOSE,
    CN_RANDOM_HAND_ROIS,
    CN_RANDOM_LOCKED_DETAIL_CLOSE,
    CN_RANDOM_MASTERY,
    CN_RANDOM_MASTERY_FOOTER_ROI,
    CN_RANDOM_MODAL_CLOSE,
    CN_RANDOM_REWARD_AMOUNT_ROI,
    CN_RANDOM_REWARD_CONTINUE,
    CN_RANDOM_WAND,
    HAND_CARDS_COORDS,
)
from pyclashbot.bot.find import find_cn_mastery_claim_all
from pyclashbot.bot.nav import (
    PAGE_CN_CARD,
    PAGE_CN_COLLECTION,
    PAGE_CN_MAIN,
    navigate_cn_classic_1v1,
    navigate_main_page,
    recover_cn_page_once,
)
from pyclashbot.bot.random_deck_strategy import STRATEGY_VERSION, RandomDeckStrategy
from pyclashbot.detection.cn_battle_cues import _read_elixir, read_cn_battle_cues
from pyclashbot.detection.cn_daily_gift import daily_gift_action, daily_gift_reward_action
from pyclashbot.detection.cn_page_navigation import (
    cn_game_exit_cancel,
    cn_global_challenge_promotion_close,
    cn_king_skin_promotion_close,
    cn_navigation_step,
)
from pyclashbot.detection.cn_puzzle_reward import puzzle_reward_action
from pyclashbot.detection.cn_random_deployment import deployment_evidence, slot_was_consumed
from pyclashbot.detection.cn_random_hand import identify_random_hand
from pyclashbot.detection.cn_random_ui import (
    TEMPLATE_ROOT,
    available_random_slots,
    changed_deck_slots,
    deck_portraits,
    mastery_footer_state,
    random_ui_is,
)
from pyclashbot.detection.cn_reward_quantity import coin_quantity_fallback
from pyclashbot.detection.cn_shop_daily import confirmation as shop_confirmation
from pyclashbot.emulators.base import CLASH_ROYALE_PACKAGE
from pyclashbot.utils.cn_footer_ocr import read_local_ocr
from pyclashbot.utils.mastery_rewards import (
    append_confirmed_rewards,
    confirmed_reward_event,
    preserve_receipt,
    read_reward_quantity,
    read_reward_totals,
    receipt_key,
)
from pyclashbot.utils.persistence import append_jsonl_once, atomic_write_bytes, atomic_write_json, read_validated_json
from pyclashbot.utils.runtime_config import environment_identity, load_runtime_config, resource_path, source_path

ROOT = load_runtime_config().data_root
POLICY_VERSION = "random-mastery-v26-loss-review-20261004"
BATTLE_POLL_SECONDS = 0.12
BATTLE_FRAME_STALL_SECONDS = 45.0
BATTLE_FRAME_SAMPLE_SECONDS = 1.0
MAX_CONSECUTIVE_RECOVERIES = 3
LOBBY_START_WAIT_SECONDS = 600.0
LOBBY_START_POLL_SECONDS = 2.0
LOBBY_START_REPORT_SECONDS = 30.0
PRE_MATCH_OBSERVE_SECONDS = 3.0
PRE_MATCH_OBSERVE_INTERVAL = 0.2


class RandomMasteryLoop:
    def __init__(self, adb_path, serial, logger, memuc_path=None, vm_index=0, strategy_name="random"):
        TimedAdbController.adb_path = adb_path
        self.device = TimedAdbController(_LogAdapter(logger), device_serial=serial)
        self.serial = serial
        self.recovery_attempts = 0
        self._reset_battle_frame_monitor()
        self.vision = ChineseVision()
        self.logger = logger
        self.completed = 0
        self.consecutive = 0
        self.closed_loops = 0
        self.total_claimed = 0
        self.generated = 0
        self.state = "starting"
        self.last_action = {}
        self.strategy = RandomDeckStrategy(time.monotonic())
        self.strategy_reason = "等待新卡组与手牌识别"
        self.last_strategy_observation = -100.0
        self.session = time.strftime("%Y%m%d-%H%M%S")
        self.work = ROOT / "work" / "random-mastery" / self.session
        self.work.mkdir(parents=True, exist_ok=True)
        self.trace_path = ROOT / "outputs" / "cn-random-mastery.jsonl"
        self.status_path = ROOT / "outputs" / "random-mastery-live-status.json"
        self.stop_path = ROOT / "work" / "random-mastery" / "STOP"
        self.checkpoint_path = ROOT / "work" / "random-mastery" / "checkpoint.json"
        self.result_outbox_path = ROOT / "work" / "random-mastery" / "pending-result.json"
        self.drain_path = ROOT / "work" / "random-mastery" / "DRAIN"
        checkpoint = read_validated_json(self.checkpoint_path, self._valid_checkpoint, default={})
        self.completed = checkpoint.get("completed", 0)
        self.generated = checkpoint.get("generated", 0)
        self.closed_loops = checkpoint.get("closed_loops", 0)
        self.total_claimed = checkpoint.get("total_claimed", 0)
        self.pending_mastery = checkpoint.get("pending_mastery", False)
        self.pending_claim_all = checkpoint.get("pending_claim_all", False)
        self.pending_battle = checkpoint.get("pending_battle", False)
        self.reward_claim_id = checkpoint.get("reward_claim_id")
        self.reward_receipts = checkpoint.get("reward_receipts", [])
        self.reward_slot = checkpoint.get("reward_slot", 0)
        self.reward_phase = checkpoint.get("reward_phase", "")
        self.reward_ledger = ROOT / "outputs" / "cn-mastery-rewards.jsonl"
        totals = read_reward_totals(self.reward_ledger)
        self.total_reward_items = totals["rewards"]
        self.total_reward_coins = totals["coins"]
        self.unknown_coin_items = totals["unknown_coin_items"]
        self.active_battle = self.completed if self.pending_mastery else self.completed + 1
        self.evidence_sequence = 0
        self.cards_confirmed = 0
        self.card_attempts = 0
        if self.pending_battle and self.status_path.exists():
            try:
                previous = read_validated_json(self.status_path, lambda value: isinstance(value, dict), default={})
            except ValueError:
                previous = {}  # Diagnostic status never overrides a valid checkpoint.
            if previous.get("completed") == self.completed and previous.get("generated_decks") == self.generated:
                self.cards_confirmed = previous.get("cards_confirmed", 0)
                self.card_attempts = previous.get("card_attempts", 0)
        package = resource_path("pyclashbot")
        source_files = [
            "bot/cn_random_mastery_loop.py",
            "bot/coords.py",
            "bot/cn_1v1_loop.py",
            "bot/nav.py",
            "bot/state_detect.py",
            "bot/random_deck_strategy.py",
            "bot/random_card_roles.py",
            "detection/cn_random_hand.py",
            "detection/cn_random_deployment.py",
            "detection/cn_random_ui.py",
            "detection/cn_daily_gift.py",
            "detection/cn_page_navigation.py",
            "utils/cn_footer_ocr.py",
            "utils/persistence.py",
            "utils/runtime_config.py",
        ]
        paths = [
            *(source_path("pyclashbot/" + name) for name in source_files),
            package / "detection/reference_images/cn_random_cards/card_catalog.json",
            package / "detection/reference_images/cn_random_cards/consumed_slot.png",
            resource_path("scripts/ocr_cn_footer.ps1"),
            *TEMPLATE_ROOT.glob("*.png"),
            *BATTLE_TEMPLATE_ROOT.glob("*.png"),
        ]
        hand_calibration = package / "detection/reference_images/cn_random_cards/hand_calibration_20261003"
        paths.extend(path for path in sorted(hand_calibration.rglob("*")) if path.is_file())
        for folder in ("cn_daily_gift", "cn_pages"):
            paths.extend(
                path
                for path in sorted((package / "detection/reference_images" / folder).rglob("*"))
                if path.is_file() and path.suffix.lower() in {".png", ".json"}
            )
        hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        environment = environment_identity()
        self.experiment = {
            "rule_version": STRATEGY_VERSION,
            "strategy_hash": hashes[str(source_path("pyclashbot/bot/random_deck_strategy.py"))],
            "asset_hash": hashlib.sha256(
                json.dumps(
                    {name: digest for name, digest in hashes.items() if name.endswith((".png", ".json"))},
                    sort_keys=True,
                ).encode()
            ).hexdigest(),
            "environment_hash": environment["sha256"],
        }
        atomic_write_json(
            self.work / "manifest.json",
            {
                "policy": POLICY_VERSION,
                "serial": serial,
                "sha256": hashes,
                "experiment": self.experiment,
                "environment": environment,
                "environment_hash": environment["sha256"],
            },
        )
        self._recover_result_outbox()

    @staticmethod
    def _valid_checkpoint(data):
        if not isinstance(data, dict) or type(data.get("schema", 1)) is not int or data.get("schema", 1) != 1:
            return False
        for name in ("completed", "generated", "closed_loops", "total_claimed", "reward_slot"):
            value = data.get(name, 0)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                return False
        for name in ("pending_mastery", "pending_claim_all", "pending_battle"):
            if not isinstance(data.get(name, False), bool):
                return False
        if data.get("reward_claim_id") is not None and not isinstance(data["reward_claim_id"], str):
            return False
        receipts = data.get("reward_receipts", [])
        return (
            isinstance(receipts, list)
            and isinstance(data.get("reward_phase", ""), str)
            and all(
                isinstance(row, dict)
                and isinstance(row.get("id"), str)
                and row.get("kind") in ("coins", "gems", "other")
                and (
                    row.get("amount") is None
                    or (isinstance(row["amount"], int) and not isinstance(row["amount"], bool) and row["amount"] > 0)
                )
                and isinstance(row.get("evidence", {}), dict)
                for row in receipts
            )
        )

    def _recover_result_outbox(self):
        path = getattr(self, "result_outbox_path", None)
        if path is None or not path.is_file():
            return
        pending = read_validated_json(
            path,
            lambda value: (
                isinstance(value, dict)
                and isinstance(value.get("row"), dict)
                and type(value.get("schema")) is int
                and value["schema"] == 1
                and isinstance(value.get("committed", False), bool)
            ),
        )
        row = pending["row"]
        battle = row.get("finished_battle")
        if (
            not isinstance(battle, int)
            or isinstance(battle, bool)
            or battle < 1
            or not isinstance(row.get("session"), str)
            or not re.fullmatch(r"\d{8}-\d{6}", row["session"])
        ):
            raise RecoveryExhausted("待发布结果结构无效; 已保留断点与凭据")
        try:
            datetime.strptime(row["session"], "%Y%m%d-%H%M%S")
        except ValueError as error:
            raise RecoveryExhausted("待发布结果运行时间无效; 未发布战绩") from error
        result = pending.get("result")
        if (
            row.get("event") != "battle_finished"
            or row.get("battle") != battle
            or row.get("event_id") != f"result:{row['session']}:{battle}"
            or not isinstance(result, dict)
            or result.get("outcome") not in ("胜利", "失败", "平局", "未知")
            or any(
                row.get(name) != result.get(name)
                for name in ("outcome", "card_attempts", "cards_confirmed", "generation", "evidence")
            )
        ):
            raise RecoveryExhausted("待发布结果身份或内容不一致; 未发布战绩")
        counts = [result.get(name) for name in ("card_attempts", "cards_confirmed", "generation")]
        if (
            any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in counts)
            or counts[1] > counts[0]
        ):
            raise RecoveryExhausted("待发布结果计数无效; 未发布战绩")
        if self.completed < battle and self.completed + 1 != battle:
            raise RecoveryExhausted("待发布结果与断点场次不连续; 未发布战绩")
        if self.completed > battle and not pending.get("committed", False):
            raise RecoveryExhausted("待发布结果落后于断点; 未发布战绩")
        evidence = result.get("evidence")
        source_work = ROOT / "work" / "random-mastery" / row["session"]
        try:
            picture = Path(evidence["path"]).resolve()
            digest = evidence["sha256"]
            valid = (
                picture.is_relative_to(source_work.resolve())
                and picture.suffix.lower() == ".png"
                and isinstance(digest, str)
                and hashlib.sha256(picture.read_bytes()).hexdigest() == digest
            )
        except (OSError, ValueError, TypeError, KeyError):
            valid = False
        if not valid:
            raise RecoveryExhausted("待发布结算图缺失或哈希不一致; 未发布战绩")
        atomic_write_json(source_work / f"battle-{battle:04d}.json", pending["result"])
        append_jsonl_once(self.trace_path, row)
        if self.completed < battle:
            self.completed = battle
            self.pending_battle = False
            self.pending_mastery = True
            self.active_battle = battle
            self._checkpoint()
        atomic_write_json(path, {"schema": 1, "row": row, "result": pending["result"], "committed": True})
        # Keep the committed receipt as a recovery journal. A future result
        # replaces it only after that result's immutable evidence is durable.

    def _event(self, event, **values):
        ledger = getattr(self, "reward_ledger", None)
        if ledger is not None and ledger.exists():
            stamp = ledger.stat().st_mtime_ns
            if stamp != getattr(self, "reward_ledger_stamp", None):
                totals = read_reward_totals(ledger)
                self.total_reward_items, self.total_reward_coins = totals["rewards"], totals["coins"]
                self.unknown_coin_items = totals["unknown_coin_items"]
                self.reward_ledger_stamp = stamp
        row = {
            "event": event,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "session": self.session,
            "policy": POLICY_VERSION,
            "battle": self.active_battle,
            "experiment": getattr(self, "experiment", {}),
            **values,
        }
        with self.trace_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        status = {
            "updated_at": row["time"],
            "pid": os.getpid(),
            "session": self.session,
            "state": self.state,
            "mode": "classic_1v1",
            "strategy": "random_mastery",
            "completed": self.completed,
            "generated_decks": self.generated,
            "closed_loops": self.closed_loops,
            "claim_all_batches": self.total_claimed,
            "card_attempts": self.card_attempts,
            "cards_confirmed": self.cards_confirmed,
            "last_event": event,
            "evidence_dir": str(self.work),
        }
        status["rewards_received"] = getattr(self, "total_reward_items", 0)
        status["coins_received"] = getattr(self, "total_reward_coins", 0)
        status["unknown_coin_items"] = getattr(self, "unknown_coin_items", 0)
        strategy = getattr(self, "strategy", None)
        if strategy is not None:
            status["strategy_version"] = STRATEGY_VERSION
            status["combat_profile"] = strategy.profile()
            status["decision_reason"] = getattr(self, "strategy_reason", "等待规则决策")
            status["last_action"] = getattr(self, "last_action", {})
            status["battle_poll_seconds"] = BATTLE_POLL_SECONDS
        atomic_write_json(self.status_path, status)

    def _save(self, name, frame):
        self.evidence_sequence += 1
        # Ring storage bounds battle screenshots; completed-cycle records remain separate.
        path = self.work / f"recent-{name}-{self.evidence_sequence % 48:02d}.png"
        ok, encoded = cv2.imencode(".png", frame)
        if not ok:
            raise RuntimeError("Cannot encode evidence")
        data = encoded.tobytes()
        if name in (
            "result",
            "recovery",
            "frozen-battle",
            "battle-recovered",
            "mismatch",
            "navigation-mismatch",
            "battle-start",
            "battle",
            "decision",
            "play",
            "pending-battle-lobby",
        ):
            digest = hashlib.sha256(data).hexdigest()
            path = self.work / "evidence" / f"{name}-{digest}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise RecoveryExhausted("已保存证据校验失败; 已保留原文件并暂停")
                return {"path": str(path), "sha256": digest}
        atomic_write_bytes(path, data)
        return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}

    def _use_recovery(self, reason, frame=None):
        """Spend a bounded recovery budget without altering a persisted game cycle."""
        attempts = getattr(self, "recovery_attempts", 0)
        if attempts >= MAX_CONSECUTIVE_RECOVERIES:
            raise RecoveryExhausted(f"连续三次恢复未完成真实闭环; 暂停: {reason}")
        self.recovery_attempts = attempts + 1
        values = {"reason": reason, "attempt": self.recovery_attempts}
        if isinstance(frame, np.ndarray):
            values["evidence"] = self._save("recovery", frame)
        self._event("recovery_attempt", **values)
        self.logger.warning("有界恢复 %d/%d: %s", self.recovery_attempts, MAX_CONSECUTIVE_RECOVERIES, reason)

    def _reconnect_adb(self):
        """Reconnect only this ADB transport; leave the VM and shared server running."""
        try:
            state = self.device.adb("get-state", timeout=5)
            if state.returncode == 0 and (state.stdout or "").strip() == "device":
                return
        except (OSError, subprocess.TimeoutExpired):
            pass
        serial = getattr(self, "serial", getattr(self.device, "device_serial", ""))
        if ":" in serial:
            result = self.device.adb(f"connect {serial}", timeout=20)
            if result.returncode != 0:
                raise RecoveryExhausted("ADB 设备重连失败; 保留断点并暂停")

    def _capture_frame(self):
        while True:
            try:
                return self.device.screenshot()
            except (OSError, subprocess.TimeoutExpired, RuntimeError, ValueError) as error:
                # The ADB controller raises this precise error for undecodable
                # screencap bytes. Invalid arguments remain terminal errors.
                if isinstance(error, ValueError) and not str(error).startswith("Failed to decode screenshot."):
                    raise
                self._use_recovery(f"ADB 截图临时失败: {type(error).__name__}")
                try:
                    self._reconnect_adb()
                except (OSError, subprocess.TimeoutExpired, RecoveryExhausted) as reconnect_error:
                    self.logger.warning("ADB 重连暂未成功: %s", type(reconnect_error).__name__)
                time.sleep(0.5)

    def _recover_app(self, reason, frame=None):
        self._classic_menu_verified = False
        self._use_recovery(reason, frame)
        result = self.device.adb(f"shell am force-stop {CLASH_ROYALE_PACKAGE}", timeout=20)
        if result.returncode != 0:
            raise RecoveryExhausted("游戏停止失败; 保留断点并暂停")
        # A successful force-stop invalidates the in-memory daily reveal. Its
        # old timer and blue-background continuation cannot own the new loader.
        # Persisted battle/mastery checkpoints and receipts remain untouched.
        self._daily_reward_pending = False
        self._daily_reward_started_at = None
        self._daily_reward_taps = 0
        self._daily_gift_attempts = 0
        self._awaiting_relaunch_observation = True
        self.device.start_app(CLASH_ROYALE_PACKAGE)
        self._reset_battle_frame_monitor()

    def _reset_battle_frame_monitor(self):
        self._battle_frame_hash = None
        self._battle_frame_changed_at = None
        self._battle_frame_sampled_at = None

    def _battle_frame_stalled(self, kind, frame, now):
        if kind != "battle":
            self._reset_battle_frame_monitor()
            return False
        sampled_at = getattr(self, "_battle_frame_sampled_at", None)
        if sampled_at is not None and now - sampled_at < BATTLE_FRAME_SAMPLE_SECONDS:
            return False
        digest = hashlib.sha256(frame.tobytes()).digest()
        self._battle_frame_sampled_at = now
        if digest != getattr(self, "_battle_frame_hash", None):
            self._battle_frame_hash = digest
            self._battle_frame_changed_at = now
        return now - self._battle_frame_changed_at >= BATTLE_FRAME_STALL_SECONDS

    def _frame(self):
        if self.stop_path.exists():
            raise KeyboardInterrupt
        frame = self._capture_frame()
        # Android can return a black render frame during a panel transition.
        # Reobserve briefly without issuing any additional input.
        for _ in range(5):
            if frame is not None and float(np.std(frame)) >= 2:
                break
            time.sleep(0.25)
            frame = self._capture_frame()
        if frame is None or frame.shape != (633, 419, 3):
            raise RecoveryExhausted("截图尺寸或 ADB 连接异常；暂停")
        challenge_promotion = cn_global_challenge_promotion_close(frame)
        if challenge_promotion is not None:
            if (
                getattr(self, "pending_claim_all", False)
                or getattr(self, "pending_battle", False)
                or getattr(self, "state", None) in ("matching", "battle")
                or self.device.foreground_package() != CLASH_ROYALE_PACKAGE
            ):
                raise RecoveryExhausted("当前对战、领奖或前台状态不允许关闭全球挑战赛广告；保留现场并暂停")
            attempts = getattr(self, "_global_challenge_promotion_close_attempts", 0) + 1
            self._global_challenge_promotion_close_attempts = attempts
            if attempts > 3:
                raise RecoveryExhausted("全球挑战赛广告连续3次未关闭；保留现场并暂停")
            if challenge_promotion.target is None:
                raise RecoveryExhausted("未确认全球挑战赛广告关闭按钮；保留现场并暂停")
            self._event(
                "global_challenge_promotion_close_attempt",
                attempt=attempts,
                evidence=self._save("global-challenge-promotion", frame),
            )
            self._tap(challenge_promotion.target, 0.8)
            return self._frame()
        self._global_challenge_promotion_close_attempts = 0
        promotion = cn_king_skin_promotion_close(frame)
        if promotion is not None:
            if (
                getattr(self, "pending_claim_all", False)
                or getattr(self, "pending_battle", False)
                or getattr(self, "state", None) in ("matching", "battle")
            ):
                raise RecoveryExhausted("已有对战或领奖交易断点；保留国王皮肤广告现场，暂停操作")
            attempts = getattr(self, "_king_skin_promotion_close_attempts", 0) + 1
            self._king_skin_promotion_close_attempts = attempts
            if attempts > 3:
                raise RecoveryExhausted("国王皮肤广告连续3次未关闭；保留现场并暂停")
            if promotion.target is None:
                raise RecoveryExhausted("未确认国王皮肤广告关闭按钮；保留现场并暂停")
            self._event(
                "king_skin_promotion_close_attempt",
                attempt=attempts,
                evidence=self._save("king-skin-promotion", frame),
            )
            self._tap(promotion.target, 0.8)
            return self._frame()
        self._king_skin_promotion_close_attempts = 0
        daily = daily_gift_action(frame)
        if daily is not None:
            attempts = getattr(self, "_daily_gift_attempts", 0) + 1
            self._daily_gift_attempts = attempts
            if attempts > 3:
                raise RecoveryExhausted("每日礼物选择连续3次未离开；暂停")
            action, target = daily
            self._awaiting_relaunch_observation = False
            self._event(
                "daily_gift_choice",
                action=action,
                choice="我想变好看",
                attempt=attempts,
                evidence=self._save("daily-gift-choice", frame),
            )
            self.logger.info("每日福袋已识别，按已保存偏好选择：我想变好看")
            if not getattr(self, "_daily_reward_pending", False):
                self._daily_reward_pending = True
                self._daily_reward_started_at = time.monotonic()
                self._daily_reward_taps = 0
            self._tap(target, 1.5)
            return self._frame()
        self._daily_gift_attempts = 0
        cancel_exit = cn_game_exit_cancel(frame)
        if cancel_exit is not None and cancel_exit.target is not None:
            attempts = getattr(self, "_exit_cancel_attempts", 0) + 1
            self._exit_cancel_attempts = attempts
            if attempts > 3:
                raise RecoveryExhausted("退出确认连续3次未关闭；保留现场并暂停")
            self._event("game_exit_cancelled", evidence=self._save("exit-cancel", frame), attempt=attempts)
            self._tap(cancel_exit.target, 0.8)
            return self._frame()
        self._exit_cancel_attempts = 0
        interrupted = self.vision.find(frame, "connection_interrupted")
        if interrupted is not None and self.vision.classify(frame)[0] == "connection_interrupted":
            if getattr(self, "pending_claim_all", False):
                raise RecoveryExhausted("领奖断点尚待核验; 连接中断保留凭据并暂停")
            # Do not click a relogin control or enter an authentication flow.
            # Relaunching the installed app lets it reuse its existing session.
            self._recover_app("已确认连接中断及重新登录提示", frame)
            recovered = self._startup_frame()
            if getattr(self, "pending_battle", False) and self.vision.classify(recovered)[0] not in (
                "battle",
                "result",
            ):
                raise RecoveryExhausted("连接恢复后未确认待续本局对战或结算; 保留断点, 不开新局")
            return recovered
        # Only the calibrated connection dialog authorizes this input. Reobserve
        # after confirmation; callers never receive the stale overlay frame.
        connection = self.vision.find(frame, "connection_confirm")
        if connection is not None and self.vision.classify(frame)[0] == "connection":
            self._use_recovery("关闭已识别连接弹窗", frame)
            self._reset_battle_frame_monitor()
            self._tap(connection.center, 3)
            return self._frame()
        if getattr(self, "_daily_reward_pending", False):
            kind = self.vision.classify(frame)[0]
            daily_reward = daily_gift_reward_action(frame)
            exited = kind == "lobby" or (
                kind not in ("reward", "connection", "connection_interrupted")
                and (
                    random_ui_is(frame, "deck")
                    or random_ui_is(frame, "collection")
                    or cn_navigation_step(frame) is not None
                )
            )
            if exited:
                self._daily_reward_pending = False
                self._daily_reward_taps = 0
            else:
                # Pending rewards have a monotonic start time; relaunch clears both fields.
                if time.monotonic() - cast(float, self._daily_reward_started_at) >= 120:
                    self._event("daily_gift_reward_timeout", evidence=self._save("daily-gift-reward-timeout", frame))
                    raise RecoveryExhausted("每日礼物奖励120秒内未返回已知页面；暂停")
                if daily_reward is not None or kind == "reward" or self.vision.reward_continuation(frame):
                    if self._daily_reward_taps >= 40:
                        raise RecoveryExhausted("每日礼物奖励连续40次未结束；暂停")
                    self._daily_reward_taps += 1
                    self._event(
                        "daily_gift_reward",
                        tap=self._daily_reward_taps,
                        action=daily_reward[0] if daily_reward is not None else "continue_recognized_reward",
                        evidence=self._save("daily-gift-reward", frame),
                    )
                    # Existing four-star reveals need time between inputs.
                    delay = 5 if self.vision.four_star_reward(frame) else 1.5
                    self._tap(daily_reward[1] if daily_reward is not None else CN_POST_WIN_REWARD_TAP, delay)
                    return self._frame()
        return frame

    def _require(self, name):
        deadline = time.monotonic() + 3
        recoveries = 0
        page_returns = 0
        while True:
            frame = self._frame()
            learned = cn_navigation_step(frame) if name == "deck" else None
            editing_deck = learned is not None and learned.page == "card_editor"
            if random_ui_is(frame, name) and not editing_deck:
                return frame
            if editing_deck and page_returns < 12 and self._return_known_page(frame, expected=name):
                page_returns += 1
                deadline = time.monotonic() + 3
                continue
            # A remembered Collection tab is a known navigation state, not a
            # mastery modal. Verify it before switching back to the Deck tab.
            if (
                name == "deck"
                and recoveries < 2
                and (random_ui_is(frame, "collection") or self.vision.classify(frame)[0] == "lobby")
            ):
                recoveries += 1
                collection = random_ui_is(frame, "collection")
                self._event(
                    "collection_return_to_deck" if collection else "lobby_return_to_deck",
                    evidence=self._save("collection" if collection else "lobby", frame),
                )
                navigate_main_page(
                    self.device,
                    _LogAdapter(self.logger),
                    PAGE_CN_COLLECTION if collection else PAGE_CN_MAIN,
                    PAGE_CN_CARD,
                )
                deadline = time.monotonic() + 3
                continue
            if name == "deck" and page_returns < 12 and self._return_known_page(frame, expected=name):
                page_returns += 1
                deadline = time.monotonic() + 3
                continue
            # Post-battle rewards can arrive after the lobby/navigation snapshot.
            # Re-enter the interrupted page only after clearing a verified reward;
            # mastery Claim all keeps its separate receipt/checkpoint workflow.
            post_reward = (
                name in ("deck", "mastery_list")
                and getattr(self, "pending_mastery", False)
                and not getattr(self, "pending_claim_all", False)
                and not getattr(self, "_page_recovery_active", False)
                and (self.vision.classify(frame)[0] == "reward" or self.vision.reward_continuation(frame))
            )
            if post_reward and recoveries < 2:
                recoveries += 1
                self._event("late_post_battle_reward", expected=name, evidence=self._save("late-reward", frame))
                previous_state = self.state
                self._page_recovery_active = True
                try:
                    self._return_from_result()
                    self._navigate(PAGE_CN_MAIN, PAGE_CN_CARD)
                    if name == "mastery_list":
                        self._require("deck")
                        self._tap(CN_RANDOM_MASTERY)
                finally:
                    self.state = previous_state
                    self._page_recovery_active = False
                deadline = time.monotonic() + 3
                continue
            if time.monotonic() >= deadline:
                self._event("screen_mismatch", expected=name, evidence=self._save("mismatch", frame))
                raise RecoveryExhausted(f"未确认 {name} 页面，暂停操作")
            time.sleep(0.2)

    def _tap(self, point, delay=0.65):
        if self.stop_path.exists():
            raise KeyboardInterrupt
        self.device.click(*point)
        time.sleep(delay)

    def _return_known_page(self, frame, *, expected):
        # Result/mastery receipts stay owned by their existing workflows.
        if getattr(self, "pending_battle", False) or getattr(self, "pending_claim_all", False):
            return False
        if getattr(self, "state", None) in ("matching", "battle"):
            return False
        if self.vision.classify(frame)[0] in ("battle", "result", "reward", "connection", "connection_interrupted"):
            return False
        step = cn_navigation_step(frame)
        if step is None:
            return False
        self._event(
            "known_page_return",
            page=step.page,
            expected=expected,
            route=step.route,
            target=list(step.target) if step.target is not None else None,
            evidence=self._save("known-page", frame),
        )
        return (
            recover_cn_page_once(
                self.device,
                _LogAdapter(self.logger),
                frame=frame,
                allow_spectator_exit=True,
                allow_unowned_confirmation=getattr(self, "state", None) != "generating_deck",
            )
            is not None
        )

    def _navigate(self, start, end):
        expected = "deck" if start == PAGE_CN_CARD else "lobby"
        deadline = time.monotonic() + 8
        recoveries = 0
        page_returns = 0
        while True:
            frame = self._frame()
            kind = self.vision.classify(frame)[0]
            valid = random_ui_is(frame, "deck") if expected == "deck" else kind == "lobby"
            learned = cn_navigation_step(frame) if expected == "deck" else None
            if learned is not None and learned.page == "card_editor":
                valid = False
            if valid:
                break
            if page_returns < 12 and self._return_known_page(frame, expected=expected):
                page_returns += 1
                deadline = time.monotonic() + 8
                continue
            post_reward = (
                start == PAGE_CN_MAIN
                and getattr(self, "pending_mastery", False)
                and not getattr(self, "pending_claim_all", False)
                and (kind == "reward" or self.vision.reward_continuation(frame))
            )
            if post_reward and recoveries < 2:
                recoveries += 1
                self._event("late_post_battle_reward", start=start, end=end, evidence=self._save("late-reward", frame))
                self._return_from_result()
                # A fresh observation may still be a reward/transition frame.
                # Keep the same bounded source loop instead of checking once.
                deadline = time.monotonic() + 8
                continue
            if time.monotonic() >= deadline:
                self._event(
                    "navigation_mismatch",
                    start=start,
                    end=end,
                    expected=expected,
                    observed=kind,
                    recoveries=recoveries,
                    evidence=self._save("navigation-mismatch", frame),
                )
                raise RecoveryExhausted(f"主页面导航失败：{start} -> {end}")
            time.sleep(0.2)
        navigate_main_page(self.device, _LogAdapter(self.logger), start, end)
        # The nav helper's first snapshot may be a transition/black frame.
        # Observe the destination for a bounded interval without another tap.
        if end == PAGE_CN_CARD:
            self._require("deck")
        else:
            deadline = time.monotonic() + 3
            while self.vision.classify(self._frame())[0] != "lobby":
                if time.monotonic() >= deadline:
                    raise RecoveryExhausted("导航后未确认经典1V1大厅")
                time.sleep(0.2)

    def _new_deck(self):
        self.active_battle = self.completed + 1
        self.state = "generating_deck"
        before = self._require("deck")
        portraits = deck_portraits(before)
        for attempt in range(3):
            self._require("deck")
            self._tap(CN_RANDOM_DECK_OPTIONS)
            self._require("deck_menu")
            self._tap(CN_RANDOM_WAND)
            confirmation = self._require("deck_confirm")
            self._event("deck_confirmation", evidence=self._save("deck-confirm", confirmation))
            self._tap(CN_RANDOM_CONFIRM, 1.4)
            after = self._require("deck")
            changes = changed_deck_slots(portraits, deck_portraits(after))
            if changes >= 1:
                self.generated += 1
                self._checkpoint()
                self._event(
                    "deck_generated",
                    generation=self.generated,
                    changed_slots=changes,
                    evidence_before=self._save("deck-before", before),
                    evidence_after=self._save("deck-after", after),
                )
                self.logger.info("随机卡组已生成 第%d套，变化卡位=%d", self.generated, changes)
                return
            self._event("deck_unchanged", attempt=attempt + 1)
        raise RecoveryExhausted("三次生成后未确认卡组改变；未开局")

    def _play(self, frame):
        started = time.monotonic()
        hand = identify_random_hand(frame)
        cues = read_cn_battle_cues(frame, include_567=True)
        elixir = cues.get("elixir")
        now = time.monotonic()
        decision = self.strategy.decide(hand, cues, now)
        if decision is None:
            self.strategy_reason = self.strategy.observation.get("reason", "等待规则决策")
            if now - self.last_strategy_observation >= 2:
                self._event("strategy_observe", hand=hand, cues=cues, observation=self.strategy.observation)
                self.last_strategy_observation = now
            return
        slot, name, point = decision.slot, decision.card, decision.point
        self.strategy_reason = decision.reason
        self.card_attempts += 1
        self.last_action = {
            "card": name,
            "slot": slot,
            "category": decision.category,
            "phase": "selecting",
            "reason": decision.reason,
        }
        self._event("card_selection_started", slot=slot, card_hint=name, category=decision.category)
        self._tap(HAND_CARDS_COORDS[slot], 0.02)
        selected = self._frame()
        if self.vision.classify(selected)[0] != "battle":
            self.last_action["phase"] = "battle_ended"
            self.strategy.record(decision, False, time.monotonic())
            return
        selected_was_empty = slot_was_consumed(selected, slot)
        if self.card_attempts <= 2:
            self._event("selection_evidence", evidence=self._save("selected", selected), slot=slot)
        drop_started = time.monotonic()
        self.last_action["phase"] = "deploying"
        self._tap(point, 0.08)
        verification = {"confirmed": False, "method": "battle_ended", "portrait_change": 0}
        previous_card = None
        samples = 0
        after_elixir = None
        while True:
            after = self._frame()
            samples += 1
            if self.vision.classify(after)[0] != "battle":
                break
            after_elixir = _read_elixir(after)
            verification = deployment_evidence(
                frame, after, slot, name, elixir, after_elixir, previous_card, selected_was_empty
            )
            previous_card = verification["after_card"]
            if verification["confirmed"] or time.monotonic() - drop_started >= 1.05:
                break
            time.sleep(0.09)
        confirmed = verification["confirmed"]
        change = verification["portrait_change"]
        if confirmed:
            self.cards_confirmed += 1
        self.strategy.record(decision, confirmed, time.monotonic())
        self.last_action.update(
            phase="confirmed" if confirmed else "unconfirmed", duration_ms=round((time.monotonic() - started) * 1000, 1)
        )
        timings = {
            "decision_ms": round((now - started) * 1000, 1),
            "select_ms": round((drop_started - now) * 1000, 1),
            "verify_ms": round((time.monotonic() - drop_started) * 1000, 1),
            "total_ms": self.last_action["duration_ms"],
            "verification_frames": samples,
        }
        self._event(
            "play",
            slot=slot,
            card_hint=name,
            point=point,
            elixir=elixir,
            after_elixir=after_elixir,
            portrait_change=round(float(change), 2),
            confirmed=confirmed,
            decision=asdict(decision),
            category=decision.category,
            reason=decision.reason,
            strategy_version=STRATEGY_VERSION,
            hand=hand,
            cues=cues,
            timings=timings,
            verification_method=verification["method"],
        )
        if self.card_attempts <= 4 or self.card_attempts % 10 == 0 or not confirmed:
            self._event(
                "play_evidence",
                confirmed=confirmed,
                attempt=self.card_attempts,
                decision=asdict(decision),
                evidence_before=self._save("decision", frame),
                evidence=self._save("play", after),
            )

    @staticmethod
    def _hand_portrait(frame, slot):
        x1, y1, x2, y2 = CN_RANDOM_HAND_ROIS[slot]
        return frame[y1:y2, x1:x2]

    def _prepare_classic_lobby(self, frame, *, verify_menu=False):
        if getattr(self, "pending_battle", False) or getattr(self, "pending_claim_all", False):
            raise RecoveryExhausted("对战或领奖断点尚未闭合；不改模式")
        if self.vision.classify(frame)[0] != "lobby":
            raise RecoveryExhausted("切换经典模式前未确认大厅；未开局")
        self._event("verify_classic_navigation", evidence=self._save("mode-before", frame))
        for attempt in range(2):
            if navigate_cn_classic_1v1(self.device, _LogAdapter(self.logger), self.vision, verify_menu=verify_menu):
                fresh = self._frame()
                fresh_kind = self.vision.classify(fresh)[0]
                if fresh_kind in ("battle", "result", "reward"):
                    raise RecoveryExhausted("模式验证后的新画面出现对战或奖励；保留现场，未重启或开局")
                if fresh_kind == "lobby" and self.vision.classic_selected(fresh):
                    self._classic_menu_verified = True
                    self._event("classic_navigation_verified", evidence=self._save("mode-verified", fresh))
                    return fresh
            observed = self._frame()
            if attempt or self.vision.classify(observed)[0] in ("battle", "result", "reward"):
                break
            # No match has been submitted and no reward receipt is open. An
            # idle relaunch clears a stale SDK panel without touching the VM.
            self._recover_app("大厅无法完成模式菜单往返验证，恢复已安装游戏", observed)
            recovered = self._startup_frame()
            if self.vision.classify(recovered)[0] != "lobby":
                break
        raise RecoveryExhausted("未能通过已校准路径确认经典1V1与可交互大厅；未开局")

    def _wait_for_lobby_start(self, frame):
        """Wait only on a confirmed disabled Classic lobby, without submitting."""
        if any(getattr(self, name, False) for name in ("pending_battle", "pending_mastery", "pending_claim_all")):
            raise RecoveryExhausted("已有对战或领奖断点尚未闭合；未提交新匹配")
        availability_check = getattr(self.vision, "lobby_start_state", None)
        if not callable(availability_check):
            raise RecoveryExhausted("对战按钮可用性检测未就绪；未提交匹配")
        deadline = time.monotonic() + LOBBY_START_WAIT_SECONDS
        waiting_since = None
        next_report = 0.0
        while True:
            kind, match = self.vision.classify(frame)
            if kind != "lobby" or match is None or not self.vision.classic_selected(frame):
                raise RecoveryExhausted("等待对战按钮时未确认经典 1V1 大厅；未提交匹配，保留现场")
            availability = availability_check(frame)
            now = time.monotonic()
            if availability == "ready":
                if waiting_since is not None:
                    self.strategy_reason = "对战按钮已开放，准备匹配"
                    self._event(
                        "lobby_start_available",
                        waited_seconds=round(now - waiting_since, 1),
                        evidence=self._save("lobby-start-available", frame),
                    )
                    self.logger.info("经典 1V1 对战按钮已开放，准备匹配")
                return frame, match
            if availability != "disabled":
                raise RecoveryExhausted("未确认对战按钮可点击或已禁用；未提交匹配，保留现场")
            if waiting_since is None:
                waiting_since = now
                self.strategy_reason = "对战按钮暂不可用，等待开放；尚未提交匹配"
                self._event(
                    "lobby_start_unavailable",
                    wait_limit_seconds=LOBBY_START_WAIT_SECONDS,
                    evidence=self._save("lobby-start-unavailable", frame),
                )
                self.logger.info("经典 1V1 对战按钮暂不可用，等待开放；尚未提交匹配")
                next_report = now + LOBBY_START_REPORT_SECONDS
            if now >= deadline:
                raise RecoveryExhausted("经典 1V1 对战按钮持续不可用超过10分钟；未提交匹配，暂停")
            if now >= next_report:
                self._event("lobby_start_waiting", waited_seconds=round(now - waiting_since, 1))
                next_report = now + LOBBY_START_REPORT_SECONDS
            time.sleep(min(LOBBY_START_POLL_SECONDS, deadline - now))
            frame = self._frame()

    def _preflight_read(self, command, deadline, *, binary=False):
        if self.stop_path.exists():
            raise KeyboardInterrupt
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Pre-match observation deadline exhausted")
        result = self.device.adb(command, binary_output=binary, timeout=remaining)
        if self.stop_path.exists():
            raise KeyboardInterrupt
        if time.monotonic() >= deadline:
            raise TimeoutError("Pre-match observation deadline exhausted")
        if result.returncode != 0:
            raise RuntimeError("Pre-match read failed")
        return result.stdout

    def _preflight_capture(self, deadline):
        raw = self._preflight_read("exec-out screencap -p", deadline, binary=True)
        if not isinstance(raw, bytes) or not raw:
            return None
        return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)

    def _preflight_foreground(self, deadline):
        for command in ("shell dumpsys window", "shell dumpsys activity activities"):
            output = self._preflight_read(command, deadline)
            for line in (output or "").splitlines():
                if any(
                    key in line for key in ("mCurrentFocus", "mFocusedApp", "mResumedActivity", "topResumedActivity")
                ):
                    match = re.search(r"([A-Za-z][\w.]+)/(?:[\w.$]+)", line)
                    if match:
                        return match.group(1)
        return None

    def _reject_preflight(self, frame, reason, observation=None):
        values = {
            "kind": "unobserved",
            "has_match": False,
            "classic_selected": False,
            "menu_verified": bool(getattr(self, "_classic_menu_verified", False)),
            "availability": "unknown",
            "foreground_package": None,
            **(observation or {}),
        }
        values["eligible_reason"] = reason
        values.setdefault("evidence_role", "observed_frame" if isinstance(frame, np.ndarray) else "unavailable_capture")
        if isinstance(frame, np.ndarray) and frame.dtype == np.uint8 and frame.ndim == 3:
            values["evidence"] = self._save("mismatch", frame)
        self._event("pre_match_rejected", **values)
        raise RecoveryExhausted(f"开局前未确认稳定经典1V1大厅；未提交匹配：{reason}")

    def _preflight_classic_lobby(self, frame, *, deadline):
        stable, previous = 0, None
        observation = None
        while True:
            if self.stop_path.exists():
                raise KeyboardInterrupt
            pending = any(
                getattr(self, name, False) for name in ("pending_battle", "pending_mastery", "pending_claim_all")
            )
            if pending or not getattr(self, "_classic_menu_verified", False):
                self._reject_preflight(frame, "pending_transaction" if pending else "menu_unverified")
            valid = isinstance(frame, np.ndarray) and frame.shape == (633, 419, 3) and frame.dtype == np.uint8
            kind, match = self.vision.classify(frame) if valid else ("invalid", None)
            classic = self.vision.classic_selected(frame) if valid else False
            availability = self.vision.lobby_start_state(frame) if kind == "lobby" and classic else "unknown"
            observation = {
                "kind": kind,
                "has_match": match is not None,
                "classic_selected": classic,
                "menu_verified": True,
                "availability": availability,
                "foreground_package": None,
            }
            try:
                observation["foreground_package"] = self._preflight_foreground(deadline)
            except (OSError, RuntimeError, TimeoutError, subprocess.TimeoutExpired) as error:
                self._reject_preflight(frame, f"read_failed:{type(error).__name__}", observation)
            if observation["foreground_package"] != CLASH_ROYALE_PACKAGE:
                self._reject_preflight(frame, "foreign_app", observation)
            if not valid:
                self._reject_preflight(frame, "invalid_frame", observation)
            if shop_confirmation(frame) is not None:
                self._reject_preflight(frame, "payment_confirmation", observation)
            if self.vision.four_star_reward(frame) and self.vision.find(frame, "reward_star") is not None:
                self._reject_preflight(frame, "recognized_star_reward", observation)
            if daily_gift_action(frame) is not None or daily_gift_reward_action(frame) is not None:
                self._reject_preflight(frame, "recognized_daily_reward", observation)
            if kind not in ("unknown", "lobby") or (kind == "unknown" and cn_navigation_step(frame) is not None):
                self._reject_preflight(frame, "recognized_non_lobby", observation)
            if kind == "lobby" and (match is None or not classic):
                self._reject_preflight(frame, "wrong_mode_or_missing_match", observation)
            strict = kind == "lobby" and match is not None and classic and availability in ("ready", "disabled")
            stable = stable + 1 if strict and previous == availability else int(strict)
            previous = availability if strict else None
            now = time.monotonic()
            if now >= deadline:
                self._reject_preflight(frame, "observation_deadline", observation)
            if stable >= 2:
                return frame, match
            time.sleep(min(PRE_MATCH_OBSERVE_INTERVAL, deadline - now))
            try:
                frame = self._preflight_capture(deadline)
            except (OSError, RuntimeError, TimeoutError, subprocess.TimeoutExpired) as error:
                self._reject_preflight(
                    frame,
                    f"capture_failed:{type(error).__name__}",
                    {**observation, "evidence_role": "last_successful_capture"},
                )

    def _battle(self, resumed=False):
        deadline = time.monotonic() + PRE_MATCH_OBSERVE_SECONDS
        if resumed:
            self.state = "matching"
            frame = self._frame()
        else:
            if self.stop_path.exists():
                raise KeyboardInterrupt
            if any(getattr(self, name, False) for name in ("pending_battle", "pending_mastery", "pending_claim_all")):
                self._reject_preflight(None, "pending_transaction")
            try:
                frame = self._preflight_capture(deadline)
            except (OSError, RuntimeError, TimeoutError, subprocess.TimeoutExpired) as error:
                self._reject_preflight(None, f"capture_failed:{type(error).__name__}")
        valid = isinstance(frame, np.ndarray) and frame.shape == (633, 419, 3) and frame.dtype == np.uint8
        kind, match = self.vision.classify(frame) if valid or resumed else ("invalid", None)
        if resumed:
            if not self.pending_battle or kind not in ("battle", "result"):
                raise RecoveryExhausted("没有可恢复的本循环对局；未开新局")
        else:
            if kind == "lobby" and not getattr(self, "_classic_menu_verified", False):
                initial_availability = self.vision.lobby_start_state(frame)
                if match is None or initial_availability not in ("ready", "disabled"):
                    self._reject_preflight(
                        frame,
                        "unverified_lobby_before_menu",
                        {"kind": kind, "has_match": match is not None, "availability": initial_availability},
                    )
                try:
                    foreground = self._preflight_foreground(deadline)
                except (OSError, RuntimeError, TimeoutError, subprocess.TimeoutExpired) as error:
                    self._reject_preflight(frame, f"read_failed:{type(error).__name__}")
                if foreground != CLASH_ROYALE_PACKAGE:
                    self._reject_preflight(
                        frame,
                        "foreign_app",
                        {"kind": kind, "has_match": match is not None, "foreground_package": foreground},
                    )
                frame = self._prepare_classic_lobby(frame, verify_menu=True)
                # The causal menu roundtrip remains separate from the short,
                # input-free observation budget that follows its verified end.
                deadline = time.monotonic() + PRE_MATCH_OBSERVE_SECONDS
            frame, match = self._preflight_classic_lobby(frame, deadline=deadline)
            self.state = "matching"
            frame, match = self._wait_for_lobby_start(frame)
            if self.stop_path.exists():
                raise KeyboardInterrupt
            if not getattr(self, "_classic_menu_verified", False) or any(
                getattr(self, name, False) for name in ("pending_battle", "pending_mastery", "pending_claim_all")
            ):
                self._reject_preflight(
                    frame,
                    "context_changed_before_commit",
                    {
                        "kind": self.vision.classify(frame)[0],
                        "has_match": match is not None,
                        "classic_selected": self.vision.classic_selected(frame),
                        "availability": self.vision.lobby_start_state(frame),
                        "pending_battle": self.pending_battle,
                        "pending_mastery": self.pending_mastery,
                        "pending_claim_all": self.pending_claim_all,
                    },
                )
            self.pending_battle = True
            self._checkpoint()
            self._event("match_requested", generation=self.generated, evidence=self._save("lobby", frame))
            self._tap(match.center, 0.5)
            deadline = time.monotonic() + 150
            confirmations = 0
            while time.monotonic() < deadline:
                frame = self._frame()
                confirmations = confirmations + 1 if self.vision.classify(frame)[0] == "battle" else 0
                if confirmations >= 2:
                    break
                time.sleep(0.5)
            else:
                raise RecoveryExhausted("匹配或加载超过150秒；暂停")
        self.state = "battle"
        self.strategy = RandomDeckStrategy(time.monotonic())
        self.last_action = {}
        self.strategy_reason = "按当前手牌建立本局进攻与防守计划"
        if not resumed:
            self.cards_confirmed = self.card_attempts = 0
        self._event(
            "battle_resumed" if resumed else "battle_started",
            generation=self.generated,
            evidence=self._save("battle-start", frame),
        )
        self.logger.info("随机卡组对战开始 第%d局", self.completed + 1)
        self._reset_battle_frame_monitor()
        deadline = time.monotonic() + 420
        result_count = 0
        last_observe = 0
        while time.monotonic() < deadline:
            frame = self._frame()
            kind, _ = self.vision.classify(frame)
            result_count = result_count + 1 if kind == "result" else 0
            if result_count >= 2:
                break
            now = time.monotonic()
            if self._battle_frame_stalled(kind, frame, now):
                changed_at = self._battle_frame_changed_at
                assert changed_at is not None
                self._event(
                    "battle_frame_frozen",
                    unchanged_seconds=now - changed_at,
                    evidence=self._save("frozen-battle", frame),
                )
                self._recover_app("对战整帧连续45秒静止", frame)
                recovered = self._startup_frame()
                recovered_kind, _ = self.vision.classify(recovered)
                if recovered_kind not in ("battle", "result") or not self.pending_battle:
                    raise RecoveryExhausted("游戏重启后未确认本局对战或结算; 保留断点, 不虚计完成数")
                self._event("battle_recovered", kind=recovered_kind, evidence=self._save("battle-recovered", recovered))
                continue
            if kind == "battle":
                self._play(frame)
            if now - last_observe >= 12:
                self._event(
                    "battle_observed",
                    elixir=_read_elixir(frame) if kind == "battle" else None,
                    available_slots=available_random_slots(frame) if kind == "battle" else [],
                    evidence=self._save("battle", frame),
                )
                last_observe = now
            time.sleep(BATTLE_POLL_SECONDS if kind == "battle" else 0.3)
        else:
            raise RecoveryExhausted("对战超过7分钟；暂停")
        outcome = self.vision.outcome(frame)
        result = {
            "outcome": outcome,
            "card_attempts": self.card_attempts,
            "cards_confirmed": self.cards_confirmed,
            "generation": self.generated,
            "evidence": self._save("result", frame),
        }
        finished = self.completed + 1
        source_session = getattr(self, "session", self.work.name)
        event_row = {
            "event": "battle_finished",
            "event_id": f"result:{source_session}:{finished}",
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "session": source_session,
            "policy": POLICY_VERSION,
            "battle": finished,
            "finished_battle": finished,
            "mode": "classic_1v1",
            "experiment": getattr(self, "experiment", {}),
            **result,
        }
        outbox = getattr(self, "result_outbox_path", None)
        if outbox is not None:
            atomic_write_json(outbox, {"schema": 1, "row": event_row, "result": result, "committed": False})
        atomic_write_json(self.work / f"battle-{finished:04d}.json", result)
        if outbox is not None:
            append_jsonl_once(self.trace_path, event_row)
        self.completed += 1
        self.pending_battle = False
        self.pending_mastery = True
        self.state = "returning"
        self._checkpoint()
        self.consecutive = self.consecutive + 1 if self.cards_confirmed else 0
        if outbox is not None:
            atomic_write_json(outbox, {"schema": 1, "row": event_row, "result": result, "committed": True})
            self._event("result_committed", finished_battle=self.completed)
        else:
            self._event("battle_finished", finished_battle=self.completed, **result)
        self.logger.info(
            "对战结束 结果=%s 出牌确认=%d/%d 已完成=%d 连续完成=%d",
            outcome,
            self.cards_confirmed,
            self.card_attempts,
            self.completed,
            self.consecutive,
        )
        self._return_from_result()

    def _post_battle_puzzle_action(self, frame):
        """Resolve the recorded puzzle panels only for this completed battle."""
        if (
            not getattr(self, "pending_mastery", False)
            or getattr(self, "pending_claim_all", False)
            or getattr(self, "pending_battle", False)
        ):
            return None
        action = puzzle_reward_action(frame)
        if action is None or self.device.foreground_package() != CLASH_ROYALE_PACKAGE:
            return None
        return action

    def _return_from_result(self, *, allow_restart=True):
        self.state = "returning"
        deadline = time.monotonic() + 120
        reward_context = getattr(self, "pending_mastery", False) and not getattr(self, "pending_claim_all", False)
        lobby_since = None
        taps = 0
        while time.monotonic() < deadline:
            frame = self._frame()
            kind, match = self.vision.classify(frame)
            if kind == "lobby":
                if lobby_since is None:
                    lobby_since = time.monotonic()
                if time.monotonic() - lobby_since >= 3:
                    self._event("returned_lobby", evidence=self._save("return", frame))
                    return
                time.sleep(0.4)
                continue
            lobby_since = None
            puzzle = self._post_battle_puzzle_action(frame)
            if time.monotonic() >= deadline:
                break
            if kind == "result" and match:
                self._tap(match.center, 1.8)
            elif puzzle is not None or kind == "reward" or (reward_context and self.vision.reward_continuation(frame)):
                reward_context = True
                taps += 1
                if taps > 40:
                    raise RecoveryExhausted("即时奖励步骤超过上限")
                opened = self.vision.find(frame, "reward_rainbow_open")
                if puzzle is not None:
                    self._event(
                        "post_battle_puzzle_reward",
                        action=puzzle[0],
                        tap=taps,
                        evidence=self._save("post-battle-puzzle", frame),
                    )
                if time.monotonic() >= deadline:
                    break
                self._tap(puzzle[1] if puzzle is not None else opened.center if opened else CN_POST_WIN_REWARD_TAP, 3)
            else:
                time.sleep(0.8)
        # A completed battle is already checkpointed. One relaunch may clear a
        # stalled transition, but mastery Claim all must retain its receipt flow.
        if allow_restart and getattr(self, "pending_mastery", False) and not getattr(self, "pending_claim_all", False):
            self._recover_app("结算/即时奖励120秒未返回大厅", frame)
            recovered = self._startup_frame()
            recovered_kind, _ = self.vision.classify(recovered)
            if (
                recovered_kind not in ("lobby", "result", "reward")
                and self._post_battle_puzzle_action(recovered) is None
                and not self.vision.reward_continuation(recovered)
            ):
                raise RecoveryExhausted("结算重启后未确认大厅或本局奖励; 保留断点并暂停")
            return self._return_from_result(allow_restart=False)
        raise RecoveryExhausted("结算/即时奖励未返回大厅；暂停")

    def _detail_frame(self):
        deadline = time.monotonic() + 3
        while True:
            frame = self._frame()
            if any(random_ui_is(frame, name) for name in ("mastery_detail", "mastery_locked")):
                return frame
            if time.monotonic() >= deadline:
                self._event(
                    "screen_mismatch", expected="mastery_detail_or_locked", evidence=self._save("mismatch", frame)
                )
                raise RecoveryExhausted("未确认卡牌大师详情页，暂停")
            time.sleep(0.2)

    def _close_detail(self):
        frame = self._detail_frame()
        self._tap(
            CN_RANDOM_LOCKED_DETAIL_CLOSE if random_ui_is(frame, "mastery_locked") else CN_RANDOM_DETAIL_CLOSE, 0.35
        )

    def _checkpoint_data(self):
        return {
            "schema": 1,
            "completed": self.completed,
            "generated": self.generated,
            "closed_loops": self.closed_loops,
            "total_claimed": self.total_claimed,
            "pending_mastery": self.pending_mastery,
            "pending_claim_all": self.pending_claim_all,
            "pending_battle": getattr(self, "pending_battle", False),
            "reward_claim_id": getattr(self, "reward_claim_id", None),
            "reward_receipts": getattr(self, "reward_receipts", []),
            "reward_slot": getattr(self, "reward_slot", 0),
            "reward_phase": getattr(self, "reward_phase", ""),
        }

    def _checkpoint(self):
        data = self._checkpoint_data()
        atomic_write_json(self.checkpoint_path, data, backup=True, validator=self._valid_checkpoint)

    def _reward_intro(self):
        if self.reward_phase != "intro":
            self.reward_slot += 1
            self.reward_phase = "intro"
            self._checkpoint()

    def _record_reward(self, frame, kind, amount=None):
        if amount is None:
            x1, y1, x2, y2 = CN_RANDOM_REWARD_AMOUNT_ROI
            amount, _, _ = read_reward_quantity(frame[y1:y2, x1:x2], self.work / "ocr-reward-quantity.png")
            if amount is None and kind == "coins":
                amount = coin_quantity_fallback(frame)
            if amount is None:
                time.sleep(0.5)
                settled = self._frame()
                if random_ui_is(settled, "mastery_reward_coin"):
                    frame = settled
                    amount, _, _ = read_reward_quantity(frame[y1:y2, x1:x2], self.work / "ocr-reward-quantity.png")
                    if amount is None and kind == "coins":
                        amount = coin_quantity_fallback(frame)
        if kind == "other" and amount is None:
            return False
        key = receipt_key(self.reward_slot, kind, amount)
        unknown_key = receipt_key(self.reward_slot, kind, None)
        unknown = next((item for item in self.reward_receipts if item["id"] == unknown_key), None)
        if amount is not None and unknown is not None:
            self.reward_receipts.remove(unknown)
        if any(item["id"] == key for item in self.reward_receipts):
            self.reward_phase = "receipt"
            self._checkpoint()
            return False
        ok, encoded = cv2.imencode(".png", frame)
        if not ok:
            raise RecoveryExhausted("奖励截图保存失败")
        evidence = preserve_receipt(encoded.tobytes(), ROOT / "work/random-mastery/reward-receipts")
        self.reward_receipts.append({"id": key, "kind": kind, "amount": amount, "evidence": evidence})
        self.reward_phase = "receipt"
        self._checkpoint()
        self._event("reward_observed", kind=kind, amount=amount, receipt_id=key, evidence=evidence)
        return True

    def _commit_rewards(self):
        if not self.reward_claim_id:
            self.reward_claim_id = uuid.uuid4().hex
        event = confirmed_reward_event(
            self.reward_claim_id,
            self.reward_receipts,
            session=self.session,
            battle=self.active_battle,
            stamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            policy=POLICY_VERSION,
        )
        append_confirmed_rewards(self.reward_ledger, event)
        totals = read_reward_totals(self.reward_ledger)
        self.total_reward_items, self.total_reward_coins = totals["rewards"], totals["coins"]
        self.unknown_coin_items = totals["unknown_coin_items"]
        self._event(
            "reward_totals_confirmed", rewards_received=self.total_reward_items, coins_received=self.total_reward_coins
        )
        self.reward_claim_id = None
        self.reward_receipts = []
        self.reward_phase = ""
        self.reward_slot = 0

    def _claim_all_return(self):
        deadline = time.monotonic() + 60
        unknown_since = time.monotonic()
        while time.monotonic() < deadline:
            frame = self._frame()
            if random_ui_is(frame, "mastery_list"):
                return
            if random_ui_is(frame, "mastery_reward_continue"):
                self._reward_intro()
                self._event(
                    "claim_reward_continue",
                    point=CN_RANDOM_REWARD_CONTINUE,
                    evidence=self._save("claim-continue", frame),
                )
                self._tap(CN_RANDOM_REWARD_CONTINUE, 1.2)
                unknown_since = time.monotonic()
                continue
            if random_ui_is(frame, "mastery_reward_coin"):
                if self._record_reward(frame, "coins"):
                    deadline = time.monotonic() + 60
                self._event("claim_reward_reveal", evidence=self._save("claim-coin", frame))
                self._tap(CN_RANDOM_REWARD_CONTINUE, 1.2)
                unknown_since = time.monotonic()
                continue
            kind, _ = self.vision.classify(frame)
            if kind == "reward" or self.vision.reward_continuation(frame):
                if self._record_reward(frame, "other"):
                    deadline = time.monotonic() + 60
                opened = self.vision.find(frame, "reward_rainbow_open")
                self._tap(opened.center if opened else CN_POST_WIN_REWARD_TAP, 2)
                unknown_since = time.monotonic()
                continue
            data = read_local_ocr(frame, self.work / "ocr-claim-popup.png")
            text = "".join(data.get("text", "").split())
            known_background = random_ui_is(frame, "mastery_reward_background")
            currency_reveal = known_background and any(word in text for word in ("金币", "宝石", "星级积分"))
            if currency_reveal:
                resource = "coins" if "金币" in text else "gems" if "宝石" in text else "other"
                if self._record_reward(frame, resource):
                    deadline = time.monotonic() + 60
            reward = any(word in text for word in ("奖励", "获得", "恭喜")) or currency_reveal
            forbidden = any(word in text for word in ("购买", "花费", "升级", "不足"))
            point = None
            if reward and not forbidden:
                for line in data.get("lines", []):
                    label = "".join(line["text"].split())
                    if label in ("确定", "继续", "领取"):
                        point = (int(line["x"] + line["width"] / 2), int(line["y"] + line["height"] / 2))
                        break
                if point is None and ("点击继续" in text or "点击屏幕继续" in text):
                    point = CN_POST_WIN_REWARD_TAP
                if point is None and currency_reveal:
                    point = CN_RANDOM_REWARD_CONTINUE
            if point:
                self._event("claim_reward_continue", point=point, evidence=self._save("claim-popup", frame))
                self._tap(point, 1.2)
                unknown_since = time.monotonic()
            elif time.monotonic() - unknown_since > 8:
                self._event("claim_all_unverified", evidence=self._save("claim-unknown", frame))
                raise RecoveryExhausted("领取全部后出现未识别奖励弹窗；未记录领取成功")
            else:
                time.sleep(0.4)
        raise RecoveryExhausted("领取全部后60秒未返回卡牌大师列表")

    def _mastery(self):
        self.state = "mastery"
        self._require("deck")
        self._tap(CN_RANDOM_MASTERY)
        frame = self._require("mastery_list")
        self._event("mastery_opened", evidence=self._save("mastery-list", frame))
        attempts = int(self.pending_claim_all)
        for _ in range(8):
            for observation in range(3):
                frame = self._require("mastery_list")
                footer_text = ""
                footer_state = mastery_footer_state(frame)
                if footer_state == "unknown":
                    x1, y1, x2, y2 = CN_RANDOM_MASTERY_FOOTER_ROI
                    data = read_local_ocr(frame[y1:y2, x1:x2], self.work / "ocr-footer.png")
                    footer_text = data.get("text", "")
                    footer_state = mastery_footer_state(frame, footer_text)
                if footer_state != "unknown":
                    break
                if observation < 2:
                    time.sleep(0.4)
            self._event(
                "mastery_footer_checked",
                footer_state=footer_state,
                method="claim_all_footer_only",
                per_card_checked=False,
                evidence=self._save("mastery-footer", frame),
            )
            if footer_state == "none":
                if attempts:
                    self._commit_rewards()
                    self.total_claimed += attempts
                    self.pending_claim_all = False
                    self._checkpoint()
                    self._event("claim_all_confirmed", batches=attempts, evidence=self._save("claim-after", frame))
                self._event(
                    "mastery_checked",
                    method="claim_all_footer_only",
                    per_card_checked=False,
                    no_rewards_remaining=True,
                    claim_all_batches=attempts,
                    evidence=self._save("mastery-complete", frame),
                )
                self.logger.info(
                    "卡牌大师：%s，关闭页面继续下一局", "领取全部已确认" if attempts else "没有领取全部按钮，无可领奖励"
                )
                break
            point = find_cn_mastery_claim_all(self.device, frame, footer_text)
            if footer_state != "claim_all" or point is None:
                raise RecoveryExhausted("卡牌大师底部既非领取全部也非无奖励提示；暂停")
            self._event("claim_all_attempt", evidence=self._save("claim-before", frame))
            if not self.pending_claim_all:
                self.reward_claim_id = uuid.uuid4().hex
                self.reward_receipts = []
                self.reward_slot = 0
                self.reward_phase = ""
            self.pending_claim_all = True
            self._checkpoint()
            self._tap(point, 1.0)
            attempts += 1
            self._claim_all_return()
        else:
            raise RecoveryExhausted("领取全部连续8次后仍有按钮；未确认领取完成")
        self._tap(CN_RANDOM_MODAL_CLOSE, 0.65)
        self._require("deck")

    def _startup_frame(self):
        deadline = time.monotonic() + 90
        page_returns = 0
        while time.monotonic() < deadline:
            frame = self._frame()
            kind, _ = self.vision.classify(frame)
            ready = kind in ("lobby", "battle", "result", "reward") or any(
                random_ui_is(frame, name)
                for name in (
                    "deck",
                    "collection",
                    "mastery_list",
                    "mastery_detail",
                    "mastery_locked",
                    "mastery_reward_continue",
                    "mastery_reward_coin",
                )
            )
            ready = (
                ready
                or (self._post_battle_puzzle_action(frame) is not None)
                or (
                    getattr(self, "pending_mastery", False)
                    and not getattr(self, "pending_claim_all", False)
                    and not getattr(self, "_awaiting_relaunch_observation", False)
                    and self.vision.reward_continuation(frame)
                )
            )
            core_page = kind in ("lobby", "battle", "result", "reward") or any(
                random_ui_is(frame, name) for name in ("deck", "collection")
            )
            learned = cn_navigation_step(frame)
            if learned is not None and learned.page == "card_editor":
                core_page = False
                ready = False
            if (
                learned is not None
                and not core_page
                and not getattr(self, "pending_mastery", False)
                and not getattr(self, "pending_claim_all", False)
            ):
                ready = False
            if (
                not core_page
                and not getattr(self, "pending_mastery", False)
                and not getattr(self, "pending_claim_all", False)
                and page_returns < 12
                and self.device.foreground_package() == CLASH_ROYALE_PACKAGE
                and self._return_known_page(frame, expected="startup")
            ):
                # A detail opened from card information has a different parent
                # from a detail opened by the owned mastery workflow. Normalize
                # manual navigation one observed step at a time before resuming.
                page_returns += 1
                continue
            if ready and self.device.foreground_package() == CLASH_ROYALE_PACKAGE:
                self._awaiting_relaunch_observation = False
                return frame
            if (
                page_returns < 12
                and self.device.foreground_package() == CLASH_ROYALE_PACKAGE
                and self._return_known_page(frame, expected="startup")
            ):
                page_returns += 1
                continue
            time.sleep(0.5)
        raise RecoveryExhausted("90秒内未进入可识别的已登录游戏页面；暂停")

    def _pending_startup_lobby(self, frame):
        """An idle, logged-in lobby can close an unconfirmed match attempt."""
        kind, match = self.vision.classify(frame)
        return (
            kind == "lobby"
            and match is not None
            and not self.pending_mastery
            and not self.pending_claim_all
            and self.vision.find(frame, "battle_hud") is None
            and not self.vision.reward_continuation(frame)
            and self.device.foreground_package() == CLASH_ROYALE_PACKAGE
        )

    def _reconcile_pending_startup(self, frame):
        """Preserve an unresolved attempt before a user-started idle restart.

        Automatic recovery inside an active battle keeps its stricter guard:
        only this initial startup may reconcile a stable, idle main menu.
        A lobby never supplies a battle result or a completed-cycle count.
        """
        if not self.pending_battle or self.vision.classify(frame)[0] in ("battle", "result"):
            return frame
        if not self._pending_startup_lobby(frame):
            raise RecoveryExhausted("启动时未确认待续本局对战或结算; 保留断点, 不开新局")
        first_evidence = self._save("pending-battle-lobby", frame)
        time.sleep(1.0)
        fresh = self._frame()
        if self.vision.classify(fresh)[0] in ("battle", "result"):
            return fresh
        if not self._pending_startup_lobby(fresh):
            raise RecoveryExhausted("启动时未确认稳定空闲大厅; 保留断点, 不开新局")
        observations = [first_evidence, self._save("pending-battle-lobby", fresh)]
        archive_path = self.work / f"unresolved-battle-{self.completed + 1:04d}-{uuid.uuid4().hex[:12]}.json"
        archive = {
            "schema": 1,
            "event": "pending_battle_unresolved",
            "reason": "startup_confirmed_idle_lobby",
            "session": self.session,
            "battle": self.completed + 1,
            "generation": self.generated,
            "checkpoint_before": self._checkpoint_data(),
            "card_attempts": self.card_attempts,
            "cards_confirmed": self.cards_confirmed,
            "observations": observations,
            "confirmation_interval_seconds": 1.0,
            "counts_as_completed": False,
        }
        # The immutable checkpoint snapshot and both lobby observations must
        # be durable before changing the live checkpoint. Keep the result
        # outbox intact: an older committed result is a separate receipt.
        atomic_write_json(archive_path, archive)
        self._event(
            "pending_battle_unresolved",
            archive=str(archive_path),
            reason=archive["reason"],
            generation=self.generated,
            counts_as_completed=False,
            observations=observations,
        )
        self.pending_battle = False
        try:
            self._checkpoint()
        except Exception:
            self.pending_battle = True
            raise
        self.cards_confirmed = self.card_attempts = 0
        self.last_action = {}
        self.logger.info("已两次确认空闲主大厅；旧匹配断点保留为未确认中断记录，已完成场次不变：%d", self.completed)
        return fresh

    def _finish_limited_run(self, max_battles, starting_completed):
        added = self.completed - starting_completed
        drain = getattr(self, "drain_path", None)
        draining = drain is not None and drain.is_file()
        if not draining and (not max_battles or added < max_battles):
            return False
        self._navigate(PAGE_CN_CARD, PAGE_CN_MAIN)
        self.state = "stopped"
        values = {
            "target": max_battles,
            "session_completed": added,
            "starting_completed": starting_completed,
            "total_completed": self.completed,
        }
        if draining:
            values["drained"] = True
        self._event("finite_complete", **values)
        return True

    def run_forever(self, max_battles=0):
        starting_completed = self.completed
        self.logger.info("国服 1v1 连续对战已启动，策略=随机卡组+卡牌大师；0局上限表示无限")
        self._event("started", max_battles=max_battles, starting_completed=starting_completed)
        try:
            frame = self._startup_frame()
            frame = self._reconcile_pending_startup(frame)
            kind, _ = self.vision.classify(frame)
            self._event(
                "startup_ready",
                kind=kind,
                pages=[
                    name
                    for name in ("deck", "collection", "mastery_list", "mastery_detail", "mastery_locked")
                    if random_ui_is(frame, name)
                ],
                evidence=self._save("startup", frame),
            )
            if kind in ("battle", "result") and self.pending_battle:
                self._battle(resumed=True)
                frame = self._frame()
                kind, _ = self.vision.classify(frame)
            elif kind == "battle":
                raise RecoveryExhausted("当前对局没有本循环的换卡组断点；未接管其他对局")
            elif kind in ("result", "reward") and self.pending_mastery:
                if not self.pending_claim_all:
                    self._return_from_result()
                    frame = self._frame()
            elif (
                self.pending_mastery
                and not self.pending_claim_all
                and (self._post_battle_puzzle_action(frame) is not None or self.vision.reward_continuation(frame))
            ):
                self._return_from_result()
                frame = self._frame()
            if self.pending_claim_all and any(
                random_ui_is(frame, name) for name in ("mastery_reward_continue", "mastery_reward_coin")
            ):
                self._event("resume_claim_reward")
                self._claim_all_return()
                self._require("mastery_list")
                self._tap(CN_RANDOM_MODAL_CLOSE)
                frame = self._frame()
            if not self.pending_claim_all and random_ui_is(frame, "collection"):
                # Collection pages do not show the selected battle mode. Return
                # to the lobby and verify Classic 1v1 before entering its deck.
                if not self._return_known_page(frame, expected="classic_lobby"):
                    raise RecoveryExhausted("收藏页面尚未确认返回大厅路径；未切卡组或开局")
                frame = self._frame()
            if self.vision.classify(frame)[0] == "lobby":
                frame = self._prepare_classic_lobby(frame, verify_menu=True)
                self._navigate(PAGE_CN_MAIN, PAGE_CN_CARD)
            elif any(random_ui_is(frame, name) for name in ("mastery_detail", "mastery_locked")):
                self._close_detail()
                self._require("mastery_list")
                self._tap(CN_RANDOM_MODAL_CLOSE)
            elif random_ui_is(frame, "mastery_list"):
                self._tap(CN_RANDOM_MODAL_CLOSE)
            self._require("deck")
            if self.pending_mastery:
                self._event("resume_pending_mastery", completed_battle=self.completed)
                self._mastery()
                self.closed_loops += 1
                self.pending_mastery = False
                self._checkpoint()
                self._event("cycle_complete", completed_battle=self.completed, resumed=True)
                self.recovery_attempts = 0
                if self._finish_limited_run(max_battles, starting_completed):
                    return
            while True:
                self._new_deck()
                self._navigate(PAGE_CN_CARD, PAGE_CN_MAIN)
                self._battle()
                self._navigate(PAGE_CN_MAIN, PAGE_CN_CARD)
                self._mastery()
                self.closed_loops += 1
                self.pending_mastery = False
                self._checkpoint()
                cycle = {
                    "battle": self.completed,
                    "generated_decks": self.generated,
                    "claim_all_batches": self.total_claimed,
                    "closed_loops": self.closed_loops,
                }
                self._event("cycle_complete", **cycle)
                self.recovery_attempts = 0
                (self.work / f"cycle-{self.completed:04d}.json").write_text(
                    json.dumps(cycle, indent=2), encoding="utf-8"
                )
                if self._finish_limited_run(max_battles, starting_completed):
                    return
        except KeyboardInterrupt:
            self.state = "stopped"
            self._event("user_stopped")
            raise
        except Exception as error:
            self.state = "paused"
            self._event("paused", reason=str(error))
            if isinstance(error, RecoveryExhausted):
                raise
            raise RecoveryExhausted(str(error)) from error
