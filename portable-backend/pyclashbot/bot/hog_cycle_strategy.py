"""Deterministic 2.6 Hog rules; V5 candidate geometry and observed-target rules."""
# Chinese user-facing status intentionally uses full-width punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

from pyclashbot.bot.coords import (
    CN_HOG_BACK_POINTS,
    CN_HOG_BRIDGE_MUSKETEER_POINTS,
    CN_HOG_BRIDGE_POINTS,
    CN_HOG_CANNON_COVERAGE_RADIUS,
    CN_HOG_CANNON_LATE_PRESSURE_Y,
    CN_HOG_CANNON_POINTS,
    CN_HOG_CANNON_TARGET_OFFSET_Y,
    CN_HOG_CENTRAL_MUSKETEER_POINTS,
    CN_HOG_DEEP_KITE_POINTS,
    CN_HOG_DEEP_MUSKETEER_POINTS,
    CN_HOG_DUAL_LANE_MUSKETEER_POINT,
    CN_HOG_ENEMY_PRINCESS_TOWER_POINTS,
    CN_HOG_FIREBALL_GROUND_OFFSET_Y,
    CN_HOG_FIREBALL_MAX_Y,
    CN_HOG_FRIENDLY_TOWER_BOXES,
    CN_HOG_KITE_POINTS,
    CN_HOG_LANE_SPLIT_X,
    CN_HOG_LOG_Y_LIMITS,
    CN_HOG_MUSKETEER_POINTS,
    CN_HOG_STALL_POINTS,
    CN_HOG_STALL_SAFE_BOUNDS,
    CN_HOG_STALL_TARGET_MIN_Y,
    CN_HOG_STALL_TARGET_Y_OFFSET,
    CN_HOG_STALL_TOWER_MARGIN,
    CN_HOG_SUPPORT_POINTS,
)

COSTS = {
    "hog": 4,
    "musketeer": 4,
    "cannon": 3,
    "fireball": 4,
    "ice_golem": 2,
    "log": 2,
    "ice_spirit": 1,
    "skeletons": 1,
}
CARD_NAMES = {
    "hog": "野猪",
    "musketeer": "火枪",
    "cannon": "加农炮",
    "fireball": "火球",
    "ice_golem": "冰人",
    "log": "滚木",
    "ice_spirit": "冰精灵",
    "skeletons": "骷髅",
}
MIN_ACTION_INTERVAL = 1.2
PRESSURE_HOLD_SECONDS = 2.5
CORE_DEFENSE_WAIT_SECONDS = 4.5
CORE_REPLAY_COOLDOWN = 4.0
CORE_BUDGET_SECONDS = 12.0
OWN_PRESSURE_Y = 300
TYPED_BRIDGE_PRESSURE_Y = 275
THREAT_CONFIDENCE = 0.88
THREAT_ASSOCIATION_RADIUS = 40
SKELETON_BARREL_TEMPLATE = "air_skeleton_barrel_top"
SKELETON_BARREL_CONFIDENCE = 0.74
BALLOON_TEMPLATE = "air_balloon_envelope"
BALLOON_CONFIDENCE = 0.78
BALLOON_PRESSURE_Y = 210
ROYAL_GIANT_TEMPLATE = "rush_royal_giant_head"
ROYAL_GIANT_PRESSURE_Y = 250
HOG_RUSH_TEMPLATE = "rush_hog_rider"
HOG_RUSH_PRESSURE_Y = 200
LOW_TOWER_FILL_FOR_SPELL = 0.13
ONE_SPELL_TOWER_FILL = 0.04
LATE_SPELL_START_SECONDS = 140.0
BRIDGE_OBSERVATION_SECONDS = 2.5
BRIDGE_OBSERVATION_MAX_GAP = 2.5
BRIDGE_OBSERVATION_RADIUS = 10


class DarkGroundObservation(TypedDict):
    x: int
    y: int
    dark_pixels: int
    time: float


class BridgeObservation(TypedDict):
    anchor: tuple[int, int]
    first: float
    seen: float
    frames: int


@dataclass(frozen=True)
class HogDecision:
    slot: int
    card: str
    variant: str | None
    point: tuple[int, int]
    reason: str
    category: str
    elixir: int
    lane: str | None = None
    pressure_count: int = 0
    pressure_depth: int = 0
    threat_kind: str | None = None
    persistent_bridge: bool = False


