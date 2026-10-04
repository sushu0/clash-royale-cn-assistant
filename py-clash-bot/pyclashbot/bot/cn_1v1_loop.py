# ruff: noqa: RUF001
# Native Chinese punctuation and multiplication glyphs are intentional UI/OCR text.
"""Small Tencent-client battle loop using the project's ADB and image primitives.

Only the lobby, active battle, result and connection dialog are recognized. The
reference crops and friendly deployment points must come from live screenshots.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np

from pyclashbot.bot.card_detection import identify_567_hand_frame, identify_hog_hand_frame
from pyclashbot.bot.coords import (
    CN_BATTLE_CLOCK_ROI,
    CN_CLASSIC_MODE_ICON_ROI,
    CN_DECK_CLOSE,
    CN_DECK_PREVIEW,
    CN_FOUR_STAR_REWARD_BG_POINTS,
    CN_FRIENDLY_DROP_POINTS,
    CN_POST_WIN_REWARD_TAP,
    CN_RESULT_LOSS_YELLOW_ROI,
    CN_REWARD_BACKGROUND_ROI,
    CN_REWARD_FLOOR_ROI,
    CN_REWARD_FLOOR_SEARCH_ROI,
    CN_REWARD_PURPLE_FLOOR_SEARCH_ROI,
    CN_REWARD_PUZZLE_TITLE_ROI,
    CN_REWARD_UNLOCKED_ROI,
    CN_REWARD_UNOPENED_CHEST_SEARCH_ROI,
    HAND_CARDS_COORDS,
)
from pyclashbot.bot.double_air_567_strategy import COSTS as COSTS_567
from pyclashbot.bot.double_air_567_strategy import POLICY_VERSION as POLICY_567
from pyclashbot.bot.double_air_567_strategy import DoubleAir567Strategy
from pyclashbot.bot.elite_ice_golem_ability import EliteIceGolemAbility
from pyclashbot.bot.hog_cycle_strategy import COSTS, MIN_ACTION_INTERVAL, HogCycleStrategy
from pyclashbot.bot.nav import navigate_cn_classic_1v1, recover_cn_page_once
from pyclashbot.detection.cn_567_deck import read_567_deck
from pyclashbot.detection.cn_battle_cues import read_cn_battle_cues
from pyclashbot.detection.cn_daily_gift import daily_gift_action
from pyclashbot.detection.cn_page_navigation import cn_game_exit_cancel, cn_navigation_step
from pyclashbot.emulators.adb import AdbController
from pyclashbot.emulators.base import CLASH_ROYALE_PACKAGE
from pyclashbot.utils.image_handler import open_from_path
from pyclashbot.utils.persistence import atomic_write_json
from pyclashbot.utils.runtime_config import environment_identity, load_runtime_config, resource_path, source_path

if TYPE_CHECKING:
    import logging

TEMPLATES = resource_path("pyclashbot/detection/reference_images/cn_minimal")
MANDATORY_TEMPLATES = ("lobby_start", "battle_hud", "result_continue")
THRESHOLDS = {
    "lobby_start": 0.87,
    "battle_hud": 0.88,
    "result_continue": 0.86,
    "result_classic_continue": 0.90,
    "result_loss": 0.90,
    "result_loss_alt": 0.87,
    "result_loss_yellow": 0.90,
    "result_loss_yellow_confetti": 0.90,
    "result_win": 0.87,
    "reward_star": 0.90,
    "reward_floor": 0.85,
    "reward_chest_unopened": 0.92,
    "reward_purple_floor": 0.88,
    "reward_puzzle_title": 0.90,
    "reward_unlocked": 0.90,
    "reward_unlocked_small": 0.90,
    "reward_rainbow_open": 0.92,
    "connection_confirm": 0.86,
    "connection_interrupted": 0.94,
}
SEARCH_REGIONS = {
    "lobby_start": (135, 450, 285, 535),
    "battle_hud": (30, 510, 110, 575),
    "result_continue": (195, 540, 330, 615),
    "result_classic_continue": (145, 530, 285, 615),
    "result_loss": (150, 38, 265, 100),
    "result_loss_alt": (150, 38, 265, 100),
    "result_loss_yellow": CN_RESULT_LOSS_YELLOW_ROI,
    "result_loss_yellow_confetti": CN_RESULT_LOSS_YELLOW_ROI,
    "result_win": (145, 228, 273, 290),
    "reward_star": (80, 80, 338, 220),
    "reward_floor": CN_REWARD_FLOOR_SEARCH_ROI,
    "reward_chest_unopened": CN_REWARD_UNOPENED_CHEST_SEARCH_ROI,
    "reward_purple_floor": CN_REWARD_PURPLE_FLOOR_SEARCH_ROI,
    "reward_puzzle_title": CN_REWARD_PUZZLE_TITLE_ROI,
    "reward_unlocked": CN_REWARD_UNLOCKED_ROI,
    "reward_unlocked_small": CN_REWARD_UNLOCKED_ROI,
    "reward_rainbow_open": (150, 560, 270, 620),
    "connection_confirm": (40, 130, 380, 510),
    "connection_interrupted": (40, 245, 165, 330),
}
POLL_SECONDS = 0.45
BATTLE_POLL_SECONDS = 0.18
MATCH_TIMEOUT = 150
BATTLE_TIMEOUT = 7 * 60
RESULT_TIMEOUT = 90
LOBBY_TIMEOUT = 180
TASK_ROOT = load_runtime_config().data_root
STRATEGY_TRACE = TASK_ROOT / "outputs" / "cn-hog-strategy.jsonl"
POLICY_VERSION = "hog-v5n-lethal-tower-priority-winrate33-20260927"
CLOCK_STALL_TIMEOUT = 45.0


class RecoveryExhausted(Exception):  # noqa: N818 - Public exception name retained for caller compatibility.
    """Explicit terminal fault; must not be swallowed by generic recovery."""


class ModeOrDeckMismatch(RecoveryExhausted):
    pass


class _LogAdapter:
    """Keep the upstream ADB controller's status API out of the concise log."""

    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def log(self, message: str) -> None:
        self.logger.debug(message)

    def change_status(self, status: str) -> None:
        self.logger.debug(status)


class TimedAdbController(AdbController):
    """Bound local ADB calls so a temporary disconnect cannot stall the loop."""

    def adb(self, command: str, binary_output: bool = False, timeout: float | None = 30) -> subprocess.CompletedProcess:
        return super().adb(command, binary_output=binary_output, timeout=timeout)


@dataclass(frozen=True)
class Match:
    x: int
    y: int
    width: int
    height: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)


