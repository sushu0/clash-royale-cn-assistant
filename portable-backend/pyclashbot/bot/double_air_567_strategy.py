"""Small 4.0 policy: defend, observe survivors, then tank and one support.

Visual hints are partial evidence. A successful input is never a defeated enemy
or a surviving ally. No victory/defeat or win-rate criterion affects decisions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict, cast

from pyclashbot.bot.coords import CN_567_BOMBER_LINE_POINTS, CN_567_POINTS, CN_567_ROCKET_DISTANCE_BAND

COSTS = {
    "pekka": 7,
    "goblin_giant": 6,
    "goblin_machine": 5,
    "baby_dragon": 4,
    "mega_minion": 3,
    "bomber": 2,
    "arrows": 3,
    "zap": 2,
}
AIR_DEFENDERS = {"baby_dragon", "mega_minion"}
SPELLS = {"arrows", "zap"}
POLICY_VERSION = "double-air-567-v4-budget-cycle-20260929"
MIN_ACTION_INTERVAL = 1.6

Point = tuple[int, int]


class EnemyTrack(TypedDict):
    point: Point
    anchor: Point
    first: float
    seen: float
    frames: int
    motion: int
    domain: NotRequired[str | None]
    heavy_until: NotRequired[float]
    small_until: NotRequired[float]
    ground_motion: NotRequired[int]


class DefenderTrack(TypedDict):
    card: str
    variant: NotRequired[str | None]
    point: Point
    deployed: float
    seen: float
    frames: int
    visible: bool


class AttackWave(TypedDict):
    lane: str
    at: float
    supported: bool
    air: bool
    card: NotRequired[str]
    point: NotRequired[Point]
    origin: NotRequired[str]


@dataclass(frozen=True)
class Decision:
    slot: int
    card: str
    variant: str | None
    point: tuple[int, int]
    reason: str
    category: str
    elixir: int
    lane: str
    threat_kind: str = "none"
    reserve: int = 0


class DoubleAir567Strategy:
    def __init__(self, started_at: float):
        self.started_at = started_at
        self.last_attempt = -math.inf
        self.last_heavy = -math.inf
        self.last_play = {}
        self.categories = {}
        self.tracks: list[EnemyTrack] = []
        self.defenders: list[DefenderTrack] = []
        self.quiet_since: float | None = None
        self.wave: AttackWave | None = None
        self.last_pressure = {"left": -math.inf, "right": -math.inf}
        self.last_defense_cycle = -math.inf
        self.observation: dict[str, Any] = {}
        self.attack_lane: str = "left"
        self.lane_candidate: str | None = None
        self.lane_candidate_frames = 0
        self.lane_observed_at = -math.inf

    def _update_attack_lane(self, towers, fills, now):
        """Use repeated readable bars; never treat unknown or zero as lethal HP."""
        if now <= self.lane_observed_at:
            return
        if now - self.lane_observed_at > 3:
            self.lane_candidate_frames = 0
        self.lane_observed_at = now
        towers, fills = towers or {}, fills or {}
        other = "right" if self.attack_lane == "left" else "left"
        candidate = None
        if towers.get(self.attack_lane) is False and towers.get(other) is True:
            candidate = other
        elif all(
            towers.get(side) is True
            and isinstance(fills.get(side), (int, float))
            and not isinstance(fills.get(side), bool)
            and math.isfinite(fills[side])
            and 0 < fills[side] <= 1
            for side in ("left", "right")
        ):
            if fills[self.attack_lane] - fills[other] >= 0.12:
                candidate = other
        self.lane_candidate_frames = (
            self.lane_candidate_frames + 1 if candidate and candidate == self.lane_candidate else int(bool(candidate))
        )
        self.lane_candidate = candidate
        if self.lane_candidate_frames >= 3 and not self.wave and candidate is not None:
            self.attack_lane = candidate
            self.lane_candidate_frames = 0

    @staticmethod
    def lane(point):
        return "left" if point[0] < 209 else "right"

    @staticmethod
    def _rocket_point(target, lane):
        low, high = CN_567_ROCKET_DISTANCE_BAND
        points = [CN_567_POINTS[name][lane] for name in ("support", "defend", "deep", "front")]
        valid = [p for p in points if low <= math.dist(p, target) <= high]
        return min(valid, key=lambda p: abs(math.dist(p, target) - (low + high) / 2)) if valid else None

    @staticmethod
    def _is_evolved_bomber(item):
        return bool(
            item
            and item.get("card") == "bomber"
            and item.get("variant") in {"evo_bomber", "cn_evo_bomber"}
            and item.get("evolution_ready", True)
        )

    @staticmethod
    def _bomber_defense_point(target, lane):
        # A straight lane shot can continue through the front unit. Do not
        # force that alignment when the threat is already beside our tower.
        if target[1] <= 305:
            return CN_567_BOMBER_LINE_POINTS["front"][lane]
        if target[1] >= 405:
            return CN_567_POINTS["back"][lane]
        if target[1] >= 370:
            return CN_567_BOMBER_LINE_POINTS["back"][lane]
        return CN_567_POINTS["support"][lane]

    @staticmethod
    def _rear_support_point(tank_point, lane, card):
        if tank_point[1] <= 310:
            return CN_567_BOMBER_LINE_POINTS["front"][lane] if card == "bomber" else CN_567_POINTS["defend"][lane]
        if tank_point[1] <= 390:
            return CN_567_POINTS["deep"][lane]
        return CN_567_BOMBER_LINE_POINTS["back"][lane] if card == "bomber" else CN_567_POINTS["back"][lane]

    def _observe(self, cues: dict[str, Any], now: float):
        points: list[Point] = []
        for raw in cues.get("enemies", []) + cues.get("far_warnings", []):
            point = cast("Point", tuple(raw))
            if not any(math.dist(point, other) <= 7 for other in points):
                points.append(point)
        previous = self.tracks
        self.tracks = []
        used = set()
        for point in points:
            matches = [
                (i, old)
                for i, old in enumerate(previous)
                if i not in used and now - old["seen"] <= 3 and math.dist(point, old["point"]) <= 35
            ]
            if matches:
                i, old = min(matches, key=lambda item: math.dist(item[1]["point"], point))
                used.add(i)
                anchor = old["anchor"] if math.dist(point, old["anchor"]) <= 4 else point
                first = old["first"] if anchor == old["anchor"] else now
                self.tracks.append(
                    {
                        "point": point,
                        "anchor": anchor,
                        "first": first,
                        "seen": now,
                        "frames": old["frames"] + int(now > old["seen"]),
                        "motion": point[1] - old["point"][1],
                        "domain": old.get("domain"),
                        "heavy_until": old.get("heavy_until", 0),
                        "small_until": old.get("small_until", 0),
                        "ground_motion": max(0, old.get("ground_motion", 0) + point[1] - old["point"][1]),
                    }
                )
            else:
                self.tracks.append(
                    {"point": point, "anchor": point, "first": now, "seen": now, "frames": 1, "motion": 0}
                )
        live_allies = [tuple(p) for p in cues.get("allies", [])]
        occupied = set()
        # Continuous tracks claim their anchors before newly deployed units.
        # Unseen old deployments cannot later steal a fresh unit's identity.
        self.defenders.sort(key=lambda d: (d["frames"] > 0, d["seen"], d["deployed"]), reverse=True)
        for defender in self.defenders:
            defender["visible"] = False
            if (
                now - defender["deployed"] > 35
                or (defender["frames"] == 0 and now - defender["deployed"] > 8)
                or (defender["frames"] > 0 and now - defender["seen"] > 3.5)
            ):
                continue
            gap = now - defender["seen"]
            radius = min(140, 35 + 18 * (now - defender["deployed"])) if defender["frames"] == 0 else 25 + 8 * gap
            matches = [
                (i, p)
                for i, p in enumerate(live_allies)
                if i not in occupied
                and self.lane(p) == self.lane(defender["point"])
                and p[1] <= defender["point"][1] + 25
                and math.dist(p, defender["point"]) <= radius
            ]
            if matches:
                i, point = min(matches, key=lambda item: math.dist(item[1], defender["point"]))
                occupied.add(i)
                defender.update(point=point, seen=now, frames=defender["frames"] + 1, visible=True)
        self.defenders = [d for d in self.defenders if now - d["deployed"] <= 35]
        if points:
            self.quiet_since = None
        elif self.quiet_since is None:
            self.quiet_since = now
        self.observation = {
            "tracks": self.tracks,
            "survivors": self.defenders,
            "quiet_seconds": 0 if self.quiet_since is None else round(now - self.quiet_since, 2),
        }
        return points

    def decide(self, hand, elixir, enemies, now, enemy_towers=None, **cues):
        cues["enemies"] = enemies
        points = self._observe(cues, now)
        self._update_attack_lane(enemy_towers, cues.get("enemy_tower_fill"), now)
        self.observation["attack_lane"] = self.attack_lane
        if elixir is None or now - self.last_attempt < MIN_ACTION_INTERVAL:
            return None
        ready = {
            h["card"]: h
            for h in hand
            if h.get("card") in COSTS
            and h.get("available")
            and COSTS[h["card"]] <= elixir
            and now - self.last_play.get(h["card"], -math.inf) >= 3.5
        }
        in_hand = {h["card"] for h in hand if h.get("card") in COSTS}
        evolved_bomber = self._is_evolved_bomber(ready.get("bomber"))
        threats = [
            t
            for t in cues.get("threats", []) or []
            if t.get("kind") in {"air", "rush", "swarm", "ground", "reset", "small_swarm"}
            and t.get("confidence", 0)
            >= (
                0.78
                if t.get("template_id") == "567_ground_drill_torso"
                else 0.74
                if t.get("template_id") == "air_skeleton_barrel_top"
                else 0.78
                if t.get("template_id") == "air_balloon_envelope"
                else 0.88
            )
        ]
        pressure = []
        for track in self.tracks:
            x, y = track["point"]
            associated = [t for t in threats if math.dist((x, y), (t["x"], t["y"])) <= 12]
            air = any(t["kind"] == "air" for t in associated)
            ground = any(t["kind"] in {"rush", "ground"} for t in associated)
            heavy = any(t["kind"] == "rush" or t.get("heavy") is True for t in associated)
            small = any(t.get("small") is True or t["kind"] == "small_swarm" for t in associated)
            ground |= any(t.get("role") == "ground_swarm" for t in associated)
            dark = any(math.dist((x, y), (d["x"], d["y"])) <= 25 for d in cues.get("dark_ground_candidates", []) or [])
            ground |= dark and track.get("ground_motion", 0) >= 6 and not air
            if heavy:
                track["heavy_until"] = now + 6
            if small:
                track["small_until"] = now + 4
            heavy |= track.get("heavy_until", 0) >= now and not air
            small |= track.get("small_until", 0) >= now and not air
            if air or ground:
                track["domain"] = "air" if air else "ground"
            air |= track.get("domain") == "air"
            ground |= track.get("domain") == "ground"
            # Preserve static bridge/siege pressure independently of motion.
            siege = 190 <= y < 300 and track["frames"] >= 3 and now - track["first"] >= 2.5
            if y >= 280 or (air and y >= 210) or (ground and y >= 250) or siege:
                nearby = [p for p in points if math.dist(p, (x, y)) <= 55]
                swarm = len(nearby) >= 3 or any(t["kind"] in {"swarm", "small_swarm"} for t in associated)
                kind = (
                    "air_swarm"
                    if air and swarm
                    else "air"
                    if air
                    else "siege"
                    if siege
                    else "ground_swarm"
                    if ground and swarm
                    else "swarm"
                    if swarm
                    else "ground_heavy"
                    if ground and heavy
                    else "ground_small"
                    if ground and small
                    else "ground"
                    if ground
                    else "unknown"
                )
                lane = self.lane((x, y))
                hp = (cues.get("own_tower_fill") or {}).get(lane)
                urgency = y + (80 if air else 0) + (45 if siege or heavy else 0) + 8 * len(nearby)
                if hp is not None and hp < 0.3:
                    urgency += 45
                pressure.append((urgency, lane, kind, (x, y), track["frames"], associated))
                self.last_pressure[lane] = now
        pressure.sort(reverse=True)
        self.observation["pressure"] = [{"lane": p[1], "kind": p[2], "point": p[3], "urgency": p[0]} for p in pressure]

        def choose(card, lane, point, reason, category, kind="none", reserve=0):
            if card not in ready:
                return None
            h = ready[card]
            return Decision(h["slot"], card, h.get("variant"), point, reason, category, elixir, lane, kind, reserve)

        for _, lane, kind, target, frames, associated in pressure:
            if pressure[0][3][1] >= 370 and math.dist(pressure[0][3], target) > 90:
                continue  # do not spend the king-tower response on a distant bridge target
            if frames < 2 and target[1] < 355:
                continue
            # Evolution is a ground splash/support upgrade, never an air
            # answer. Prefer it for a verified ground group before spending
            # Arrows or the two dedicated air defenders, unless the group is
            # already at the tower and needs an immediate spell response.
            if evolved_bomber and kind in {"ground_small", "ground_swarm"} and target[1] < 355:
                return choose(
                    "bomber",
                    lane,
                    self._bomber_defense_point(target, lane),
                    "confirmed evolved Bomber for verified ground splash",
                    "defense",
                    kind,
                )
            # Spells need an actual clustered target or a recognized reset target.
            nearby = [p for p in points if math.dist(p, target) <= 55]
            clearable = any(t.get("small") or t["kind"] in {"swarm", "small_swarm"} for t in associated)
            if (
                "swarm" in kind
                and "arrows" in ready
                and (clearable or (len(nearby) >= 4 and "baby_dragon" not in ready))
            ):
                return choose("arrows", lane, target, "visible compact enemy group", "defense", kind)
            if "zap" in ready and (
                any(t["kind"] == "reset" for t in associated)
                or (clearable and len(nearby) >= 2 and kind.startswith("ground"))
            ):
                return choose("zap", lane, target, "observed reset/clear target", "defense", kind)
            order = (
                {
                    "air": ("mega_minion", "baby_dragon", "goblin_machine"),
                    "air_swarm": ("baby_dragon", "mega_minion", "goblin_machine"),
                    "ground_heavy": ("pekka", "goblin_machine", "mega_minion", "baby_dragon", "bomber"),
                    "ground": ("mega_minion", "goblin_machine", "baby_dragon", "pekka", "bomber"),
                    "ground_small": ("bomber", "baby_dragon", "mega_minion", "goblin_machine"),
                    "ground_swarm": ("bomber", "baby_dragon", "goblin_machine"),
                    "swarm": ("baby_dragon", "bomber", "mega_minion", "goblin_machine"),
                    "siege": ("pekka", "goblin_machine", "mega_minion", "baby_dragon"),
                    "unknown": ("baby_dragon", "mega_minion", "goblin_machine"),
                }
            )[kind]
            # Reassess the visible threat after each play. Briefly allow an
            # observed compatible defender to engage, without declaring success.
            covering = [
                d
                for d in self.defenders
                if d["visible"]
                and d["frames"] >= 2
                and self.lane(d["point"]) == lane
                and math.dist(d["point"], target) <= 95
                and (kind not in {"air", "air_swarm", "unknown"} or d["card"] in AIR_DEFENDERS)
            ]
            if covering and now - max(d["deployed"] for d in covering) < 4 and target[1] < 370:
                if evolved_bomber and kind.startswith("ground") and any(d["card"] == "pekka" for d in covering):
                    tank = next(d for d in covering if d["card"] == "pekka")
                    return choose(
                        "bomber",
                        lane,
                        self._rear_support_point(tank["point"], lane, "bomber"),
                        "evolved ground support behind an observed defending PEKKA",
                        "defense_support",
                        kind,
                    )
                continue
            for card in order:
                if card not in ready:
                    continue
                # An untyped swarm may be airborne: bomber alone is not a valid counter.
                if kind == "swarm" and card == "bomber":
                    continue
                if card == "goblin_machine" and kind in {"air", "air_swarm", "unknown", "swarm"}:
                    point = self._rocket_point(target, lane)
                    if point is None:
                        continue
                    return choose(
                        card,
                        lane,
                        point,
                        "secondary rocket can target air/ground outside melee dead zone",
                        "defense",
                        kind,
                    )
                placement = "front" if kind == "siege" else "deep" if target[1] >= 370 else "defend"
                if card in AIR_DEFENDERS or card == "bomber":
                    placement = "deep" if target[1] >= 370 else "support"
                if card == "bomber" and evolved_bomber:
                    return choose(
                        card,
                        lane,
                        self._bomber_defense_point(target, lane),
                        "evolved Bomber ground defense; preserve a rear firing position",
                        "defense",
                        kind,
                    )
                return choose(
                    card, lane, CN_567_POINTS[placement][lane], "live threat still requires defense", "defense", kind
                )
        # Unresolved or newly seen pressure forbids committing to an attack.
        if pressure:
            # A cheap transition can reveal a real counter when all known
            # anti-air answers are out of hand. This is NOT a claimed defense:
            # keep the threat unresolved, reserve four elixir, re-read next hand.
            _, lane, kind, target, frames, _ = pressure[0]
            if (
                kind in {"unknown", "swarm", "air", "air_swarm"}
                and frames >= 2
                and target[1] >= 310
                and "bomber" in ready
                and not (in_hand & AIR_DEFENDERS)
                and elixir >= 6
                and now - self.last_defense_cycle >= 8
            ):
                placement = "deep" if target[1] >= 370 else "support"
                point = self._bomber_defense_point(target, lane) if evolved_bomber else CN_567_POINTS[placement][lane]
                return choose(
                    "bomber",
                    lane,
                    point,
                    (
                        "unresolved target; evolved Bomber emergency transition from protected rear"
                        if evolved_bomber
                        else "unresolved target; cheap transition to draw a compatible counter"
                    ),
                    "defense_cycle",
                    kind,
                    reserve=4,
                )
            # The four-card heavy/spell lock also occurs with Bomber out of
            # hand. Zap a CURRENT near target once to draw the next card. Its
            # identity and survival remain unknown; this is not a kill/reset
            # claim. Never cycle a spell on an empty board or a far warning.
            if (
                kind in {"unknown", "swarm", "air", "air_swarm"}
                and frames >= 2
                and target[1] >= 310
                and "zap" in ready
                and "bomber" not in in_hand
                and not (in_hand & AIR_DEFENDERS)
                and elixir >= 6
                and now - self.last_defense_cycle >= 8
            ):
                return choose(
                    "zap",
                    lane,
                    target,
                    "visible near threat; bounded Zap transition to draw a compatible counter",
                    "defense_cycle",
                    kind,
                    reserve=4,
                )
            self.observation["wait_reason"] = "unresolved_threat_no_compatible_ready_counter"
            return None
        if points or self.quiet_since is None or now - self.quiet_since < 3:
            return None
        # A destroyed/occluded tower has no readable bar. It cannot veto every
        # attack forever; demand a longer quiet board instead of inventing HP.
        if any(value is None for value in (cues.get("own_tower_fill") or {}).values()) and now - self.quiet_since < 8:
            return None
        single = now - self.started_at < 120
        heavy_ready = not (single and now - self.last_heavy < 9)

        def reserve_for(card):
            candidates = [COSTS[c] for c in in_hand if c not in (card, "goblin_giant")]
            # Preserve an actually held answer to air when committing six elixir.
            air_costs = [COSTS[c] for c in in_hand & AIR_DEFENDERS if c != card]
            return min(air_costs) if air_costs else max(3, min(candidates, default=7))

        survivors = [
            d
            for d in self.defenders
            if d["visible"] and d["frames"] >= 2 and 285 <= d["point"][1] <= 365 and d["card"] != "goblin_giant"
        ]
        if self.wave and now - self.wave["at"] > 24:
            self.wave = None
        if self.wave:
            lane = self.wave["lane"]
            tank = next(
                (
                    d
                    for d in self.defenders
                    if d["visible"]
                    and d["frames"] >= 2
                    and d["card"] == "goblin_giant"
                    and self.lane(d["point"]) == lane
                    and 280 <= d["point"][1] <= 420
                ),
                None,
            )
            # A recently confirmed safe rear Giant can take one cheap follower
            # before its undamaged level plaque appears. This is a bounded
            # inference only for a quiet rear start, never proof that an enemy
            # was defended or that a front-line survivor is still alive.
            recent_rear_start = (
                self.wave.get("origin") == "attack"
                and self.wave.get("card") == "goblin_giant"
                and tuple(self.wave.get("point", ())) == CN_567_POINTS["back"][lane]
                and 2 <= now - self.wave["at"] <= 6
            )
            if (tank or recent_rear_start) and not self.wave["supported"]:
                candidates = ("bomber", "goblin_machine", "mega_minion", "baby_dragon") if tank else ("bomber",)
                for card in candidates:
                    if COSTS[card] >= 5 and not heavy_ready:
                        continue
                    # Never put both dedicated anti-air cards into this attack.
                    if card in AIR_DEFENDERS and self.wave["air"]:
                        continue
                    reserve = reserve_for(card)
                    if card in ready and elixir - COSTS[card] >= reserve:
                        point = (
                            self._rear_support_point(tank["point"], lane, card) if tank else CN_567_POINTS["back"][lane]
                        )
                        basis = "observed tank" if tank else "recent confirmed rear Giant; fresh quiet board"
                        self.observation["support_basis"] = basis
                        return choose(
                            card,
                            lane,
                            point,
                            "one support behind "
                            + basis
                            + ("; evolved Bomber" if card == "bomber" and evolved_bomber else ""),
                            "support",
                            reserve=reserve,
                        )
            return None
        reserve = reserve_for("goblin_giant")
        if heavy_ready and "goblin_giant" in ready and elixir - 6 >= reserve:
            if survivors:
                lead = min(survivors, key=lambda d: d["point"][1])
                lane = self.lane(lead["point"])
                return choose(
                    "goblin_giant",
                    lane,
                    CN_567_POINTS["front"][lane],
                    "observed surviving defender; quiet opposite lane",
                    "counterpush",
                    reserve=reserve,
                )
            if elixir == 10 and now - self.quiet_since >= 6:
                lane = self.attack_lane
                if enemy_towers and enemy_towers.get(lane) is False:
                    lane = "right" if lane == "left" else "left"
                return choose(
                    "goblin_giant",
                    lane,
                    CN_567_POINTS["back"][lane],
                    "full elixir; safe start with held defense budget",
                    "attack",
                    reserve=reserve,
                )
        # When Giant is not in hand, one cheap support may prepare a safe wave.
        if elixir == 10 and now - self.quiet_since >= 8:
            preparation = (
                ("goblin_machine", "mega_minion", "baby_dragon", "bomber")
                if evolved_bomber
                else ("bomber", "mega_minion", "baby_dragon", "goblin_machine")
            )
            for card in preparation:
                if COSTS[card] >= 5 and not heavy_ready:
                    continue
                if card in AIR_DEFENDERS and any(
                    d["card"] in AIR_DEFENDERS and (d["visible"] or now - d["deployed"] < 8) for d in self.defenders
                ):
                    continue
                reserve = reserve_for(card)
                if elixir - COSTS[card] < reserve:
                    continue
                if card in ready and now - self.last_play.get(card, -math.inf) >= 15:
                    return choose(
                        card,
                        self.attack_lane,
                        CN_567_POINTS["back"][self.attack_lane],
                        "single low-cost preparation at full elixir",
                        "prepare",
                        reserve=reserve,
                    )
        return None

    def record(self, decision, confirmed, now):
        self.last_attempt = now
        if not confirmed:
            return
        self.last_play[decision.card] = now
        if decision.category == "defense_cycle":
            self.last_defense_cycle = now
        self.categories[decision.category] = self.categories.get(decision.category, 0) + 1
        if COSTS[decision.card] >= 5:
            self.last_heavy = now
        if decision.card not in SPELLS:
            self.defenders.append(
                {
                    "card": decision.card,
                    "variant": decision.variant,
                    "point": decision.point,
                    "deployed": now,
                    "seen": now,
                    "frames": 0,
                    "visible": False,
                }
            )
        if decision.category in {"counterpush", "attack"}:
            air = any(
                d["visible"] and d["card"] in AIR_DEFENDERS and self.lane(d["point"]) == decision.lane
                for d in self.defenders
            )
            self.wave = {
                "lane": decision.lane,
                "at": now,
                "supported": False,
                "air": air,
                "card": decision.card,
                "point": decision.point,
                "origin": decision.category,
            }
        elif decision.category == "support" and self.wave:
            self.wave["supported"] = True
            self.wave["air"] |= decision.card in AIR_DEFENDERS
