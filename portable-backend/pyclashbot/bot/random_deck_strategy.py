"""Deterministic random-deck policy with current visual evidence as spending gates."""

# Chinese user-facing status intentionally uses full-width punctuation.
# ruff: noqa: RUF001
import math
from dataclasses import dataclass, replace
from typing import Any, TypedDict

from pyclashbot.bot.coords import (
    CN_HOG_FRIENDLY_TOWER_BOXES,
    CN_RANDOM_BUILDING_COVERAGE,
    CN_RANDOM_ENEMY_KING_POINT,
    CN_RANDOM_INTERCEPT_BOUNDS,
    CN_RANDOM_INTERCEPT_OFFSET_Y,
    CN_RANDOM_POLICY_POINTS,
    CN_RANDOM_SPELL_POINTS,
    CN_RANDOM_SUPPORT_Y_OFFSET,
    CN_RANDOM_TOWER_MARGIN,
)
from pyclashbot.bot.random_card_roles import canonical, mirrorable, role_for, special_capabilities
from pyclashbot.detection.cn_threats import approved_threat

STRATEGY_VERSION = "random-rules-v2.4-20261004-loss-review"
FULL_ELIXIR_IDLE_SECONDS = 8.0
INFERRED_SUPPORT_SECONDS = 3.5
IDLE_TOWER_SPELLS = frozenset({"arrows", "zap", "snowball", "fireball", "poison", "lightning", "rocket", "earthquake"})


@dataclass(frozen=True)
class RandomDecision:
    slot: int
    card: str
    variant: str
    point: tuple[int, int]
    category: str
    reason: str
    lane: str
    cost: int
    reserve: int
    target: tuple[int, int] | None = None
    urgent: bool = False
    mirrored_card: str | None = None
    inferred_support: bool = False


class RandomWave(TypedDict):
    lane: str
    at: float
    until: float
    heavy: bool
    supports: int
    inferred_support_used: bool