class ChineseVision:
    def __init__(self) -> None:
        missing = [name for name in MANDATORY_TEMPLATES if not (TEMPLATES / f"{name}.png").is_file()]
        if missing:
            raise RuntimeError(f"Live Chinese screenshots must be calibrated first: {', '.join(missing)}")
        self.templates = {
            path.stem: open_from_path(str(path)) for path in TEMPLATES.glob("*.png") if path.stem in THRESHOLDS
        }
        for name, template in self.templates.items():
            minimum_std = 3 if name.endswith("_floor") else 12
            if np.std(cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)) < minimum_std:
                raise ValueError(f"Template {name} has too little detail for reliable matching")

    def find(self, frame: np.ndarray, name: str) -> Match | None:
        template = self.templates.get(name)
        if template is None:
            return None
        x1, y1, x2, y2 = SEARCH_REGIONS[name]
        region = frame[y1:y2, x1:x2]
        if region.shape[0] < template.shape[0] or region.shape[1] < template.shape[1]:
            return None
        frame_gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        if name in {"reward_puzzle_title", "reward_unlocked", "reward_unlocked_small"}:
            # Match the white glyphs, not the rarity-dependent sky gradient.
            def glyph_mask(image):
                hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
                return ((hsv[:, :, 1] <= 55) & (hsv[:, :, 2] >= 205)).astype(np.uint8) * 255

            frame_gray, template_gray = glyph_mask(region), glyph_mask(template)
        scores = cv2.matchTemplate(frame_gray, template_gray, cv2.TM_CCOEFF_NORMED)
        _, score, _, (x, y) = cv2.minMaxLoc(scores)
        if score < THRESHOLDS[name]:
            return None
        return Match(x + x1, y + y1, template.shape[1], template.shape[0])

    def classify(self, frame: np.ndarray) -> tuple[str, Match | None]:
        # This exact crop contains both "connection interrupted" and "please
        # log in again". An Android overlay takes precedence over the dimmed game.
        interrupted = self.find(frame, "connection_interrupted")
        if interrupted is not None:
            return "connection_interrupted", interrupted
        rainbow_open = self.find(frame, "reward_rainbow_open")
        if rainbow_open:
            return "reward", rainbow_open
        puzzle_title = self.find(frame, "reward_puzzle_title")
        if puzzle_title and (self.find(frame, "reward_unlocked") or self.find(frame, "reward_unlocked_small")):
            return "reward", puzzle_title
        reward_star = self.find(frame, "reward_star")
        if reward_star and (
            self.find(frame, "reward_floor")
            or self.find(frame, "reward_purple_floor")
            or self.unopened_star_reward(frame)
        ):
            return "reward", reward_star
        for name, kind in (
            ("connection_confirm", "connection"),
            ("result_classic_continue", "result"),
            ("result_continue", "result"),
            ("lobby_start", "lobby"),
            ("battle_hud", "battle"),
        ):
            match = self.find(frame, name)
            if match is not None:
                if kind == "lobby" and cn_navigation_step(frame) is not None:
                    return "navigation", None
                return kind, match
        if cn_navigation_step(frame) is not None:
            return "navigation", None
        return "unknown", None

    def outcome(self, frame: np.ndarray) -> str:
        if self.find(frame, "result_win"):
            return "胜利"
        if any(
            self.find(frame, name)
            for name in (
                "result_loss",
                "result_loss_alt",
                "result_loss_yellow",
                "result_loss_yellow_confetti",
            )
        ):
            return "失败"
        # Confetti can hide every small title template. On an already
        # recognized result page, the golden crown rows remain separated:
        # opponent crowns are above the banner, ours below it. Replay against
        # 60 frozen result frames included both earlier raw-unknown losses.
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        gold = (hsv[:, :, 0] >= 10) & (hsv[:, :, 0] <= 45) & (hsv[:, :, 1] >= 100) & (hsv[:, :, 2] >= 140)
        opponent = int(np.count_nonzero(gold[85:145, 80:340]))
        own = int(np.count_nonzero(gold[280:345, 80:340]))
        if opponent >= 1800 and opponent - own >= 1000:
            return "失败"
        if own >= 1800 and own - opponent >= 1000:
            return "胜利"
        return "未知"

    def classic_selected(self, frame: np.ndarray) -> bool:
        path = TEMPLATES.parent / "cn_567" / "classic_icon.png"
        template = cv2.imread(str(path))
        if template is None:
            return False
        x1, y1, x2, y2 = CN_CLASSIC_MODE_ICON_ROI
        patch = frame[y1:y2, x1:x2]
        return (
            patch.shape == template.shape
            and float(cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED)[0, 0]) >= 0.94
        )

    def unopened_star_reward(self, frame: np.ndarray) -> bool:
        """Recognize a free starred chest despite animation of its checkerboard."""
        if not isinstance(frame, np.ndarray) or frame.shape != (633, 419, 3):
            return False
        if not (self.find(frame, "reward_star") and self.find(frame, "reward_chest_unopened")):
            return False
        x1, y1, x2, y2 = CN_REWARD_BACKGROUND_ROI
        sky = frame[y1:y2, x1:x2]
        hsv = cv2.cvtColor(sky, cv2.COLOR_BGR2HSV)
        blue_or_purple = (hsv[:, :, 0] >= 100) & (hsv[:, :, 0] <= 165) & (hsv[:, :, 1] >= 100) & (hsv[:, :, 2] >= 30)
        edges = cv2.Canny(cv2.cvtColor(sky, cv2.COLOR_BGR2GRAY), 20, 60)
        return bool(np.mean(blue_or_purple) >= 0.90 and np.mean(edges > 0) < 0.025)

    def reward_continuation(self, frame: np.ndarray) -> bool:
        """Only used within an already recognized free reward sequence."""
        if self.four_star_reward(frame):
            return True
        if self.unopened_star_reward(frame):
            return True
        x1, y1, x2, y2 = CN_REWARD_BACKGROUND_ROI
        hsv = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
        blue_or_purple = (hsv[:, :, 0] >= 100) & (hsv[:, :, 0] <= 165) & (hsv[:, :, 1] >= 100) & (hsv[:, :, 2] >= 30)
        if np.mean(blue_or_purple) >= 0.90 and (
            self.find(frame, "reward_floor") or self.find(frame, "reward_purple_floor")
        ):
            return True
        # Revealed puzzle rewards have the same blue checkerboard but a
        # different glow; legendary reveals also change the sky's hue. Require
        # the characteristic floor and a quiet upper background without HUD,
        # not one hardcoded sky color. The caller still requires reward context.
        top_gray = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
        top_edges = float(np.mean(cv2.Canny(top_gray, 20, 60) > 0))
        x1, y1, x2, y2 = CN_REWARD_FLOOR_ROI
        floor = frame[y1:y2, x1:x2]
        hsv = cv2.cvtColor(floor, cv2.COLOR_BGR2HSV)
        color = (hsv[:, :, 0] >= 100) & (hsv[:, :, 0] <= 165) & (hsv[:, :, 1] >= 100) & (hsv[:, :, 2] >= 30)
        gray = cv2.cvtColor(floor, cv2.COLOR_BGR2GRAY)
        edges = float(np.mean(cv2.Canny(gray, 20, 60) > 0))
        return bool(top_edges < 0.025 and np.mean(color) >= 0.95 and 0.015 <= edges <= 0.10 and np.std(gray) >= 5)

    @staticmethod
    def four_star_reward(frame: np.ndarray) -> bool:
        """Observed pink sky and teal floor during the four-star reveal.

        This is only allowed as a continuation after another reward was already
        recognized. It is not a general screen classifier or a chest feature.
        """
        if not isinstance(frame, np.ndarray) or frame.shape != (633, 419, 3):
            return False
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        samples = []
        for x, y in CN_FOUR_STAR_REWARD_BG_POINTS:
            samples.append(np.median(hsv[y - 5 : y + 6, x - 5 : x + 6].reshape(-1, 3), axis=0))
        sky = samples[:2]
        floor = samples[2:]
        return bool(
            all(165 <= hue <= 179 and sat >= 70 and value >= 180 for hue, sat, value in sky)
            and all(65 <= hue <= 100 and sat >= 90 and value >= 115 for hue, sat, value in floor)
        )