class HogCycleStrategy:
    """One card per decision; only confirmed deployments advance combinations."""

    def __init__(self, started_at: float) -> None:
        self.started_at = started_at
        self.attack_lane = "left"
        self.last_attempt = -math.inf
        self.last_play: dict[str, float] = {}
        self.pending_hog_until = 0.0
        self.pending_hog_is_spirit = False
        self.supported_hog_at = -math.inf
        self.raw_pressure_frames = 0
        self.last_pressure_at = -math.inf
        self.stable_enemies: list[tuple[int, int]] = []
        self.destroyed_tower_frames = 0
        self.last_core_defense: dict[str, tuple[float, int, int]] = {}
        self.last_defense_by_card: dict[tuple[str, str], float] = {}
        self.core_spending: list[tuple[float, str, int]] = []
        self.last_unsupported_delay: dict[str, tuple[float, int, int]] = {}
        self.bridge_observations: list[BridgeObservation] = []
        self.low_tower_frames = {"left": 0, "right": 0}
        self.last_own_tower_fill: dict[str, float | None] = {"left": None, "right": None}
        self.own_tower_damaged_at = {"left": -math.inf, "right": -math.inf}
        self.far_warning_frames = 0
        self.far_warning_lane: str | None = None
        self.dark_ground_observations: list[DarkGroundObservation] = []
        self.categories: dict[str, int] = {"attack": 0, "defense": 0, "cycle": 0, "spell": 0}

    def _moving_dark_ground(self, candidates: list[dict], now: float) -> list[DarkGroundObservation]:
        """Confirm only a dark red-plaque body that advanced in the same lane."""
        previous = [item for item in self.dark_ground_observations if now - item["time"] <= 6]
        current: list[DarkGroundObservation] = []
        for item in candidates:
            x, y, pixels = item.get("x"), item.get("y"), item.get("dark_pixels")
            if (
                not isinstance(x, int)
                or not isinstance(y, int)
                or not isinstance(pixels, int)
                or not 30 <= x <= 389
                or not 190 <= y <= 310
                or pixels < 330
            ):
                continue
            current.append({"x": x, "y": y, "dark_pixels": pixels, "time": now})
        confirmed: list[DarkGroundObservation] = []
        for item in current:
            if item["dark_pixels"] < 400:
                continue
            for prior in previous:
                elapsed = now - prior["time"]
                if (
                    0 < elapsed <= 6
                    and abs(item["x"] - prior["x"]) <= 35
                    and 18 <= item["y"] - prior["y"] <= 90
                    and (item["x"] < CN_HOG_LANE_SPLIT_X) == (prior["x"] < CN_HOG_LANE_SPLIT_X)
                ):
                    confirmed.append(item)
                    break
        self.dark_ground_observations = previous + current
        return confirmed

    def _pressure(
        self, enemies: list[tuple[int, int]], now: float, urgent_group: bool = False
    ) -> list[tuple[int, int]]:
        self.raw_pressure_frames = self.raw_pressure_frames + 1 if enemies else 0
        if self.raw_pressure_frames >= 2 or urgent_group:
            self.stable_enemies = enemies
            self.last_pressure_at = now
        elif not enemies and now - self.last_pressure_at > PRESSURE_HOLD_SECONDS:
            self.stable_enemies = []
        return self.stable_enemies

    def _ready(self, card: str, now: float, cooldown: float) -> bool:
        return now - self.last_play.get(card, -math.inf) >= cooldown

    @staticmethod
    def _stall_point(target: tuple[int, int], lane: str) -> tuple[int, int]:
        """Place a cheap unit beside the current near-tower target, not its old lane tile."""
        if target[1] < CN_HOG_STALL_TARGET_MIN_Y:
            return CN_HOG_STALL_POINTS[lane]
        min_x, min_y, max_x, max_y = CN_HOG_STALL_SAFE_BOUNDS
        x = max(min_x, min(max_x, target[0]))
        y = max(min_y, min(max_y, target[1] + CN_HOG_STALL_TARGET_Y_OFFSET))
        for name, (x1, y1, x2, y2) in CN_HOG_FRIENDLY_TOWER_BOXES.items():
            if x1 <= x <= x2 and y1 <= y <= y2:
                left_x = max(min_x, x1 - CN_HOG_STALL_TOWER_MARGIN)
                right_x = min(max_x, x2 + CN_HOG_STALL_TOWER_MARGIN)
                if name == "king":
                    x = left_x if lane == "left" else right_x
                else:
                    x = min((left_x, right_x), key=lambda candidate: abs(candidate - target[0]))
        return (int(x), int(y))

    def _persistent_bridge_points(self, enemies: list[tuple[int, int]], now: float) -> set[tuple[int, int]]:
        """Promote only currently visible, spatially stable bridge observations.

        This records persistence, not troop identity or proof of an attack.
        Anchoring to the first point prevents a slowly moving chain from
        inheriting a stationary target's history across the bridge.
        """
        previous = [item for item in self.bridge_observations if 0 <= now - item["seen"] <= BRIDGE_OBSERVATION_MAX_GAP]
        used: set[int] = set()
        current: list[BridgeObservation] = []
        persistent: set[tuple[int, int]] = set()
        for raw_point in enemies:
            point = tuple(raw_point)
            if not ROYAL_GIANT_PRESSURE_Y <= point[1] < OWN_PRESSURE_Y:
                continue
            matches = [
                (i, item)
                for i, item in enumerate(previous)
                if i not in used and math.dist(item["anchor"], point) <= BRIDGE_OBSERVATION_RADIUS
            ]
            observation: BridgeObservation = {"anchor": point, "first": now, "seen": now, "frames": 1}
            if matches:
                index, old = min(matches, key=lambda pair: math.dist(pair[1]["anchor"], point))
                used.add(index)
                observation = {**old, "seen": now, "frames": old["frames"] + int(now > old["seen"])}
            current.append(observation)
            if observation["frames"] >= 3 and now - observation["first"] >= BRIDGE_OBSERVATION_SECONDS:
                persistent.add(point)
        # Short visibility gaps retain history, but absent points are never
        # returned for spending. A later gap beyond the limit resets the track.
        current.extend(item for i, item in enumerate(previous) if i not in used)
        self.bridge_observations = current
        return persistent

    def decide(
        self,
        hand: list[dict],
        elixir: int | None,
        enemies: list[tuple[int, int]],
        now: float,
        enemy_towers: Mapping[str, bool | None] | None = None,
        threats: list[dict] | None = None,
        far_warnings: list[tuple[int, int]] | None = None,
        enemy_tower_fill: Mapping[str, float | None] | None = None,
        own_tower_fill: Mapping[str, float | None] | None = None,
        dark_ground_candidates: list[dict] | None = None,
    ) -> HogDecision | None:
        other_lane = "right" if self.attack_lane == "left" else "left"
        if enemy_towers and enemy_towers.get(self.attack_lane) is False and enemy_towers.get(other_lane) is True:
            self.destroyed_tower_frames += 1
            if self.destroyed_tower_frames >= 3:
                self.attack_lane = other_lane
                self.pending_hog_until = 0.0
                self.pending_hog_is_spirit = False
                self.supported_hog_at = self.last_play.get("hog", -math.inf)
                self.destroyed_tower_frames = 0
        else:
            self.destroyed_tower_frames = 0
        for side in ("left", "right"):
            fill = (enemy_tower_fill or {}).get(side)
            visible = enemy_towers and enemy_towers.get(side) is True
            valid = (
                visible
                and isinstance(fill, (int, float))
                and math.isfinite(fill)
                and 0 < fill <= LOW_TOWER_FILL_FOR_SPELL
            )
            self.low_tower_frames[side] = self.low_tower_frames[side] + 1 if valid else 0
            own_fill = (own_tower_fill or {}).get(side)
            if isinstance(own_fill, (int, float)) and math.isfinite(own_fill) and 0 < own_fill <= 1:
                previous = self.last_own_tower_fill[side]
                if previous is not None and previous - own_fill >= 0.06:
                    self.own_tower_damaged_at[side] = now
                self.last_own_tower_fill[side] = own_fill
        # At least two same-lane upper-arena plaques are a preparation warning,
        # never a target for a defensive spell or proof of near-tower pressure.
        # A single-frame warning delays an uncommitted attack while the next
        # screenshot confirms it. An existing Ice Golem -> Hog promise survives.
        far_left = [point for point in far_warnings or [] if point[0] < CN_HOG_LANE_SPLIT_X]
        far_right = [point for point in far_warnings or [] if point[0] >= CN_HOG_LANE_SPLIT_X]
        warning_lane = "left" if len(far_left) >= len(far_right) else "right"
        warning_count = max(len(far_left), len(far_right))
        warning_lane = warning_lane if warning_count >= 2 else None
        single_river_warning = any(200 <= y < OWN_PRESSURE_Y for _, y in far_warnings or [])
        if warning_lane is None:
            self.far_warning_frames = 0
            self.far_warning_lane = None
        else:
            self.far_warning_frames = self.far_warning_frames + 1 if warning_lane == self.far_warning_lane else 1
            self.far_warning_lane = warning_lane
        dark_ground_approaches = self._moving_dark_ground(dark_ground_candidates or [], now)
        # Historical river-only pressure once cancelled an already confirmed
        # Ice Golem -> Hog follow-up. Keep that combination independent below.
        valid_threats = []
        for threat in threats or []:
            if not isinstance(threat, dict) or threat.get("kind") not in ("air", "rush", "swarm"):
                continue
            confidence, tx, ty = threat.get("confidence"), threat.get("x"), threat.get("y")
            if (
                not isinstance(confidence, (int, float))
                or not isinstance(tx, (int, float))
                or not isinstance(ty, (int, float))
                or not all(math.isfinite(value) for value in (confidence, tx, ty))
            ):
                continue
            # These air templates have separately validated operating points
            # plus red-area gates in the vision layer. Never
            # accept a caller-supplied threshold or relax other template IDs.
            minimum_confidence = THREAT_CONFIDENCE
            if threat["kind"] == "air" and threat.get("template_id") == SKELETON_BARREL_TEMPLATE:
                minimum_confidence = SKELETON_BARREL_CONFIDENCE
            elif threat["kind"] == "air" and threat.get("template_id") == BALLOON_TEMPLATE:
                minimum_confidence = BALLOON_CONFIDENCE
            if minimum_confidence <= confidence <= 1.0:
                valid_threats.append(threat)
        # The ordinary Balloon's level tag sits high above its basket/shadow.
        # Only its calibrated template can promote the vision layer's explicit
        # early marker from y210; other air, Royal Giant and unknown points
        # retain their existing separate boundaries.
        early_threats = []
        for threat in valid_threats:
            if threat["kind"] == "air":
                minimum_y = (
                    BALLOON_PRESSURE_Y if threat.get("template_id") == BALLOON_TEMPLATE else TYPED_BRIDGE_PRESSURE_Y
                )
            elif threat["kind"] == "rush":
                if threat.get("template_id") == HOG_RUSH_TEMPLATE:
                    minimum_y = HOG_RUSH_PRESSURE_Y
                else:
                    minimum_y = (
                        ROYAL_GIANT_PRESSURE_Y
                        if threat.get("template_id") == ROYAL_GIANT_TEMPLATE
                        else TYPED_BRIDGE_PRESSURE_Y
                    )
            else:
                continue
            early_threats.append((threat, minimum_y))
        persistent_bridge_points = self._persistent_bridge_points(enemies, now)
        own_enemies = [
            point
            for point in enemies
            if point[1] >= OWN_PRESSURE_Y
            or tuple(point) in persistent_bridge_points
            or any(
                point[1] >= minimum_y
                and threat["y"] >= minimum_y
                and (threat["x"] < CN_HOG_LANE_SPLIT_X) == (point[0] < CN_HOG_LANE_SPLIT_X)
                and math.dist((threat["x"], threat["y"]), point) <= THREAT_ASSOCIATION_RADIUS
                for threat, minimum_y in early_threats
            )
        ]
        # A visible Princess Tower bar at or below one verified Fireball hit
        # is a small but decisive window. Pilot 09 B10 showed 126 HP with a
        # ready Fireball and two seconds left; the old pressure ordering spent
        # on a Musketeer instead. Protect the King Tower first if it is being
        # surrounded, and otherwise allow this lethal shot on one clear frame.
        king_near = [point for point in own_enemies if 150 <= point[0] <= 270 and point[1] >= 335]
        king_crisis = len(king_near) >= 2 and max(y for _, y in king_near) >= 380
        fireball_in_hand = any(item.get("card") == "fireball" and item.get("available") for item in hand)
        numeric_tower_fills = {
            side: fill for side, fill in (enemy_tower_fill or {}).items() if isinstance(fill, (int, float))
        }
        lethal_sides = [
            side
            for side in ("left", "right")
            if enemy_towers
            and enemy_towers.get(side) is True
            and side in numeric_tower_fills
            and 0 < numeric_tower_fills[side] <= ONE_SPELL_TOWER_FILL
        ]
        lethal_side = (
            min(lethal_sides, key=lambda side: numeric_tower_fills[side])
            if lethal_sides
            and fireball_in_hand
            and isinstance(elixir, int)
            and elixir >= COSTS["fireball"]
            and not king_crisis
            else None
        )
        # Three separately recognized plaques already inside our half are
        # enough to act now. Waiting for another ADB frame let fast swarms
        # move from y330 to a Princess Tower before a defensive card landed.
        urgent_group = not self.stable_enemies and len(own_enemies) >= 3 and max(y for _, y in own_enemies) >= 330
        pressure = self._pressure(own_enemies, now, urgent_group)
        # After a visibility gap the held points can block an attack, but a
        # new first frame must never authorize spending against those old
        # coordinates. The next confirmed frame replaces the held snapshot.
        if own_enemies and self.raw_pressure_frames < 2 and not urgent_group and lethal_side is None:
            return None
        if elixir is None or not 0 <= elixir <= 10 or now - self.last_attempt < MIN_ACTION_INTERVAL:
            return None
        available = {
            item["card"]: item
            for item in hand
            if item.get("available") and item.get("card") in COSTS and COSTS[item["card"]] <= elixir
        }
        if not available:
            return None

        pressure_lane = None
        pressure_count = 0
        pressure_depth = 0
        threat_kind = None
        persistent_bridge = False

        def play(card: str, point: tuple[int, int], reason: str, category: str) -> HogDecision | None:
            item = available.get(card)
            if item is None:
                return None
            return HogDecision(
                item["slot"],
                card,
                item.get("variant"),
                point,
                reason,
                category,
                elixir,
                pressure_lane,
                pressure_count,
                pressure_depth,
                threat_kind,
                persistent_bridge,
            )

        if lethal_side is not None and self._ready("fireball", now, 5):
            decision = play(
                "fireball",
                CN_HOG_ENEMY_PRINCESS_TOWER_POINTS[lethal_side],
                "敌公主塔可被一发火球摧毁，立即收塔",
                "spell",
            )
            if decision:
                return decision

        if pressure:
            # Keep the short observation hold for safety, but do not spend on
            # a target that has disappeared from the current frame.
            if not own_enemies:
                return None
            # Frozen three-crown losses include affordable Fireballs ignored
            # beside the King Tower because only one or two plaques shared the
            # old 43-pixel cluster. Defend the center before cheap delays.
            if king_crisis and self._ready("fireball", now, 5):
                pressure_count = len(king_near)
                pressure_depth = max(y for _, y in king_near)
                target = (
                    round(sum(x for x, _ in king_near) / len(king_near)),
                    min(CN_HOG_FIREBALL_MAX_Y, round(sum(y for _, y in king_near) / len(king_near)) + 20),
                )
                decision = play("fireball", target, "国王塔近场多目标，立即火球解围", "spell")
                if decision:
                    return decision
            left = [point for point in pressure if point[0] < CN_HOG_LANE_SPLIT_X]
            right = [point for point in pressure if point[0] >= CN_HOG_LANE_SPLIT_X]
            left_weight = sum(max(1, y - 250) for _, y in left)
            right_weight = sum(max(1, y - 250) for _, y in right)
            lane = "left" if left and (not right or left_weight >= right_weight) else "right"
            lanes = {"left": left, "right": right}
            deep_lanes = [side for side, points in lanes.items() if points and max(y for _, y in points) >= 400]
            if deep_lanes:
                lane = max(deep_lanes, key=lambda side: max(y for _, y in lanes[side]))
            other = "right" if lane == "left" else "left"
            # Pilot 09 B1: our right Musketeer had just been deployed against
            # three close markers, while three more were about to cross the
            # opposite bridge. Spending the last four elixir on that covered
            # lane's Fireball left the other Princess Tower unguarded.
            other_far = far_left if other == "left" else far_right
            other_air = any(
                threat["kind"] == "air" and (threat["x"] < CN_HOG_LANE_SPLIT_X) == (other == "left")
                for threat in valid_threats
            )
            if (
                not lanes[other]
                and len(other_far) >= 3
                and max(y for _, y in other_far) >= 250
                and now - self.last_defense_by_card.get((lane, "musketeer"), -math.inf) < 10
                and not other_air
                and elixir >= 4
                and self._ready("cannon", now, CORE_REPLAY_COOLDOWN)
            ):
                pressure_lane, pressure_count = other, len(other_far)
                pressure_depth = max(y for _, y in other_far)
                decision = play(
                    "cannon", CN_HOG_CANNON_POINTS[other], "双路推进：已由火枪守一路，先用炮接另一侧", "defense"
                )
                if decision:
                    return decision
            recent_core = self.last_core_defense.get(lane)
            # An uncovered, urgent opposite lane takes precedence over adding
            # another core to the lane that just received one.
            other_core = self.last_core_defense.get(other)
            if (
                recent_core
                and now - recent_core[0] < CORE_DEFENSE_WAIT_SECONDS
                and max(y for _, y in lanes[lane]) < recent_core[2] + 35
                and len(lanes[lane]) < recent_core[1] + 2
                and lanes[other]
                and max(y for _, y in lanes[other]) >= 375
                and (not other_core or now - other_core[0] >= CORE_DEFENSE_WAIT_SECONDS)
            ):
                lane = other
            units = left if lane == "left" else right
            deepest = max(y for _, y in units)
            focus = max(units, key=lambda point: point[1])
            persistent_bridge = tuple(focus) in persistent_bridge_points
            associated: dict[str, list[tuple[int, int]]] = {}
            for threat in valid_threats:
                tx, ty = threat["x"], threat["y"]
                threat_lane = "left" if tx < CN_HOG_LANE_SPLIT_X else "right"
                if threat_lane != lane or math.dist((tx, ty), focus) > THREAT_ASSOCIATION_RADIUS:
                    continue
                # The vision layer returns marker coordinates. Anchor actions
                # to the nearest actual marker, never an arbitrary classifier
                # coordinate or a label from the other side of the arena.
                marker = min(units, key=lambda point: math.dist(point, (tx, ty)))
                if math.dist(marker, (tx, ty)) <= THREAT_ASSOCIATION_RADIUS:
                    associated.setdefault(threat["kind"], []).append(marker)
            threat_kind = "+".join(sorted(associated)) or None
            urgent = deepest >= 375
            pressure_lane, pressure_count, pressure_depth = lane, len(units), deepest
            if deepest >= 350 or len(pressure) >= 3:
                self.pending_hog_until = 0.0
                self.pending_hog_is_spirit = False
            deep = deepest >= 400
            if deep:
                musketeer_point = CN_HOG_DEEP_MUSKETEER_POINTS[lane]
            elif persistent_bridge:
                musketeer_point = CN_HOG_BRIDGE_MUSKETEER_POINTS[lane]
            elif 166 <= focus[0] <= 253:
                # Near-midline pressure should not send the only ranged output
                # to the outer edge due to a one-pixel left/right weight tie.
                musketeer_point = CN_HOG_CENTRAL_MUSKETEER_POINTS[lane]
            else:
                musketeer_point = CN_HOG_MUSKETEER_POINTS[lane]
            stall_point = self._stall_point(focus, lane)
            kite_point = (CN_HOG_DEEP_KITE_POINTS if deep else CN_HOG_KITE_POINTS)[lane]
            cannon_point = CN_HOG_CANNON_POINTS[lane]
            projected_target = (focus[0], focus[1] + CN_HOG_CANNON_TARGET_OFFSET_Y)
            cannon_covers_target = (
                deepest < CN_HOG_CANNON_LATE_PRESSURE_Y
                or math.dist(projected_target, cannon_point) <= CN_HOG_CANNON_COVERAGE_RADIUS
            )
            cluster = max(
                ([q for q in units if math.dist(p, q) <= 43] for p in units),
                key=len,
            )
            # A confirmed incursion authorizes aiming a spell at its actual
            # nearby support, including observed markers just behind the river.
            # Do not promote those support points into pressure or invent units.
            spell_points = [point for point in enemies if (point[0] < CN_HOG_LANE_SPLIT_X) == (lane == "left")]
            support_cluster = max(
                ([q for q in spell_points if math.dist(p, q) <= 43] for p in units),
                key=len,
            )
            # The extended support set only enables the existing five-marker
            # large-group rule; ordinary three-marker priorities stay unchanged.
            fireball_cluster = support_cluster if len(support_cluster) >= 5 else cluster
            cluster_depth = max(y for _, y in fireball_cluster)
            recent_core = self.last_core_defense.get(lane)
            covered = bool(recent_core and now - recent_core[0] < 10)
            tower_damaged_recently = now - self.own_tower_damaged_at[lane] < 5
            # A Cannon alone does not establish coverage against unknown air.
            # Only recent confirmed general-purpose output can authorize this
            # counterpush; a single unknown shallow marker is not a safe lane.
            general_output_covered = now - self.last_defense_by_card.get((lane, "musketeer"), -math.inf) < 10
            covered_small_push = general_output_covered and len(pressure) <= 2 and deepest < 360
            any_urgent = any(y >= 375 for _, y in pressure)
            if (
                not associated
                and not persistent_bridge
                and not any_urgent
                and covered_small_push
                and "hog" in available
                and elixir >= COSTS["hog"] + 2
                and self._ready("hog", now, 6)
            ):
                return play(
                    "hog",
                    CN_HOG_BRIDGE_POINTS[self.attack_lane],
                    "已有通用输出覆盖小股压力，野猪反打并保留2费",
                    "attack",
                )

            self.core_spending = [entry for entry in self.core_spending if now - entry[0] < CORE_BUDGET_SECONDS]
            core_spent = sum(cost for _, side, cost in self.core_spending if side == lane)
            escalation = bool(recent_core and (deepest >= recent_core[2] + 35 or len(units) >= recent_core[1] + 2))
            core_budget = 8 if urgent or escalation else 7

            def core_allowed(card: str) -> bool:
                if card == "cannon" and not cannon_covers_target:
                    return False
                repeated_same_card = now - self.last_defense_by_card.get((lane, card), -math.inf) < CORE_BUDGET_SECONDS
                # Normal pressure may receive one Cannon plus one Musketeer;
                # it may not repeatedly recycle the same core inside the
                # window. Escalation retains the existing capped exception.
                return (
                    core_spent + COSTS[card] <= core_budget
                    and (not repeated_same_card or urgent or escalation)
                    and self._ready(card, now, CORE_REPLAY_COOLDOWN)
                )

            def cheap_delay(cards: tuple[str, ...] = ("ice_spirit", "skeletons")) -> HogDecision | None:
                # With no established output, one cheap delay buys time to
                # save for it. Repeated 1-cost cards must not starve the core.
                previous = self.last_unsupported_delay.get(lane)
                if (
                    not covered
                    and previous
                    and now - previous[0] < CORE_BUDGET_SECONDS
                    and deepest < previous[2] + 35
                    and len(units) < previous[1] + 2
                ):
                    return None
                for card in cards:
                    if self._ready(card, now, 2):
                        decision = play(
                            card,
                            stall_point,
                            "已有防守核心，1费辅助输出" if covered else "先用1费拖延，随后蓄费建立防守输出",
                            "defense",
                        )
                        if decision:
                            return decision
                return None

            def fireball(points: list[tuple[int, int]] | None = None) -> HogDecision | None:
                targets = fireball_cluster if points is None else points
                point = (
                    round(sum(x for x, _ in targets) / len(targets)),
                    min(
                        CN_HOG_FIREBALL_MAX_Y,
                        round(sum(y for _, y in targets) / len(targets)) + CN_HOG_FIREBALL_GROUND_OFFSET_Y,
                    ),
                )
                return play("fireball", point, "火球打已确认的密集压力区域", "spell")

            def log(points: list[tuple[int, int]] | None = None) -> HogDecision | None:
                targets = cluster if points is None else points
                target_depth = deepest if points is None else max(y for _, y in targets)
                y = max(CN_HOG_LOG_Y_LIMITS[0], min(CN_HOG_LOG_Y_LIMITS[1], target_depth + 40))
                x = round(sum(point[0] for point in targets) / len(targets))
                return play("log", (x, y), "沿已观测压力位置滚木清理/推退", "spell")

            # First v3.1 match: five-plus clustered markers crossed the left
            # bridge while Fireball was ready, but a single-target Musketeer
            # was placed first. Clear a large observed cluster before it grows
            # into tower pressure; do not assume an unknown group is on ground.
            if len(cluster) >= 7 and "air" not in associated and self._ready("log", now, 5):
                decision = log(cluster)
                if decision:
                    return decision
            if len(fireball_cluster) >= 5 and cluster_depth >= OWN_PRESSURE_Y:
                if "swarm" in associated and "air" not in associated and self._ready("log", now, 5):
                    decision = log(associated["swarm"])
                    if decision:
                        return decision
                if self._ready("fireball", now, 5):
                    decision = fireball()
                    if decision:
                        return decision

            if associated:
                local_units = [point for point in units if math.dist(point, focus) <= THREAT_ASSOCIATION_RADIUS]
                # An ineffective earlier Cannon must not block the first
                # effective Musketeer against confirmed local air pressure.
                if "air" in associated:
                    first_air_output = (
                        now - self.last_defense_by_card.get((lane, "musketeer"), -math.inf) >= CORE_BUDGET_SECONDS
                    )
                    if self._ready("musketeer", now, CORE_REPLAY_COOLDOWN) and (
                        first_air_output or core_allowed("musketeer")
                    ):
                        decision = play("musketeer", musketeer_point, "已确认近场空中威胁，优先火枪输出", "defense")
                        if decision:
                            return decision
                    # Mixed classifications retain the proven ground response
                    # below. A pure-air response never spends Cannon/Log or
                    # Skeletons just because the effective card is unavailable.
                    if not (associated.keys() & {"rush", "swarm"}):
                        decision = cheap_delay(("ice_spirit",))
                        if decision:
                            return decision
                        if (
                            "musketeer" not in available
                            and (len(local_units) >= 2 or urgent)
                            and self._ready("fireball", now, 5)
                        ):
                            return fireball(local_units)
                        return None

                if "swarm" in associated:
                    if self._ready("log", now, 5):
                        decision = log(associated["swarm"])
                        if decision:
                            return decision
                    if (len(local_units) >= 2 or urgent) and self._ready("fireball", now, 5):
                        decision = fireball(local_units)
                        if decision:
                            return decision
                    decision = cheap_delay()
                    if decision:
                        return decision

                if "rush" in associated:
                    first_lane_cannon = (
                        now - self.last_defense_by_card.get((lane, "cannon"), -math.inf) >= CORE_BUDGET_SECONDS
                    )
                    if (
                        not deep
                        and cannon_covers_target
                        and self._ready("cannon", now, CORE_REPLAY_COOLDOWN)
                        and (first_lane_cannon or core_allowed("cannon"))
                    ):
                        decision = play(
                            "cannon", CN_HOG_CANNON_POINTS[lane], "已确认近场冲塔威胁，及时中置炮牵引", "defense"
                        )
                        if decision:
                            return decision
                    decision = cheap_delay(("skeletons", "ice_spirit"))
                    if decision:
                        return decision
                    # The first confirmed rush templates are building-targeting
                    # Hog Riders: Ice Golem cannot pull or tank them. Without
                    # a Cannon use delay/damage, never spend on that assumption.
                    if core_allowed("musketeer"):
                        return play("musketeer", musketeer_point, "冲塔防守缺少炮与低费牌，火枪补充输出", "defense")
                    return None

            if persistent_bridge:
                # Stable near-bridge pressure must not be discarded again by
                # the generic y300 defense gates or used to justify a Hog.
                if core_allowed("musketeer"):
                    decision = play("musketeer", musketeer_point, "持续桥头压力，近位火枪提供通用输出", "defense")
                    if decision:
                        return decision
                if "musketeer" not in available and elixir >= 6 and self._ready("fireball", now, 5):
                    return fireball([focus])
                return cheap_delay(("ice_spirit",)) if elixir >= 3 else None

            if (
                recent_core
                and now - recent_core[0] < CORE_DEFENSE_WAIT_SECONDS
                and not tower_damaged_recently
                and deepest < recent_core[2] + 35
                and len(units) < recent_core[1] + 2
            ):
                if deepest >= 315:
                    decision = cheap_delay()
                    if decision:
                        return decision
                return None

            if not covered and elixir <= 3 and not urgent:
                decision = cheap_delay() if deepest >= 315 else None
                if decision:
                    return decision
                if "cannon" not in available or not core_allowed("cannon"):
                    return None

            # Dense pressure close to the tower needs immediate area damage.
            # Affordability still comes exclusively from the observed hand.
            if (
                len(fireball_cluster) >= 3
                and cluster_depth >= 360
                and (elixir >= 6 or cluster_depth >= 405)
                and self._ready("fireball", now, 5)
            ):
                decision = fireball()
                if decision:
                    return decision
            if len(units) == 1 and deepest >= 330 and elixir < 6 and core_allowed("musketeer"):
                decision = play("musketeer", musketeer_point, "少费时保留唯一通用对空/地输出", "defense")
                if decision:
                    return decision
            # Unknown troop types: Musketeer supplies ground/air damage; Cannon is not the sole defense.
            if (deepest >= 300 or len(units) >= 2) and core_allowed("musketeer"):
                decision = play("musketeer", musketeer_point, "火枪在后侧提供防守输出", "defense")
                if decision:
                    return decision
            if len(fireball_cluster) >= 3 and self._ready("fireball", now, 5):
                decision = fireball()
                if decision:
                    return decision
            # Preserve the old low-cost fallback when no general-purpose
            # response is available; never let it consume that response's fee.
            if len(units) >= 2 and deepest >= 320 and self._ready("log", now, 5):
                decision = log()
                if decision:
                    return decision
            if OWN_PRESSURE_Y <= deepest < 400 and core_allowed("cannon"):
                decision = play("cannon", CN_HOG_CANNON_POINTS[lane], "中置炮吸引进攻单位", "defense")
                if decision:
                    return decision
            if deepest >= 315:
                decision = cheap_delay()
                if decision:
                    return decision
            if deepest >= 335 and (covered or elixir >= 4 or deep) and self._ready("ice_golem", now, 8):
                decision = play("ice_golem", kite_point, "精英冰人向中场牵引承伤", "defense")
                if decision:
                    return decision
            # A single unidentified target may be airborne; spend the Log only
            # after available damage, cheap delay and kiting have been tried.
            if urgent and self._ready("log", now, 5):
                return log()
            return None  # no offensive spending while pressure remains

        # The isolated deep-dark cue is only a candidate until it moves at
        # least 18 px toward us on a later frame. This keeps stationary siege
        # art from triggering a blind Cannon. Pilot 11 B9 had Cannon in hand
        # at y253 but cycled Spirit and attacked before the Cannon went down.
        if not own_enemies and dark_ground_approaches:
            approach = max(dark_ground_approaches, key=lambda item: item["y"])
            lane = "left" if approach["x"] < CN_HOG_LANE_SPLIT_X else "right"
            known_air = any(
                t["kind"] == "air" and (t["x"] < CN_HOG_LANE_SPLIT_X) == (lane == "left") for t in valid_threats
            )
            pressure_lane, pressure_count = lane, 1
            pressure_depth, threat_kind = approach["y"], "ground_mass"
            if not known_air and elixir >= 5 and self._ready("cannon", now, CORE_REPLAY_COOLDOWN):
                decision = play("cannon", CN_HOG_CANNON_POINTS[lane], "深色地面单位持续向塔推进，提前中置炮", "defense")
                if decision:
                    return decision
            if elixir >= 6 and self._ready("musketeer", now, CORE_REPLAY_COOLDOWN):
                decision = play(
                    "musketeer", CN_HOG_MUSKETEER_POINTS[lane], "大型推进将过桥，同路火枪先建立输出", "defense"
                )
                if decision:
                    return decision
            return None
        # Require a clear interval after defense before committing the win condition.
        if own_enemies or now - self.last_pressure_at < 3:
            return None
        if dark_ground_candidates and elixir < 10:
            return None  # keep Cannon fee while a one-frame dark cue awaits motion
        # Pilot 06 B4 spent its last readily usable Cannon fee on a Hog while
        # one real opposite-lane plaque was already approaching the bridge.
        # Wait for a safer reserve or the next frame before committing.
        if single_river_warning and warning_lane is None and elixir < 8:
            return None
        if warning_lane is not None and self.far_warning_frames == 1 and self.pending_hog_until <= now:
            return None
        warning_reserve = min(6, 2 + warning_count) if self.far_warning_frames >= 2 else 0
        lane = self.attack_lane
        if self.pending_hog_until > now:
            if "hog" in available and elixir >= 7:
                reason = (
                    "已确认冰精灵前置，跟进野猪并至少保留3费"
                    if self.pending_hog_is_spirit
                    else "已确认冰人前置，跟进野猪并至少保留3费"
                )
                return play("hog", CN_HOG_BRIDGE_POINTS[lane], reason, "attack")
            return None  # a transient unavailable Hog must not be delayed by an unrelated cycle play
        if self.pending_hog_until <= now:
            self.pending_hog_until = 0.0
            self.pending_hog_is_spirit = False

        # A nearly broken tower is a real spell target. Wait for a second
        # readable frame before spending, without cycling away the available
        # Fireball in that short interval. Immediate defense above wins first.
        def finishable(side: str) -> bool:
            fill = (enemy_tower_fill or {}).get(side)
            if fill is None:
                return False
            reserve = 0 if fill <= ONE_SPELL_TOWER_FILL else 2
            return (
                fill <= ONE_SPELL_TOWER_FILL or now - self.started_at >= LATE_SPELL_START_SECONDS
            ) and elixir >= COSTS["fireball"] + reserve

        finish_targets = [side for side in ("left", "right") if self.low_tower_frames[side] >= 1 and finishable(side)]
        if finish_targets and "fireball" in available and self._ready("fireball", now, 5):
            side = min(finish_targets, key=lambda item: numeric_tower_fills[item])
            if self.low_tower_frames[side] == 1:
                return None
            return play("fireball", CN_HOG_ENEMY_PRINCESS_TOWER_POINTS[side], "连续确认低血敌塔，火球收尾", "spell")
        # The frozen pilot B1 showed seven real same-lane labels near the
        # bridge with a ready Fireball. Waiting for them to cross delayed area
        # damage by 16 seconds. Keep the five-marker and affordability gates;
        # a scattered or single far-side unit is not a spell target.
        warning_points = far_left if warning_lane == "left" else far_right
        near_bridge_group = warning_reserve and warning_count >= 3 and max(y for _, y in warning_points) >= 250
        early_air = any(
            t["kind"] == "air" and (t["x"] < CN_HOG_LANE_SPLIT_X) == (warning_lane == "left") for t in valid_threats
        )
        if (
            near_bridge_group
            and 3 <= warning_count <= 5
            and not early_air
            and "cannon" in available
            and elixir >= 5
            and self._ready("cannon", now, CORE_REPLAY_COOLDOWN)
        ):
            pressure_lane, pressure_count = warning_lane, warning_count
            pressure_depth = max(y for _, y in warning_points)
            return play(
                "cannon",
                CN_HOG_CANNON_POINTS[cast("str", warning_lane)],
                "同路敌群贴近河道，先下炮牵引再考虑火球",
                "defense",
            )
        if warning_reserve and "fireball" in available and elixir >= 6 and self._ready("fireball", now, 5):
            lane_points = far_left if warning_lane == "left" else far_right
            cluster = max(
                ([other for other in lane_points if math.dist(point, other) <= 43] for point in lane_points), key=len
            )
            if len(cluster) >= 5 and max(y for _, y in cluster) >= 245:
                x = round(sum(point[0] for point in cluster) / len(cluster))
                # Pilot 07 B2 cast at y227 while the advancing Skeleton Army
                # reached y300 before impact. Lead the deepest observed plaque
                # toward our side; the ordinary near-tower spell rule is separate.
                y = min(CN_HOG_FIREBALL_MAX_Y, max(point[1] for point in cluster) + 35)
                return play("fireball", (x, y), "桥前同路密集敌群，火球提前削弱", "spell")
        if (
            warning_reserve
            and "musketeer" in available
            and elixir >= COSTS["musketeer"] + warning_reserve
            and self._ready("musketeer", now, CORE_REPLAY_COOLDOWN)
        ):
            pressure_lane = warning_lane
            pressure_count = warning_count
            pressure_depth = max(y for x, y in (far_left if warning_lane == "left" else far_right))
            return play(
                "musketeer",
                CN_HOG_MUSKETEER_POINTS[cast("str", warning_lane)],
                "桥前成组敌军预警，同路火枪提前准备并保留防守费用",
                "defense",
            )
        if near_bridge_group and "ice_spirit" in available and elixir >= 5 and self._ready("ice_spirit", now, 3):
            pressure_lane, pressure_count = warning_lane, warning_count
            pressure_depth = max(y for _, y in warning_points)
            return play(
                "ice_spirit",
                CN_HOG_STALL_POINTS[cast("str", warning_lane)],
                "桥前敌军逼近，冰精灵在同路提前拖延",
                "defense",
            )
        last_hog = self.last_play.get("hog", -math.inf)
        if now - last_hog < 7 and self.supported_hog_at < last_hog and elixir >= 4:
            decision = play("ice_spirit", CN_HOG_SUPPORT_POINTS[lane], "野猪后跟冰精灵，仍保留3费", "attack")
            if decision:
                return decision

        # A first blind Hog at seven elixir left too little for an immediate
        # counterpush in several frozen losses. Once a real defense has been
        # made, return to the normal three-elixir Hog cycle.
        opening_hog = "hog" not in self.last_play and self.categories["defense"] == 0 and now - self.started_at < 10
        reserve = 5 if opening_hog else 3
        opening_hand_incomplete = (
            opening_hog and now - self.started_at < 5 and any(item.get("card") is None for item in hand)
        )
        if "hog" in available and not opening_hand_incomplete and self._ready("hog", now, 6):
            if (
                "ice_golem" in available
                and elixir >= 6 + max(reserve, warning_reserve)
                and self._ready("ice_golem", now, 9)
            ):
                return play("ice_golem", CN_HOG_BRIDGE_POINTS[lane], "精英冰人桥头前置，准备猪进攻", "attack")
            if (
                not warning_reserve
                and "cannon" not in available
                and "musketeer" in available
                and elixir >= 8
                and self._ready("musketeer", now, CORE_REPLAY_COOLDOWN)
            ):
                return play(
                    "musketeer", CN_HOG_DUAL_LANE_MUSKETEER_POINT, "炮尚未到手，中央火枪先建立两路输出", "cycle"
                )
            if (
                not warning_reserve
                and "ice_spirit" in available
                and elixir >= (10 if opening_hog else 8)
                and self._ready("ice_spirit", now, 3)
            ):
                return play("ice_spirit", CN_HOG_SUPPORT_POINTS[lane], "冰精灵先手支援野猪，预留3费防守", "attack")
            required_reserve = max(reserve, warning_reserve)
            if elixir >= COSTS["hog"] + required_reserve:
                return play("hog", CN_HOG_BRIDGE_POINTS[lane], f"单猪桥头消耗，预留{required_reserve}费防守", "attack")

        # When Hog is out of hand, cycle while retaining at least three elixir.
        # Keep Cannon/Musketeer and all untargeted spells for defense.
        # Prefer the 1-cost cards to avoid repeatedly consuming the Ice Golem
        # that is needed for a real Hog combination or defensive kiting.
        cycle_threshold = (5 if enemies else 4) if "hog" not in available else 8
        if elixir >= cycle_threshold:
            for card in ("skeletons", "ice_spirit"):
                if warning_reserve and elixir - COSTS[card] < warning_reserve:
                    continue
                if self._ready(card, now, 3):
                    decision = play(card, CN_HOG_BACK_POINTS[lane], "低费过牌找野猪，保留至少3费与防守核心", "cycle")
                    if decision:
                        return decision
        # Never bridge-invest Ice Golem when Hog is absent. At full elixir,
        # back-cycle it before committing the only anti-air Musketeer to one
        # lane; pilot 06 B3 lost the unguarded opposite Princess Tower.
        if (
            not warning_reserve
            and elixir >= 6
            and set(available) == {"ice_golem", "cannon", "fireball", "log"}
            and self._ready("ice_golem", now, 9)
        ):
            return play("ice_golem", CN_HOG_BACK_POINTS[lane], "精确四卡锁手，后置冰人解手并保留至少4费", "cycle")
        hog_ready = "hog" in available and self._ready("hog", now, 6)
        if elixir == 10 and not hog_ready:
            if len(available) == 4 and "ice_golem" in available and self._ready("ice_golem", now, 9):
                return play("ice_golem", CN_HOG_BACK_POINTS[lane], "满费时后置冰人解手，保留火枪和炮防守", "cycle")
            if self._ready("musketeer", now, CORE_REPLAY_COOLDOWN):
                decision = play(
                    "musketeer", CN_HOG_DUAL_LANE_MUSKETEER_POINT, "满费时中央火枪解手，保留两路防守输出", "cycle"
                )
                if decision:
                    return decision
        return None

    def record(self, decision: HogDecision, confirmed: bool, now: float) -> None:
        self.last_attempt = now
        if not confirmed:
            return
        self.last_play[decision.card] = now
        self.categories[decision.category] += 1
        if decision.card in ("cannon", "musketeer") and decision.category == "defense" and decision.lane is not None:
            self.last_core_defense[decision.lane] = (now, decision.pressure_count, decision.pressure_depth)
            self.last_defense_by_card[(decision.lane, decision.card)] = now
            self.core_spending.append((now, decision.lane, COSTS[decision.card]))
            self.last_unsupported_delay.pop(decision.lane, None)
        elif (
            decision.card in ("ice_spirit", "skeletons")
            and decision.category == "defense"
            and decision.lane is not None
        ):
            core = self.last_core_defense.get(decision.lane)
            if not core or now - core[0] >= 10:
                self.last_unsupported_delay[decision.lane] = (now, decision.pressure_count, decision.pressure_depth)
        if decision.card == "ice_golem" and decision.category == "attack":
            self.pending_hog_until = now + 7
            self.pending_hog_is_spirit = False
        elif (
            decision.card == "ice_spirit"
            and decision.category == "attack"
            and decision.reason.startswith("冰精灵先手支援野猪")
        ):
            self.pending_hog_until = now + 6
            self.pending_hog_is_spirit = True
        elif decision.card == "hog":
            if self.pending_hog_is_spirit:
                self.supported_hog_at = now
            self.pending_hog_until = 0.0
            self.pending_hog_is_spirit = False
        elif decision.card == "ice_spirit" and decision.category == "attack":
            self.supported_hog_at = self.last_play.get("hog", -math.inf)