class RandomDeckStrategy:
    def __init__(self, started_at):
        self.started_at = started_at
        self.last_attempt = -math.inf
        self.last_heavy = -math.inf
        self.last_building = -math.inf
        self.last_defense = -math.inf
        self.last_by_card = {}
        self.attack_lane = "left"
        self.pressure_frames = 0
        self.last_pressure_at = -math.inf
        self.stable_pressure = []
        self.seen_cards = {}
        self.seen_variants = set()
        self.wave: RandomWave | None = None
        self.observation: dict[str, Any] = {}
        self.last_confirmed = None
        self.last_defense_lane = "left"
        self.last_seen_pressure = -math.inf
        self.defense_commits = {}
        self.failed_slots = {}
        self.previous_targets = []
        self.previous_scan = started_at
        self.velocity = {}
        self.full_elixir_since = None
        self.defense_budget = {}

    @staticmethod
    def lane(point):
        return "left" if point[0] < 209 else "right"

    def profile(self):
        values = list(self.seen_cards.values())
        cores = [c.name for c in values if c.win_condition]
        if any(c.role == "tank" and c.cost >= 5 for c in values):
            mode = "重型主攻＋后排支援"
        elif any(c.role == "siege" for c in values):
            mode = "建筑控场＋防守反击"
        elif any(c.role in ("rush", "remote_win") for c in values):
            mode = "快速主攻＋低费轮转"
        else:
            mode = "稳健防守反击"
        special = {
            name: special_capabilities(name)
            for name in sorted(self.seen_variants)
            if special_capabilities(name)["ability"] != "not_applicable" or name == "mirror"
        }
        return {
            "mode": mode,
            "identified_cards": len(values),
            "attack_cores": cores,
            "average_cost": round(sum(c.cost for c in values) / len(values), 2) if values else None,
            "special_mechanics": special,
        }

    def _hold(self, reason, **evidence):
        self.observation = {
            "reason": reason,
            "profile": self.profile(),
            "defense_budget": self.defense_budget,
            **evidence,
        }

    def _decision(self, item, card, category, reason, lane, reserve=0, point=None, target=None, inferred_support=False):
        if point is None:
            zone = {
                "defense": "support" if card.role == "ranged" or card.air else "intercept",
                "building": "building",
                "prepare": "back",
                "attack": "bridge",
                "support": "support",
                "cycle": "back",
                "siege": "siege",
                "remote": "remote",
            }[category]
            point = CN_RANDOM_POLICY_POINTS[zone][lane]
        mirrored = item.get("mirrored_card")
        actual_name = "mirror" if mirrored else card.name
        variant = item.get("variant") or actual_name
        urgent = target is not None and target[1] >= 335
        self.observation = {
            "reason": reason,
            "category": category,
            "reserve": reserve,
            "profile": self.profile(),
            "mirrored_card": mirrored,
            "inferred_support": inferred_support,
            "defense_budget": self.defense_budget,
        }
        return RandomDecision(
            item["slot"],
            actual_name,
            variant,
            point,
            category,
            reason,
            lane,
            card.cost,
            reserve,
            target,
            urgent,
            mirrored,
            inferred_support,
        )

    def _safe_friendly_point(self, point, lane):
        x1, y1, x2, y2 = CN_RANDOM_INTERCEPT_BOUNDS
        x, y = max(x1, min(x2, point[0])), max(y1, min(y2, point[1]))
        for a, b, c, d in CN_HOG_FRIENDLY_TOWER_BOXES.values():
            if (
                a - CN_RANDOM_TOWER_MARGIN <= x <= c + CN_RANDOM_TOWER_MARGIN
                and b - CN_RANDOM_TOWER_MARGIN <= y <= d + CN_RANDOM_TOWER_MARGIN
            ):
                if a < 209 < c:
                    x = a - CN_RANDOM_TOWER_MARGIN - 1 if lane == "left" else c + CN_RANDOM_TOWER_MARGIN + 1
                else:
                    x = c + CN_RANDOM_TOWER_MARGIN + 1 if c < 209 else a - CN_RANDOM_TOWER_MARGIN - 1
        return int(max(x1, min(x2, x))), int(y)

    def _intercept(self, target):
        """Predict only from this frame's visible enemy, avoiding friendly towers."""
        vx, vy = self.velocity.get(target, (0, 0))
        point = (
            target[0] + max(-12, min(12, round(vx * 0.35))),
            target[1] + CN_RANDOM_INTERCEPT_OFFSET_Y + max(0, min(16, round(vy * 0.35))),
        )
        return self._safe_friendly_point(point, self.lane(target))

    def _building_covers(self, card, target):
        """Conservative placement coverage; late targets must still be in range."""
        radius = CN_RANDOM_BUILDING_COVERAGE.get(card.name, 80)
        vx, vy = self.velocity.get(target, (0, 0))
        projected = (
            target[0] + max(-12, min(12, vx * 0.35)),
            target[1] + CN_RANDOM_INTERCEPT_OFFSET_Y + max(0, min(16, vy * 0.35)),
        )
        return target[1] < 365 or math.dist(projected, CN_RANDOM_POLICY_POINTS["building"][self.lane(target)]) <= radius

    def _attack_object(self, cues, preferred, *, require_confirmed=False):
        """Return a living princess or explicitly observed king, never a destroyed tower."""
        towers = cues.get("enemy_towers") or {}
        lanes = [side for side in ("left", "right") if towers.get(side) is True]
        fills = cues.get("enemy_tower_fill") or {}
        if lanes:
            measured = [
                side
                for side in lanes
                if isinstance(fills.get(side), (float, int)) and math.isfinite(fills[side]) and 0 < fills[side] <= 1
            ]
            if preferred in lanes:
                other = "right" if preferred == "left" else "left"
                if (
                    other in measured
                    and preferred in measured
                    and not self.wave
                    and fills[preferred] - fills[other] > 0.18
                ):
                    preferred = other
                return preferred
            return min(measured, key=lambda side: fills[side]) if measured else lanes[0]
        if towers.get("left") is False and towers.get("right") is False:
            return "king" if towers.get("king") is True else None
        if require_confirmed:
            return None
        return preferred if towers.get(preferred) is not False else ("right" if preferred == "left" else "left")

    def _attack_decision(self, item, card, category, reason, cues, preferred, reserve=0):
        attack_object = self._attack_object(cues, preferred, require_confirmed=category == "remote")
        if attack_object is None:
            return None
        lane = preferred if attack_object == "king" else attack_object
        point = (
            (CN_RANDOM_ENEMY_KING_POINT if attack_object == "king" else CN_RANDOM_POLICY_POINTS["remote"][lane])
            if category == "remote"
            else None
        )
        return self._decision(item, card, category, reason, lane, reserve, point=point)

    def _idle_special(self, ready, cues, now, *, allow_graveyard=True, reserve=0):
        """Resolve full-elixir special hands only with a legal observed target."""
        if self.full_elixir_since is None or now - self.full_elixir_since < FULL_ELIXIR_IDLE_SECONDS:
            return None
        attack_object = self._attack_object(cues, self.attack_lane, require_confirmed=True)
        if attack_object is None:
            return None
        lane = self.attack_lane if attack_object == "king" else attack_object
        elixir = cues.get("elixir")
        if elixir is None:
            return None
        spells = [
            (item, card) for item, card in ready if card.name in IDLE_TOWER_SPELLS and elixir - card.cost >= reserve
        ]
        if spells:
            item, card = min(spells, key=lambda pair: pair[1].cost)
            point = CN_RANDOM_ENEMY_KING_POINT if attack_object == "king" else CN_RANDOM_SPELL_POINTS[lane]
            return self._decision(
                item, card, "spell", "持续满圣水未能轮转，法术攻击确认存活的敌塔", lane, reserve, point=point
            )
        graveyards = [
            (item, card) for item, card in ready if card.name == "graveyard" and elixir - card.cost >= reserve
        ]
        if graveyards and allow_graveyard:
            item, card = graveyards[0]
            return self._attack_decision(
                item, card, "remote", "持续满圣水特殊手牌，墓园攻击确认存活的敌塔解手", cues, lane, max(2, reserve)
            )
        return None

    def _ready_cards(self, hand, elixir, now):
        ready = []
        for raw_item in hand:
            item = dict(raw_item)
            name, variant = item.get("card"), item.get("variant") or item.get("card")
            if not name or canonical(variant) != canonical(name):
                continue
            card = role_for(variant, item.get("cost"))
            if card is None:
                continue
            self.seen_cards[card.name] = card
            self.seen_variants.add(variant)
            if card.role == "mirror":
                prior = self.last_confirmed
                if prior is None or prior.card == "mirror" or not mirrorable(prior.variant):
                    continue
                source = role_for(prior.variant, prior.cost)
                if source is None or prior.cost >= 10:
                    continue
                card = replace(source, cost=prior.cost + 1)
                item["mirrored_card"] = source.name
            failed = self.failed_slots.get(item["slot"], {})
            blocked = failed.get("card") == name and now < failed.get("until", 0)
            if (
                elixir is not None
                and item.get("available") is True
                and not blocked
                and card.cost <= elixir
                and now - self.last_by_card.get(name, -math.inf) >= 1.8
            ):
                ready.append((item, card))
        return ready

    def _current_targets(self, cues, now):
        pressure = [tuple(point) for point in cues.get("enemies", []) if point[1] >= 275]
        self.velocity = {}
        dt = now - self.previous_scan
        if 0 < dt <= 2:
            for point in pressure:
                old = min(self.previous_targets, key=lambda p: math.dist(p, point), default=None)
                if old is not None and math.dist(old, point) <= 50:
                    self.velocity[point] = ((point[0] - old[0]) / dt, (point[1] - old[1]) / dt)
        self.previous_targets, self.previous_scan = pressure, now
        self.pressure_frames = self.pressure_frames + 1 if pressure else 0
        if pressure:
            self.last_seen_pressure = now
        if self.pressure_frames >= 2 or any(point[1] >= 335 for point in pressure):
            self.stable_pressure = pressure
            self.last_pressure_at = now
        elif not pressure and now - self.last_seen_pressure > 0.8:
            self.stable_pressure = []
        # Cached pressure can reserve budget, but never authorizes spending at old coordinates.
        targets = list(pressure) if self.pressure_frames >= 2 or any(p[1] >= 335 for p in pressure) else []
        threats = [t for t in cues.get("threats", []) if approved_threat(t)]
        for threat in threats:
            if threat.get("kind") == "air" and threat.get("y", 0) >= 215:
                point = (int(threat["x"]), int(threat["y"]))
                if point not in targets:
                    targets.append(point)
                self.last_pressure_at = now
        return targets, threats

    def _defensive_budget(self, hand, ready, cues, now):
        """Reserve an observed response, without authorizing a cached-target cast.

        An identified but unaffordable card still needs its full budget. Keep
        the only identified air answer in hand while pressure is approaching;
        a back-line cycle is not proof it can reach an opposite-lane threat.
        """
        danger = bool(cues.get("far_warnings")) or now - self.last_pressure_at < 4
        defenders = []
        for item in hand:
            name, variant = item.get("card"), item.get("variant") or item.get("card")
            if not name or canonical(variant) != canonical(name):
                continue
            card = role_for(variant, item.get("cost"))
            if card and card.role in ("fighter", "ranged", "swarm", "building"):
                defenders.append((item, card))
        air = [(item, card) for item, card in defenders if card.air]
        ready_air = [
            (item, card) for item, card in ready if card.air and card.role in ("ranged", "swarm", "fighter", "building")
        ]
        reliable = [card for _, card in defenders if card.cost >= 3 or card.role == "building"]
        reserve = 3 if danger else 2
        if danger:
            if reliable:
                reserve = max(reserve, min(card.cost for card in reliable))
            if ready_air or air:
                reserve = max(reserve, min(card.cost for _, card in ready_air or air))
        protected = {ready_air[0][0]["slot"]} if danger and len(ready_air) == 1 else set()
        self.defense_budget = {
            "pressure_recent_or_approaching": danger,
            "reserve": reserve,
            "protected_air_slots": sorted(protected),
        }
        return reserve, protected, danger

    @staticmethod
    def _reserve_after_spend(item, ready, reserve, danger):
        """Do not count the card being cycled as the response left in hand."""
        if not danger:
            return reserve
        remaining = [
            card
            for other, card in ready
            if other["slot"] != item["slot"] and card.role in ("fighter", "ranged", "swarm", "building")
        ]
        effective = [card for card in remaining if card.cost >= 3 or card.role == "building"]
        air = [card for card in remaining if card.air]
        if effective:
            reserve = max(reserve, min(card.cost for card in effective))
        if air:
            reserve = max(reserve, min(card.cost for card in air))
        return reserve

    def decide(self, hand, cues, now):
        elixir = cues.get("elixir")
        if elixir == 10:
            if self.full_elixir_since is None:
                self.full_elixir_since = now
        else:
            self.full_elixir_since = None
        self._hold("等待圣水或可靠手牌识别")
        ready = self._ready_cards(hand, elixir, now)
        targets, threats = self._current_targets(cues, now)
        reserve, protected, danger = self._defensive_budget(hand, ready, cues, now)
        far = cues.get("far_warnings", [])
        if self.wave and now > self.wave["until"]:
            self.wave = None
        emergency = any(p[1] >= 335 for p in targets)
        if not ready or elixir is None:
            return self._hold("等待圣水或可执行手牌；镜像需已确认且可复制的上一张牌")
        if now - self.last_attempt < (0.25 if emergency else 0.55):
            return self._hold("已下牌，等待手牌轮转后继续决策")
        if targets:
            own_fills = cues.get("own_tower_fill", {})

            def urgency(point):
                health = own_fills.get(self.lane(point))
                return point[1] + (25 if isinstance(health, (float, int)) and 0 < health < 0.4 else 0)

            target = max(targets, key=urgency)
            lane = self.lane(target)
            cluster = [p for p in targets if math.dist(p, target) <= 70]
            air = any(t.get("kind") == "air" and math.dist((t["x"], t["y"]), target) <= 70 for t in threats)
            heavy = any(t.get("heavy") and math.dist((t["x"], t["y"]), target) <= 70 for t in threats)
            untyped = not any(math.dist((t["x"], t["y"]), target) <= 70 for t in threats)
            allies = [tuple(p) for p in cues.get("allies", []) if self.lane(p) == lane and math.dist(p, target) <= 110]
            committed = self.defense_commits.get(lane)
            if target[1] < 365 and committed and now - committed["at"] < 2 and allies and (not air or committed["air"]):
                return self._hold("已有可见友军接敌，保留圣水并观察防守结果")
            defenders = [
                (item, c)
                for item, c in ready
                if c.role in ("fighter", "swarm", "ranged", "building", "cycle")
                and (not air or c.air)
                and (c.role != "building" or (now - self.last_building >= 7 and self._building_covers(c, target)))
            ]

            def score(pair):
                _, c = pair
                return (
                    int(c.air and air) * 9
                    + int(c.splash and len(cluster) >= 2) * 7
                    + int(c.air and untyped) * 2
                    + int(c.tank_killer and heavy) * 8
                    + int(c.role == "building") * 2
                    + int(c.role in ("fighter", "ranged", "swarm") and c.cost >= 3) * 2
                    - c.cost * 0.8
                )

            value_spells = [
                (item, c)
                for item, c in ready
                if c.role == "small_spell" and len(cluster) >= 3 and (not air or c.name not in {"log", "barb_barrel"})
            ]
            if value_spells:
                item, card = min(value_spells, key=lambda pair: pair[1].cost)
                point = (int(sum(p[0] for p in cluster) / len(cluster)), int(sum(p[1] for p in cluster) / len(cluster)))
                return self._decision(
                    item, card, "spell", "当前可见密集敌军优先用低费法术处理", lane, point=point, target=target
                )
            if defenders:
                item, card = max(defenders, key=score)
                category = "building" if card.role == "building" else "defense"
                reason = (
                    "优先对空防守"
                    if air
                    else "群体来袭，优先范围防守"
                    if len(cluster) >= 2 and card.splash
                    else "当前可见敌军进入我方，及时拦截后反击"
                )
                point = None
                if card.role != "building":
                    point = (
                        CN_RANDOM_POLICY_POINTS["support_front" if target[1] < 330 else "support"][lane]
                        if card.role == "ranged" or card.air
                        else self._intercept(target)
                    )
                return self._decision(item, card, category, reason, lane, point=point, target=target)
            spells = [
                (item, c)
                for item, c in ready
                if c.role in ("small_spell", "large_spell", "control_spell")
                and c.name not in {"freeze", "earthquake", "vines"}
                and (not air or c.name not in {"log", "barb_barrel", "royal_delivery"})
                and (c.role == "small_spell" or len(cluster) >= 2 or target[1] >= 365)
            ]
            if spells:
                item, card = min(spells, key=lambda pair: pair[1].cost)
                point = (
                    int(sum(p[0] for p in cluster) / len(cluster)),
                    min(470, int(sum(p[1] for p in cluster) / len(cluster) + 14)),
                )
                return self._decision(
                    item, card, "spell", "法术处理当前可见的敌军目标", lane, point=point, target=target
                )
            freezes = [(item, c) for item, c in ready if c.name == "freeze" and allies and (heavy or len(cluster) >= 2)]
            if freezes:
                item, card = freezes[0]
                return self._decision(
                    item, card, "spell", "当前敌军与可见友军交战，冰冻为友军争取输出", lane, point=target, target=target
                )
            idle = self._idle_special(ready, cues, now, allow_graveyard=not emergency, reserve=reserve)
            return idle if idle else self._hold("当前防守牌无法覆盖目标，保留圣水等待有效响应")
        attack_object = self._attack_object(cues, self.attack_lane)
        if attack_object in ("left", "right"):
            self.attack_lane = attack_object
        lane = self.attack_lane
        if self.wave:
            wave_lane = self.wave["lane"]
            same_lane_allies = [tuple(p) for p in cues.get("allies", []) if self.lane(p) == wave_lane]
            if same_lane_allies and any(p[1] < 275 for p in same_lane_allies):
                graveyards = [(item, c) for item, c in ready if c.name == "graveyard" and elixir - c.cost >= reserve]
                if graveyards:
                    item, card = graveyards[0]
                    decision = self._attack_decision(
                        item, card, "remote", "当前可见友军过河，墓园配合推进", cues, wave_lane, reserve
                    )
                    if decision:
                        return decision
            buffs = [(item, c) for item, c in ready if c.role == "buff" and elixir - c.cost >= reserve]
            if buffs and len(same_lane_allies) >= 2 and now - self.wave["at"] >= 2:
                group = max(
                    ([p for p in same_lane_allies if math.dist(p, anchor) <= 90] for anchor in same_lane_allies),
                    key=len,
                )
                if len(group) >= 2:
                    item, card = min(buffs, key=lambda pair: pair[1].cost)
                    point = (int(sum(p[0] for p in group) / len(group)), int(sum(p[1] for p in group) / len(group)))
                    return self._decision(
                        item, card, "buff", "当前可见友军集结后使用增益法术", wave_lane, reserve, point=point
                    )
            age = now - self.wave["at"]
            inferred = (
                not same_lane_allies
                and age <= INFERRED_SUPPORT_SECONDS
                and not self.wave.get("inferred_support_used", False)
            )
            supports = [
                (item, c)
                for item, c in ready
                if c.role in ("ranged", "swarm", "fighter", "cycle")
                and item["slot"] not in protected
                and elixir - c.cost >= self._reserve_after_spend(item, ready, reserve, danger)
                and age >= 1.2
                and self.wave.get("supports", 0) < 2
                and (same_lane_allies or (inferred and c.cost <= 3))
            ]
            if supports:
                item, card = min(supports, key=lambda pair: (not pair[1].air, pair[1].cost))
                if same_lane_allies:
                    anchor = min(same_lane_allies, key=lambda p: p[1])
                    point = self._safe_friendly_point((anchor[0], anchor[1] + CN_RANDOM_SUPPORT_Y_OFFSET), wave_lane)
                    reason = "以当前可见友军为锚点，在其后方跟进支援"
                else:
                    point = CN_RANDOM_POLICY_POINTS["back_support" if self.wave.get("heavy") else "push_support"][
                        wave_lane
                    ]
                    reason = "刚确认主攻部署，限一次低费推断支援并等待友军证据"
                return self._decision(
                    item,
                    card,
                    "support",
                    reason,
                    wave_lane,
                    self._reserve_after_spend(item, ready, reserve, danger),
                    point=point,
                    inferred_support=not same_lane_allies,
                )
            if elixir < 9:
                return self._hold("主攻存活或支援位置证据不足，保留圣水等待友军与防守信息")
        if now - self.last_defense <= 6:
            cores = [
                (item, c)
                for item, c in ready
                if c.win_condition
                and c.role in ("rush", "remote_win")
                and c.name != "graveyard"
                and elixir - c.cost >= reserve
            ]
            for item, card in sorted(cores, key=lambda pair: pair[1].cost):
                decision = self._attack_decision(
                    item,
                    card,
                    "remote" if card.role == "remote_win" else "attack",
                    "防守后沿原路组织反击",
                    cues,
                    self.last_defense_lane,
                    reserve,
                )
                if decision:
                    return decision
        cores = [
            (item, c)
            for item, c in ready
            if c.win_condition
            and elixir - c.cost >= (reserve if danger else min(reserve, 10 - c.cost))
            and elixir >= max(5, c.cost + (reserve if danger else min(reserve, 10 - c.cost)))
            and c.name != "graveyard"
            and (c.role != "tank" or now - self.last_heavy >= 14)
        ]
        if cores and not far and not self.wave:
            for item, card in sorted(
                cores, key=lambda pair: (pair[1].role == "tank" and pair[1].cost >= 7, pair[1].cost)
            ):
                category = (
                    "prepare"
                    if card.role == "tank"
                    else "siege"
                    if card.role == "siege"
                    else "remote"
                    if card.role == "remote_win"
                    else "attack"
                )
                decision = self._attack_decision(
                    item,
                    card,
                    category,
                    "按卡组主攻核心推进，并保留防守圣水",
                    cues,
                    lane,
                    reserve if danger else min(reserve, 10 - card.cost),
                )
                if decision:
                    return decision
        visible_cores = [
            self.seen_cards[item["card"]]
            for item in hand
            if item.get("card") in self.seen_cards
            and self.seen_cards[item["card"]].win_condition
            and self.seen_cards[item["card"]].cost >= 5
            and item["card"] != "graveyard"
        ]
        if visible_cores and not far and not self.wave:
            planned = min(visible_cores, key=lambda c: c.cost)
            required = max(5, planned.cost + (reserve if danger else min(reserve, 10 - planned.cost)))
            if elixir < required:
                return self._hold("主攻牌已在手，积攒主攻与防守预算")
        utility = [
            (item, c)
            for item, c in ready
            if c.role in ("fighter", "ranged", "swarm", "cycle")
            and item["slot"] not in protected
            and elixir - c.cost >= self._reserve_after_spend(item, ready, reserve, danger)
            and (elixir >= 8 or (c.cost <= 3 and elixir >= 5))
        ]
        if utility:
            item, card = min(utility, key=lambda pair: (pair[1].cost, pair[1].role != "ranged"))
            return self._decision(
                item,
                card,
                "cycle",
                "低费后场轮转，避免圣水溢出并保留应急预算",
                lane,
                self._reserve_after_spend(item, ready, reserve, danger),
            )
        if elixir >= 9 and not far:
            buildings = [
                (item, c)
                for item, c in ready
                if c.role in ("building", "collector")
                and now - self.last_building >= 12
                and elixir - c.cost >= self._reserve_after_spend(item, ready, reserve, danger)
            ]
            if buildings:
                item, card = min(buildings, key=lambda pair: pair[1].cost)
                return self._decision(
                    item,
                    card,
                    "building",
                    "满水且场面平稳，布置建筑",
                    lane,
                    self._reserve_after_spend(item, ready, reserve, danger),
                )
        idle = self._idle_special(ready, cues, now, reserve=reserve)
        if idle:
            return idle
        return self._hold(
            "等待合法目标与组合；冰冻需当前交战，克隆需可见友军，镜像需可复制部署",
            unexecutable_cards=[item["card"] for item, _ in ready],
            target_status="king_unobserved" if attack_object is None else "awaiting_combination",
        )

    def record(self, decision, confirmed, now):
        self.last_attempt = now
        if not confirmed:
            self.failed_slots[decision.slot] = {"card": decision.card, "until": now + 1.2}
            return
        self.full_elixir_since = None
        self.last_by_card[decision.card] = now
        self.last_confirmed = decision
        effective = role_for(decision.mirrored_card or decision.variant, decision.cost)
        if decision.target is not None:
            self.last_defense = now
            self.last_defense_lane = decision.lane
            if decision.category in ("defense", "building"):
                self.defense_commits[decision.lane] = {"at": now, "air": bool(effective and effective.air)}
        if decision.category == "building":
            self.last_building = now
        if decision.category in ("attack", "prepare", "remote", "siege"):
            heavy = decision.category == "prepare" and decision.cost >= 5
            self.wave = {
                "lane": decision.lane,
                "at": now,
                "until": now + (20 if heavy else 7),
                "heavy": heavy,
                "supports": 0,
                "inferred_support_used": False,
            }
        elif decision.category == "support" and self.wave:
            self.wave["supports"] = self.wave.get("supports", 0) + 1
            if decision.inferred_support:
                self.wave["inferred_support_used"] = True
        if decision.category == "prepare" and decision.cost >= 5:
            self.last_heavy = now