class ChineseOneVOneLoop:
    def __init__(
        self,
        adb_path: str,
        serial: str,
        logger: logging.Logger,
        memuc_path: str | None = None,
        vm_index: int = 0,
        strategy_name: str = "567",
    ) -> None:
        if not CN_FRIENDLY_DROP_POINTS:
            raise RuntimeError("Calibrate CN_FRIENDLY_DROP_POINTS from a real Chinese 1v1 screenshot first")
        TimedAdbController.adb_path = adb_path
        self.device = TimedAdbController(_LogAdapter(logger), device_serial=serial)
        if not self.device.is_app_installed(CLASH_ROYALE_PACKAGE):
            raise RuntimeError(f"Tencent game is not installed: {CLASH_ROYALE_PACKAGE}")
        self.vision = ChineseVision()
        self.logger = logger
        if strategy_name not in {"567", "hog"}:
            raise ValueError("Unknown strategy")
        self.strategy_name = strategy_name
        self.policy_version = POLICY_567 if strategy_name == "567" else POLICY_VERSION
        self.costs = COSTS_567 if strategy_name == "567" else COSTS
        self.identify_hand = identify_567_hand_frame if strategy_name == "567" else identify_hog_hand_frame
        self.trace_path = (
            TASK_ROOT / "outputs" / ("cn-567-strategy.jsonl" if strategy_name == "567" else "cn-hog-strategy.jsonl")
        )
        self.deck_verified = False
        self.recovery_attempts = 0
        self.closed_loops = 0
        self.gate_passed = False
        self.cycle_pending = False
        self.returned_lobby = False
        self.result_counts = {"胜利": 0, "失败": 0, "未知": 0}
        self.total_deployment_failures = 0
        self.serial = serial
        self.memu_path = Path(memuc_path) if memuc_path else None
        self.vm_index = vm_index
        self.state = "lobby"
        self.state_since = time.monotonic()
        self.last_card_at = 0.0
        self.no_card_since = 0.0
        self.completed = 0
        self.consecutive = 0
        self.match_retries = 0
        self.battle_confirmations = 0
        self.result_confirmations = 0
        self.lobby_confirmations = 0
        self.card_attempts = 0
        self.cards_confirmed = 0
        self.card_failures = 0
        self.strategy: HogCycleStrategy | DoubleAir567Strategy | None = None
        self.elite_ability = EliteIceGolemAbility()
        self.last_observation_log = 0.0
        self.validation_dir = (
            TASK_ROOT
            / "work"
            / ("567-validation" if strategy_name == "567" else "hog-validation")
            / time.strftime("%Y%m%d-%H%M%S")
        )
        self.validation_frames_saved = 0
        self.reward_taps = 0
        self.reward_pending = False
        self.last_reward_tap_at = 0.0
        self.last_four_star_tap_at = 0.0
        self.four_star_reward_seen = False
        self.evidence_counts: dict[str, int] = {}
        self.last_unknown_evidence = 0.0
        self.clock_mask: np.ndarray | None = None
        self.clock_changed_at = time.monotonic()
        STRATEGY_TRACE.parent.mkdir(parents=True, exist_ok=True)
        source_paths = [
            *(
                source_path("pyclashbot/" + name)
                for name in (
                    "bot/cn_1v1_loop.py",
                    "bot/hog_cycle_strategy.py",
                    "bot/double_air_567_strategy.py",
                    "bot/card_detection.py",
                    "bot/coords.py",
                    "bot/nav.py",
                    "bot/state_detect.py",
                    "bot/elite_ice_golem_ability.py",
                    "detection/cn_battle_cues.py",
                    "detection/cn_threats.py",
                    "detection/cn_567_deck.py",
                    "detection/cn_daily_gift.py",
                    "detection/cn_page_navigation.py",
                    "emulators/adb_base.py",
                    "emulators/base.py",
                )
            ),
        ]
        self.policy_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}
        environment = environment_identity()
        self.experiment = {
            "rule_version": self.policy_version,
            "strategy_hash": self.policy_hashes[
                "double_air_567_strategy.py" if strategy_name == "567" else "hog_cycle_strategy.py"
            ],
            "environment_hash": environment["sha256"],
        }
        image_root = TEMPLATES.parent
        self.asset_hashes = {
            str(path.relative_to(image_root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for folder in (
                TEMPLATES,
                image_root / "cn_enemy_tags",
                image_root / "cn_threats",
                image_root / "cn_567",
                image_root / "cn_567_threats",
                image_root / "cn_daily_gift",
                image_root / "cn_pages",
            )
            for path in sorted(folder.rglob("*"))
            if path.is_file() and path.suffix.lower() in {".png", ".json"}
        }
        self.validation_dir.mkdir(parents=True, exist_ok=True)
        self.experiment["asset_hash"] = hashlib.sha256(
            json.dumps(self.asset_hashes, sort_keys=True).encode()
        ).hexdigest()
        (self.validation_dir / "policy-manifest.json").write_text(
            json.dumps(
                {
                    "version": self.policy_version,
                    "mode": "classic_1v1",
                    "source_sha256": self.policy_hashes,
                    "asset_sha256": self.asset_hashes,
                    "experiment": self.experiment,
                    "environment": environment,
                    "environment_hash": environment["sha256"],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def _set_state(self, state: str) -> None:
        self.state = state
        self.state_since = time.monotonic()

    def _tap(self, point: tuple[int, int]) -> None:
        self.device.click(*point)

    def _save_evidence(self, category: str, frame: np.ndarray) -> dict:
        """Keep every result, and bounded recent action/observation evidence.

        The hash lets readers detect when a circular slot has been overwritten.
        Historical trace rows must not be paired with a newer image in that slot.
        """
        sequence = self.evidence_counts.get(category, 0)
        self.evidence_counts[category] = sequence + 1
        filename = (
            f"result-evidence-{sequence:05d}.png"
            if category == "result"
            else f"recent-{category}-{sequence % 80:02d}.png"
        )
        path = self.validation_dir / filename
        ok, encoded = cv2.imencode(".png", frame)
        if not ok:
            return {"error": "PNG encoding failed"}
        data = encoded.tobytes()
        path.write_bytes(data)
        return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "sequence": sequence}

    def _clock_stalled(self, frame: np.ndarray, now: float) -> bool:
        """Detect a frozen battle clock; no OCR or assumed match duration."""
        x1, y1, x2, y2 = CN_BATTLE_CLOCK_ROI
        patch = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
        mask = (patch[:, :, 1] < 90) & (patch[:, :, 2] > 180)
        if self.clock_mask is None or np.mean(mask != self.clock_mask) > 0.004:
            self.clock_mask = mask.copy()
            self.clock_changed_at = now
        return now - self.clock_changed_at >= CLOCK_STALL_TIMEOUT

    def _reconnect(self) -> None:
        try:
            state = self.device.adb("get-state", timeout=5)
            if state.returncode == 0 and (state.stdout or "").strip() == "device":
                return
        except (OSError, subprocess.TimeoutExpired):
            pass
        if self.memu_path and self.memu_path.is_file():
            try:
                if self.vm_index != 0:
                    raise RecoveryExhausted("自动重连只允许本任务的 0 号模拟器; 已停止启动")
                vm = subprocess.run(
                    [str(self.memu_path), "isvmrunning", "-i", "0"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
                vm_state = (vm.stdout or "").strip().lower()
                if vm.returncode != 0 or vm_state not in {"running", "notrunning"}:
                    raise RecoveryExhausted("无法确认模拟器运行状态; 已停止启动")
                if vm_state == "notrunning":
                    listed = subprocess.run(
                        [str(self.memu_path), "listvms"],
                        capture_output=True,
                        text=True,
                        timeout=15,
                        check=False,
                    )
                    rows = [line.strip().split(",", 1) for line in (listed.stdout or "").splitlines() if line.strip()]
                    if listed.returncode != 0 or len(rows) != 1 or len(rows[0]) != 2 or rows[0][0] != "0":
                        raise RecoveryExhausted("只能自动启动唯一的 0 号 MEmu 实例; 已停止启动")
                    executable = self.memu_path.with_name("MEmu.exe")
                    if not executable.is_file():
                        raise RecoveryExhausted("缺少同目录 MEmu.exe; 已停止启动")
                    # The installed GUI preserves this VM's disk attachments;
                    # memuc start may rewrite them on this installation.
                    subprocess.Popen(
                        [str(executable)],
                        cwd=self.memu_path.parent,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    deadline = time.monotonic() + 90
                    while time.monotonic() < deadline:
                        state = self.device.adb("get-state", timeout=8)
                        if state.returncode == 0 and (state.stdout or "").strip() == "device":
                            return
                        if ":" in self.serial:
                            self.device.adb(f"connect {self.serial}", timeout=10)
                        time.sleep(2)
                    raise RecoveryExhausted("模拟器启动后90秒内 ADB 未就绪; 保留数据并暂停")
            except (OSError, subprocess.TimeoutExpired) as error:
                raise RecoveryExhausted("模拟器状态查询或启动失败; 保留数据并暂停") from error
        if ":" in self.serial:
            try:
                self.device.adb(f"connect {self.serial}", timeout=20)
            except (OSError, subprocess.TimeoutExpired) as error:
                self.logger.warning("ADB 重连命令失败: %s", error)

    def _recover(self, reason: str) -> None:
        self._classic_menu_verified = False
        self.recovery_attempts += 1
        self.closed_loops = 0
        self.cycle_pending = False
        if self.recovery_attempts > 3:
            self._trace({"event": "fatal", "reason": reason, "recovery_attempts": self.recovery_attempts})
            self.logger.error("异常恢复连续三次未恢复完整闭环，停止并报错: %s", reason)
            raise RecoveryExhausted(reason)
        self.logger.warning("恢复/重启: %s; 连续完成数=%d", reason, self.consecutive)
        if self.reward_pending:
            self.last_reward_tap_at = time.monotonic()
        self._trace({"event": "recovery", "battle": self.completed + 1, "state": self.state, "reason": reason})
        self.consecutive = 0
        try:
            self._reconnect()
            self.device.adb(f"shell am force-stop {CLASH_ROYALE_PACKAGE}", timeout=20)
            self.device.start_app(CLASH_ROYALE_PACKAGE)
        except (OSError, subprocess.TimeoutExpired, RuntimeError) as error:
            self.logger.warning("重启尝试失败: %s", error)
            time.sleep(10)
        self.match_retries = 0
        self.battle_confirmations = 0
        self.result_confirmations = 0
        self.lobby_confirmations = 0
        self.reward_taps = 0
        self._set_state("lobby")

    def _play_card(self, frame: np.ndarray) -> None:
        now = time.monotonic()
        if self.strategy is None:
            return
        hand = self.identify_hand(frame)
        cues = self._read_cues(frame)
        self._track_opening(cues, now, frame)
        extra = {"allies": cues.get("allies", [])} if self.strategy_name == "567" else {}
        decision = self.strategy.decide(
            hand,
            cues["elixir"],
            cues["enemies"],
            now,
            cues.get("enemy_towers"),
            threats=cues.get("threats"),
            far_warnings=cues.get("far_warnings"),
            enemy_tower_fill=cues.get("enemy_tower_fill"),
            own_tower_fill=cues.get("own_tower_fill"),
            dark_ground_candidates=cues.get("dark_ground_candidates"),
            **extra,
        )
        ability = self.elite_ability.decide(cues, now) if self.strategy_name == "hog" else None
        # A confirmed Ice Golem lead must not lose its Hog follow-up budget to
        # an optional skill tap. Emergency defense has already taken precedence
        # inside the policy before it returns any Hog decision.
        hog_followup = decision is not None and decision.category == "attack"
        if ability is not None and not hog_followup and now - self.strategy.last_attempt >= MIN_ACTION_INTERVAL:
            self._use_elite_ability(frame, cues, ability)
            return
        if decision is None:
            if now - self.last_observation_log >= 10:
                self._trace(
                    {
                        "event": "observe",
                        "battle": self.completed + 1,
                        "hand": hand,
                        "cues": cues,
                        "policy_observation": getattr(self.strategy, "observation", {}),
                        "evidence": self._save_evidence("observe", frame),
                    }
                )
                if self.completed < 5:
                    self.validation_dir.mkdir(parents=True, exist_ok=True)
                    cv2.imwrite(
                        str(self.validation_dir / f"observe-{self.completed + 1:02d}-{time.strftime('%H%M%S')}.png"),
                        frame,
                    )
                self.last_observation_log = now
            return
        self.last_card_at = now
        card_x, card_y = HAND_CARDS_COORDS[decision.slot]
        self.card_attempts += 1
        deploy_started = time.monotonic()
        self._tap((card_x, card_y))
        time.sleep(0.12)
        self._tap(decision.point)
        deploy_finished = time.monotonic()
        time.sleep(0.45)
        confirmation_passes = 3 if self.costs[decision.card] == 1 else 2
        for confirmation_pass in range(confirmation_passes):
            after_frame = self.device.screenshot()
            after_hand = self.identify_hand(after_frame)
            after_cues = self._read_cues(after_frame)
            after_card = after_hand[decision.slot]["card"]
            before_elixir, after_elixir = cues["elixir"], after_cues["elixir"]
            changed_card = after_card is not None and after_card != decision.card
            spent = (before_elixir - after_elixir) if before_elixir is not None and after_elixir is not None else 0
            paid_cost = spent > 0 and spent >= max(1, self.costs[decision.card] - 1)
            still_battle = self.vision.classify(after_frame)[0] == "battle"
            confirmed = still_battle and (changed_card or paid_cost)
            if confirmed or not still_battle:
                break
            if confirmation_pass < confirmation_passes - 1:
                time.sleep(0.45)  # allow hand replacement when regeneration masks a one-elixir cost
        confirmed_at = time.monotonic()
        self.strategy.record(decision, confirmed, confirmed_at)
        if decision.card == "bomber":
            form = (
                "evolved"
                if decision.variant in {"evo_bomber", "cn_evo_bomber"}
                else "normal"
                if decision.variant == "bomber"
                else "uncertain"
            )
            counts = self.bomber_forms.setdefault(form, {"attempts": 0, "confirmed": 0})
            counts["attempts"] += 1
            counts["confirmed"] += int(confirmed)
            self.logger.info("炸弹兵形态=%s 类别=%s 部署确认=%s", form, decision.category, confirmed)
        self._trace(
            {
                "event": "play",
                "battle": self.completed + 1,
                "decision": asdict(decision),
                "hand": hand,
                "cues": cues,
                "after_hand": after_hand,
                "after_cues": after_cues,
                "policy_observation": getattr(self.strategy, "observation", {}),
                "after_elixir": after_elixir,
                "confirmed": confirmed,
                "changed_card": changed_card,
                "observed_spend": spent,
                "timing_ms": {
                    "decision": round((deploy_started - now) * 1000, 1),
                    "deploy": round((deploy_finished - deploy_started) * 1000, 1),
                    "confirmation": round((confirmed_at - deploy_finished) * 1000, 1),
                    "total": round((confirmed_at - now) * 1000, 1),
                },
                "evidence_before": self._save_evidence("play-before", frame),
                "evidence_after": self._save_evidence("play-after", after_frame),
            }
        )
        if self.validation_frames_saved < 16:
            self.validation_dir.mkdir(parents=True, exist_ok=True)
            prefix = f"play-{self.validation_frames_saved:02d}-{decision.card}"
            cv2.imwrite(str(self.validation_dir / f"{prefix}-before.png"), frame)
            cv2.imwrite(str(self.validation_dir / f"{prefix}-after.png"), after_frame)
            self.validation_frames_saved += 1
        if confirmed:
            self.cards_confirmed += 1
            self.card_failures = 0
            self.elite_ability.deployed(decision.variant, decision.point, time.monotonic())
        else:
            self.card_failures += 1
            self.total_deployment_failures += 1
            if self.card_failures % 5 == 0:
                self.logger.warning("出牌未确认，累计失败=%d；继续等待圣水并重试", self.card_failures)
            if self.card_failures >= 12:
                self._recover("连续12次部署未确认")

    def _read_cues(self, frame):
        return read_cn_battle_cues(frame, include_567=self.strategy_name == "567")

    def _verify_deck(self):
        """Read the already selected deck through its ordinary preview panel."""
        self._tap(CN_DECK_PREVIEW)
        time.sleep(1)
        frame = self.device.screenshot()
        result = read_567_deck(frame)
        scores = [item["score"] for item in result["matches"]]
        evidence = self._save_evidence("deck-preflight", frame)
        self._trace({"event": "deck_preflight", "scores": scores, "deck": result, "evidence": evidence})
        if not result["valid"]:
            raise ModeOrDeckMismatch("当前卡组与已核实八张牌不匹配；保留画面，未开局")
        self._tap(CN_DECK_CLOSE)
        time.sleep(0.8)
        fresh = self.device.screenshot()
        if self.vision.classify(fresh)[0] != "lobby" or not self.vision.classic_selected(fresh):
            raise ModeOrDeckMismatch("卡组检查后未确认经典1V1大厅")
        self.deck_verified = True

    def _track_opening(self, cues, now, frame):
        elapsed = now - self.battle_started_at
        if self.opening_recorded:
            return
        if elapsed <= 45:
            values = cues.get("own_tower_fill", {})
            self.opening_samples.append({"seconds": round(elapsed, 2), "fill": values})
            if len(self.opening_samples) == 1 or 42 <= elapsed <= 45:
                cv2.imwrite(
                    str(
                        self.validation_dir
                        / f"opening-{self.completed + 1:04d}-{'start' if len(self.opening_samples) == 1 else '45s'}.png"
                    ),
                    frame,
                )
        else:
            self._finish_opening()

    def _finish_opening(self):
        if self.opening_recorded:
            return
        result = {}
        for lane in ("left", "right"):
            readable = [
                (s["seconds"], s["fill"].get(lane)) for s in self.opening_samples if s["fill"].get(lane) is not None
            ]
            baseline = [v for t, v in readable if t <= 5]
            # Require neighboring readings, not a single damage-flash pixel row.
            stable = [
                (t, (v + readable[i - 1][1]) / 2)
                for i, (t, v) in enumerate(readable)
                if i and t - readable[i - 1][0] <= 3 and abs(v - readable[i - 1][1]) <= 0.08
            ]
            full = bool(baseline and readable and readable[-1][0] >= 42 and not self.battle_resumed)
            loss = max(0, max(baseline) - min(v for _, v in stable)) if baseline and stable else None
            result[lane] = {
                "observed_loss_fraction": round(loss, 3) if loss is not None else None,
                "complete_45s_window": full,
                "last_readable_second": readable[-1][0] if readable else None,
                "method": "visual_health_bar_fraction_not_hp_ocr",
            }
        self.opening_result = result
        self.opening_recorded = True
        self._trace(
            {"event": "opening_45s", "battle": self.completed + 1, "towers": result, "samples": self.opening_samples}
        )

    def _use_elite_ability(self, frame: np.ndarray, cues: dict, decision) -> None:
        self._tap(decision.point)
        time.sleep(0.45)
        confirmed = False
        after_elixir = None
        for attempt in range(2):
            after_frame = self.device.screenshot()
            after_cues = read_cn_battle_cues(after_frame)
            after_elixir = after_cues["elixir"]
            spent = decision.elixir - after_elixir if after_elixir is not None else 0
            confirmed = self.vision.classify(after_frame)[0] == "battle" and spent >= 1
            if confirmed:
                break
            if attempt == 0:
                time.sleep(0.45)
        finished_at = time.monotonic()
        self.elite_ability.record(confirmed, finished_at)
        if self.strategy:
            self.strategy.last_attempt = finished_at
        self.logger.info("精英冰人技能: 确认=%s 剩余圣水=%s", confirmed, after_elixir)
        self._trace(
            {
                "event": "elite_ability",
                "battle": self.completed + 1,
                "decision": asdict(decision),
                "cues": cues,
                "after_elixir": after_elixir,
                "confirmed": confirmed,
                "deploy_point": self.elite_ability.deployed_point,
                "evidence_before": self._save_evidence("ability-before", frame),
                "evidence_after": self._save_evidence("ability-after", after_frame),
            }
        )
        if self.completed < 5:
            prefix = f"ability-{self.completed + 1:02d}-{time.strftime('%H%M%S')}"
            cv2.imwrite(str(self.validation_dir / f"{prefix}-before.png"), frame)
            cv2.imwrite(str(self.validation_dir / f"{prefix}-after.png"), after_frame)

    def _trace(self, event: dict) -> None:
        event["time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        event["session"] = self.validation_dir.name
        event["policy_version"] = getattr(self, "policy_version", POLICY_VERSION)
        event["mode"] = "classic_1v1"
        event["experiment"] = getattr(self, "experiment", {})
        with getattr(self, "trace_path", STRATEGY_TRACE).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        if getattr(self, "strategy_name", "hog") == "567":
            status = {
                "updated_at": event["time"],
                "session": event["session"],
                "policy_version": self.policy_version,
                "mode": "classic_1v1",
                "completed": self.completed,
                "results": self.result_counts,
                "consecutive_closed_loops": self.closed_loops,
                "validation_passed": self.gate_passed,
                "deployment_failures": self.total_deployment_failures,
                "current_bomber_forms": getattr(self, "bomber_forms", {}),
                "state": self.state,
                "last_event": event["event"],
                "validation_dir": str(self.validation_dir),
            }
            path = TASK_ROOT / "outputs" / "567-live-status.json"
            atomic_write_json(path, status)

    def _finish_battle(self, outcome: str = "未知", frame: np.ndarray | None = None) -> None:
        self._finish_opening()
        self.result_counts[outcome if outcome in self.result_counts else "未知"] += 1
        self.cycle_pending = bool(self.cards_confirmed and frame is not None and not self.battle_resumed)
        self.returned_lobby = False
        self.completed += 1
        self.consecutive = self.consecutive + 1 if self.cards_confirmed else 0
        self.logger.info(
            "对战结束 结果=%s 出牌确认=%d/%d 已完成=%d 连续完成=%d",
            outcome,
            self.cards_confirmed,
            self.card_attempts,
            self.completed,
            self.consecutive,
        )
        if not self.cards_confirmed:
            self.logger.warning("本场没有确认出牌，连续验收重新计数")
        if self.consecutive == 10:
            self.logger.info("验收里程碑：连续完成 10 场；继续运行")
        if self.strategy:
            self.logger.info("策略统计: %s", self.strategy.categories)
        self._trace(
            {
                "event": "battle_end",
                "battle": self.completed,
                "result": outcome,
                "confirmed": self.cards_confirmed,
                "attempts": self.card_attempts,
                "categories": self.strategy.categories if self.strategy else {},
                "elite_ability_uses": self.elite_ability.confirmed_uses,
                "deployment_failures": self.card_attempts - self.cards_confirmed,
                "opening_45s": self.opening_result,
                "counts": self.result_counts,
                "bomber_forms": self.bomber_forms,
                "evidence": self._save_evidence("result", frame) if frame is not None else None,
            }
        )
        if frame is not None and self.completed <= 10:
            self.validation_dir.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(self.validation_dir / f"result-{self.completed:02d}.png"), frame)
        self._set_state("result")

    def _begin_battle(self, resumed: bool = False) -> None:
        if self.cycle_pending and self.returned_lobby and not resumed:
            self.closed_loops += 1
            self.recovery_attempts = 0
            self._trace({"event": "closed_loop", "battle": self.completed, "consecutive": self.closed_loops})
            if self.closed_loops >= 10 and not self.gate_passed:
                self.gate_passed = True
                record = {
                    "event": "validation_passed",
                    "closed_loops": self.closed_loops,
                    "completed": self.completed,
                    "counts": self.result_counts,
                    "deployment_failures": self.total_deployment_failures,
                    "mode": "classic_1v1",
                    "next_battle_started": True,
                }
                self._trace(record)
                (self.validation_dir / "validation-passed.json").write_text(
                    json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                self.logger.info("连续10局开局-部署-结算-再开验收通过，进入无限循环；胜负不影响继续")
        elif self.completed and not self.gate_passed:
            self.closed_loops = 0
        self.cycle_pending = False
        self.battle_started_at = time.monotonic()
        self.battle_resumed = resumed
        self.opening_samples = []
        self.opening_recorded = False
        self.opening_result = {}
        if resumed:
            self.logger.warning("恢复事件：接管已开始的对战")
        self.logger.info("对战开始 场次=%d", self.completed + 1)
        self._trace({"event": "battle_start", "battle": self.completed + 1, "resumed": resumed})
        self._set_state("battle")
        self.last_card_at = 0.0
        self.no_card_since = 0.0
        self.card_attempts = 0
        self.cards_confirmed = 0
        self.card_failures = 0
        self.strategy = (DoubleAir567Strategy if self.strategy_name == "567" else HogCycleStrategy)(time.monotonic())
        self.bomber_forms = {}
        self.elite_ability = EliteIceGolemAbility()
        self.last_observation_log = 0.0
        self.clock_mask = None
        self.clock_changed_at = time.monotonic()

    def _step(self, frame: np.ndarray) -> None:
        if frame.shape[:2] != (633, 419):
            raise RuntimeError(f"Unexpected screenshot size: {frame.shape[:2]}")
        now = time.monotonic()
        daily = daily_gift_action(frame)
        if daily is not None:
            attempts = getattr(self, "_daily_gift_attempts", 0) + 1
            self._daily_gift_attempts = attempts
            if attempts > 3:
                raise RecoveryExhausted("每日礼物选择连续3次未离开；暂停")
            action, target = daily
            self._trace(
                {
                    "event": "daily_gift_choice",
                    "action": action,
                    "choice": "我想变好看",
                    "attempt": attempts,
                    "evidence": self._save_evidence("daily-gift-choice", frame),
                }
            )
            self.logger.info("每日福袋已识别，按已保存偏好选择：我想变好看")
            if not getattr(self, "_daily_reward_pending", False):
                self._daily_reward_pending = True
                self._daily_reward_had_existing_context = self.reward_pending
                if not self.reward_pending:
                    self.reward_pending = True
                    self.reward_taps = 0
                    self.four_star_reward_seen = False
                    self.last_four_star_tap_at = 0.0
            self.last_reward_tap_at = now
            self._tap(target)
            time.sleep(1.5)
            return
        self._daily_gift_attempts = 0
        cancel_exit = cn_game_exit_cancel(frame)
        if cancel_exit is not None and cancel_exit.target is not None:
            attempts = getattr(self, "_exit_cancel_attempts", 0) + 1
            self._exit_cancel_attempts = attempts
            if attempts > 3:
                raise RecoveryExhausted("退出确认连续3次未关闭；保留现场并暂停")
            self._trace(
                {
                    "event": "game_exit_cancelled",
                    "attempt": attempts,
                    "evidence": self._save_evidence("exit-cancel", frame),
                }
            )
            self._tap(cancel_exit.target)
            time.sleep(0.8)
            return
        self._exit_cancel_attempts = 0
        kind, match = self.vision.classify(frame)
        if getattr(self, "_daily_reward_pending", False) and (
            kind == "lobby" or (kind in ("unknown", "navigation") and cn_navigation_step(frame) is not None)
        ):
            self._daily_reward_pending = False
            if not self._daily_reward_had_existing_context:
                self.reward_pending = False
                self.reward_taps = 0
                self.four_star_reward_seen = False
        if kind in ("unknown", "navigation") and self.state == "lobby" and not self.reward_pending:
            step = cn_navigation_step(frame)
            if step is not None:
                attempts = getattr(self, "_page_return_attempts", 0) + 1
                self._page_return_attempts = attempts
                if attempts > 12:
                    raise RecoveryExhausted("已识别页面连续12次未返回大厅；暂停")
                self._trace(
                    {
                        "event": "known_page_return",
                        "page": step.page,
                        "route": step.route,
                        "target": list(step.target) if step.target is not None else None,
                        "evidence": self._save_evidence("known-page", frame),
                    }
                )
                recover_cn_page_once(
                    self.device,
                    _LogAdapter(self.logger),
                    frame=frame,
                    allow_spectator_exit=True,
                    allow_unowned_confirmation=True,
                )
                return
        if kind == "lobby":
            self._page_return_attempts = 0
        if kind == "connection_interrupted":
            self._recover("已确认连接中断及重新登录提示")
            return
        # The star can disappear during a reveal. Continue only after a known
        # reward, with its blue/purple background AND floor still present. Never tap
        # an arbitrary unknown page. Preserve this context through app recovery.
        if kind == "unknown" and self.reward_pending and self.vision.reward_continuation(frame):
            kind = "reward"
        if kind == "unknown" and now - self.last_unknown_evidence >= 5:
            self._trace(
                {
                    "event": "screen_unknown",
                    "battle": self.completed + 1,
                    "state": self.state,
                    "reward_taps": self.reward_taps,
                    "evidence": self._save_evidence("unknown", frame),
                }
            )
            self.last_unknown_evidence = now
        if kind == "unknown" and self.reward_pending:
            if 0 <= now - getattr(self, "last_reward_tap_at", 0.0) < 45:
                return  # short reveal animations can temporarily lose all templates
            self._recover("奖励后未知画面停留超过45秒")
            return
        if kind == "reward":
            self.reward_pending = True
            four_star = self.vision.four_star_reward(frame)
            if four_star:
                self.four_star_reward_seen = True
                if now - self.last_four_star_tap_at < 5:
                    return  # reveal steps animate slowly; do not spam the chest
            if not self.reward_taps:
                self.logger.info("处理结算后的即时奖励")
            self.reward_taps += 1
            self._trace(
                {
                    "event": "reward",
                    "battle": self.completed,
                    "tap": self.reward_taps,
                    "four_star": four_star,
                    "evidence": self._save_evidence("reward", frame),
                }
            )
            if self.reward_taps > (40 if self.four_star_reward_seen else 12):
                self._recover("即时奖励画面超出预期步骤")
                return
            if self.completed <= 10:
                self.validation_dir.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(self.validation_dir / f"reward-{self.completed:02d}-{self.reward_taps:02d}.png"), frame)
            self._tap(CN_POST_WIN_REWARD_TAP)
            self.last_reward_tap_at = now
            if four_star:
                self.last_four_star_tap_at = now
            time.sleep(1.4)
            return
        if kind == "lobby" and self.reward_taps:
            self.logger.info("即时奖励已处理，返回大厅；点击次数=%d", self.reward_taps)
            self.reward_taps = 0
        if kind == "lobby":
            self.reward_pending = False
            self.four_star_reward_seen = False
            self.returned_lobby = True
        if kind == "connection" and match is not None:
            self.logger.warning("恢复事件：关闭连接弹窗")
            self.recovery_attempts += 1
            if self.recovery_attempts > 3:
                raise RecoveryExhausted("连接弹窗连续恢复失败")
            self._tap(match.center)
            time.sleep(3)
            return

        if self.state == "lobby":
            if kind == "lobby" and match is not None:
                if not self.vision.classic_selected(frame) or not getattr(self, "_classic_menu_verified", False):
                    self._trace(
                        {"event": "restore_classic_mode", "evidence": self._save_evidence("mode-before", frame)}
                    )
                    if not navigate_cn_classic_1v1(
                        self.device, _LogAdapter(self.logger), self.vision, verify_menu=True
                    ):
                        observed = self.device.screenshot()
                        if self.vision.classify(observed)[0] in ("battle", "result", "reward"):
                            raise ModeOrDeckMismatch("模式验证失败后出现对战或奖励；保留现场，禁止开局")
                        self._recover("大厅无法完成模式菜单往返验证，恢复已安装游戏")
                        return
                    self._classic_menu_verified = True
                    return  # The next iteration must verify a fresh lobby before starting.
                if self.strategy_name == "567" and not self.deck_verified:
                    self._verify_deck()
                    return
                self._tap(match.center)
                self._set_state("match")
                return
            self.battle_confirmations = self.battle_confirmations + 1 if kind == "battle" else 0
            if self.battle_confirmations >= 2:
                self._begin_battle(resumed=True)
                return
            if kind == "result" and match is not None:
                self._tap(match.center)
            if now - self.state_since > LOBBY_TIMEOUT:
                self._recover("等待大厅超时或加载卡住")
            return

        if self.state == "match":
            self.battle_confirmations = self.battle_confirmations + 1 if kind == "battle" else 0
            if self.battle_confirmations >= 2:
                self._begin_battle()
                return
            if kind == "lobby" and now - self.state_since > 12 and match is not None:
                self.match_retries += 1
                if self.match_retries <= 3:
                    if not self.vision.classic_selected(frame):
                        raise ModeOrDeckMismatch("重试开局前经典1V1模式检查失败")
                    self._tap(match.center)
                    self.state_since = now
                    return
            if now - self.state_since > MATCH_TIMEOUT:
                self._recover("匹配或加载超时")
            return

        if self.state == "battle":
            self.result_confirmations = self.result_confirmations + 1 if kind == "result" else 0
            if self.result_confirmations >= 2:
                outcome = self.vision.outcome(frame)
                self._finish_battle(outcome, frame)
                return
            self.lobby_confirmations = self.lobby_confirmations + 1 if kind == "lobby" else 0
            if self.lobby_confirmations >= 2:
                self.logger.warning("恢复事件：战斗中意外返回大厅；本场不计完成")
                self._trace(
                    {
                        "event": "battle_abandoned",
                        "battle": self.completed + 1,
                        "reason": "unexpected_lobby",
                        "evidence": self._save_evidence("abandoned", frame),
                    }
                )
                self.consecutive = 0
                self._set_state("lobby")
                return
            if now - self.state_since > BATTLE_TIMEOUT:
                self._recover("对战超时或画面冻结")
                return
            if kind == "battle":
                if self._clock_stalled(frame, now):
                    self._trace(
                        {
                            "event": "clock_stalled",
                            "battle": self.completed + 1,
                            "evidence": self._save_evidence("stalled", frame),
                        }
                    )
                    self._recover("对战计时画面45秒未更新")
                    return
                self._play_card(frame)
            return

        if self.state == "result":
            if self.completed <= 10:
                self.validation_dir.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(self.validation_dir / "latest-post-result.png"), frame)
            if kind == "lobby":
                self._set_state("lobby")
                return
            if kind == "result" and match is not None:
                self._tap(match.center)
                time.sleep(2)
            if now - self.state_since > RESULT_TIMEOUT:
                self._recover("结算页未返回大厅")

    def _finish_limited_batch(self, frame: np.ndarray, max_battles: int) -> bool:
        """End a requested test only after all rewards have reached the lobby."""
        if max_battles <= 0 or self.completed < max_battles:
            return False
        if self.vision.classify(frame)[0] != "lobby":
            return False
        if self.reward_taps:
            self.logger.info("即时奖励已处理，返回大厅；点击次数=%d", self.reward_taps)
        self.reward_pending = False
        self.reward_taps = 0
        completion = {
            "event": "batch_complete",
            "battle": self.completed,
            "target_battles": max_battles,
            "consecutive": self.consecutive,
            "state": "lobby",
            "evidence": self._save_evidence("batch-lobby", frame),
        }
        self._trace(completion)
        (self.validation_dir / "batch-complete.json").write_text(
            json.dumps(completion, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.logger.info("限量验收完成：已完成=%d，连续完成=%d，已回大厅，正常停止", self.completed, self.consecutive)
        self._set_state("stopped")
        return True

    def run_forever(self, max_battles: int = 0) -> None:
        if max_battles < 0:
            raise ValueError("max_battles must be nonnegative")
        self.logger.info("国服 1v1 连续对战已启动，设备=%s", self.serial)
        self.logger.info("策略=%s；模式=经典1V1；连续10局闭环验收后无限继续，输局不停", self.policy_version)
        self.logger.info("策略源码校验: %s", self.policy_hashes)
        if max_battles:
            self.logger.info("限量验收模式：完成%d场并回到大厅后正常停止", max_battles)
            self._trace({"event": "batch_start", "battle": 0, "target_battles": max_battles})
        io_failures = 0
        while True:
            try:
                frame = self.device.screenshot()
                foreground = self.device.foreground_package()
                if foreground and foreground != CLASH_ROYALE_PACKAGE:
                    if time.monotonic() - self.state_since > 25:
                        self._recover(f"前台应用变为 {foreground}")
                else:
                    if self._finish_limited_batch(frame, max_battles):
                        return
                    self._step(frame)
                io_failures = 0
            except (OSError, subprocess.TimeoutExpired) as error:
                io_failures += 1
                self.logger.warning("ADB 临时失联/超时（%d/3）：%s", io_failures, type(error).__name__)
                if io_failures >= 3:
                    self._recover(f"ADB 连续 {io_failures} 次失败: {error}")
                    io_failures = 0
                else:
                    self._reconnect()
                    time.sleep(3)
            except (ValueError, RuntimeError, cv2.error) as error:
                self._recover(f"ADB/截图/状态异常: {type(error).__name__}: {error}")
            # A local frame + focus + vision pass measured about 0.4s. Keep
            # the idle/recovery cadence, but shorten the extra combat delay so
            # two-frame pressure confirmation does not cost another 0.9s.
            time.sleep(BATTLE_POLL_SECONDS if self.state == "battle" else POLL_SECONDS)
