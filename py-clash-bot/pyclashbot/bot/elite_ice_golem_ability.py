# ruff: noqa: RUF001
# Native Chinese punctuation and multiplication glyphs are intentional UI/OCR text.
"""Bounded use of the observed two-elixir Tencent Elite Ice Golem ability."""

import math
from dataclasses import dataclass

from pyclashbot.bot.coords import CN_HOG_ELITE_ABILITY_TAP

ABILITY_COST = 2


@dataclass(frozen=True)
class EliteAbilityDecision:
    point: tuple[int, int]
    reason: str
    elixir: int
    nearby_markers: int


class EliteIceGolemAbility:
    """Require deployment provenance, a colored ready button and nearby pressure.

    We do not track the unit itself. The short deployment corridor is deliberately
    limited to nine seconds, and at most one confirmed use is allowed per deploy.
    """

    def __init__(self) -> None:
        self.deployed_at = -math.inf
        self.deployed_point: tuple[int, int] | None = None
        self.ready_frames = 0
        self.pressure_frames = 0
        self.used = False
        self.attempts = 0
        self.last_attempt = -math.inf
        self.confirmed_uses = 0

    def deployed(self, variant: str | None, point: tuple[int, int], now: float) -> None:
        if variant != "elite_ice_golem":
            return
        self.deployed_at = now
        self.deployed_point = point
        self.ready_frames = 0
        self.pressure_frames = 0
        self.used = False
        self.attempts = 0

    def decide(self, cues: dict, now: float) -> EliteAbilityDecision | None:
        ready = bool(cues.get("elite_ability_ready"))
        self.ready_frames = self.ready_frames + 1 if ready else 0
        elapsed = now - self.deployed_at
        if self.used or self.attempts >= 2 or self.deployed_point is None or not 1 <= elapsed <= 9:
            return None
        x, y = self.deployed_point
        # Ice Golem normally moves toward the opponent, but may be held by troops.
        # Accept pressure only in this short local corridor, not anywhere in the arena.
        advance = min(55, elapsed * 10)
        nearby = [
            (ex, ey) for ex, ey in cues.get("enemies", []) if abs(ex - x) <= 48 and y - advance - 35 <= ey <= y + 30
        ]
        urgent = any(ey >= 400 and abs(ex - x) <= 38 for ex, ey in nearby)
        pressure = len(nearby) >= 2 or urgent
        self.pressure_frames = self.pressure_frames + 1 if pressure else 0
        elixir = cues.get("elixir")
        if elixir is None or self.ready_frames < 2 or self.pressure_frames < 2:
            return None
        reserve = 2 if urgent and len(nearby) >= 3 else 3
        if elixir < ABILITY_COST + reserve or now - self.last_attempt < 2.0:
            return None
        return EliteAbilityDecision(
            CN_HOG_ELITE_ABILITY_TAP,
            f"精英冰人已部署且附近有持续压力，使用暴风雪并保留{reserve}费",
            elixir,
            len(nearby),
        )

    def record(self, confirmed: bool, now: float) -> None:
        self.attempts += 1
        self.last_attempt = now
        if confirmed:
            self.used = True
            self.confirmed_uses += 1
