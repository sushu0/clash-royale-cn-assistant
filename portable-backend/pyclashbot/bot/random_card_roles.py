"""Card roles for random decks. Visual identity and live affordability remain gates."""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class CardRole:
    name: str
    cost: int
    role: str
    air: bool = False
    splash: bool = False
    tank_killer: bool = False
    win_condition: bool = False


TANKS = {"giant", "goblin_giant", "golem", "electro_giant", "lava_hound", "elixir_golem", "rune_giant"}
RUSH = {
    "hog",
    "ram_rider",
    "battle_ram",
    "royal_hogs",
    "wall_breakers",
    "skeleton_barrel",
    "suspicious_bush",
    "balloon",
    "royal_giant",
}
REMOTE = {"miner", "goblin_barrel", "goblin_drill", "graveyard"}
RANGED = {
    "archers",
    "musketeer",
    "wizard",
    "ice_wizard",
    "electro_wizard",
    "magic_archer",
    "dart_goblin",
    "fire_cracker",
    "flying_machine",
    "princess",
    "executioner",
    "bomber",
    "mother_witch",
    "witch",
    "night_witch",
    "archer_queen",
    "little_prince",
    "skeleton_dragons",
    "baby_dragon",
    "electro_dragon",
    "goblin_demolisher",
    "zappies",
    "goblin_machine",
    "sparky",
}
SWARMS = {
    "skeletons",
    "skeleton_army",
    "goblins",
    "spear_goblins",
    "goblin_gang",
    "bats",
    "minions",
    "minion_horde",
    "guards",
    "barbarians",
    "royal_recruits",
    "rascals",
}
AIR_TARGETS = {
    "archers",
    "musketeer",
    "wizard",
    "ice_wizard",
    "electro_wizard",
    "magic_archer",
    "dart_goblin",
    "fire_cracker",
    "flying_machine",
    "princess",
    "executioner",
    "mother_witch",
    "witch",
    "archer_queen",
    "little_prince",
    "hunter",
    "skeleton_dragons",
    "baby_dragon",
    "electro_dragon",
    "zappies",
    "spear_goblins",
    "goblin_gang",
    "rascals",
    "bats",
    "minions",
    "minion_horde",
    "mega_minion",
    "inferno_dragon",
    "phoenix",
    "tesla",
    "inferno_tower",
}
SPLASH = {
    "bomber",
    "wizard",
    "ice_wizard",
    "baby_dragon",
    "electro_dragon",
    "skeleton_dragons",
    "fire_cracker",
    "executioner",
    "bowler",
    "valkyrie",
    "dark_prince",
    "mega_knight",
    "royal_ghost",
    "goblin_demolisher",
    "bomb_tower",
}
TANK_KILLERS = {
    "pekka",
    "mini_pekka",
    "inferno_tower",
    "inferno_dragon",
    "mighty_miner",
    "hunter",
    "sparky",
    "elite_barbarians",
}
LARGE_SPELLS = {"fireball", "poison", "lightning", "rocket", "void"}
SMALL_SPELLS = {"arrows", "zap", "snowball", "log", "barb_barrel", "gob_curse"}
CONTROL_SPELLS = {"tornado", "freeze", "vines", "royal_delivery"}
BUFFS = {"rage", "clone"}
CHAMPIONS = {
    "archer_queen",
    "golden_knight",
    "skeleton_king",
    "mighty_miner",
    "monk",
    "little_prince",
    "goblinstein",
    "boss_bandit",
}


def mirrorable(name):
    """Mirror needs a confirmed ordinary deployment; abilities cannot be copied."""
    return bool(name and not name.startswith("hero_") and canonical(name) not in CHAMPIONS | {"mirror"})


def special_capabilities(name):
    """Report supported deployment separately from unobserved special mechanics."""
    base = canonical(name)
    if base == "mirror":
        return {"deployment": "confirmed_previous_card", "ability": "not_applicable"}
    if base in CHAMPIONS or (name and name.startswith("hero_")):
        return {"deployment": "ordinary_card", "ability": "unsupported_requires_visual_contract"}
    if base == "spirit_empress":
        return {"deployment": "observed_variant_cost", "ability": "variant_selected_by_game"}
    if name and name.startswith("evo_"):
        return {"deployment": "ordinary_card", "ability": "passive_game_managed"}
    return {"deployment": "ordinary_card", "ability": "not_applicable"}


def canonical(name):
    if not name:
        return None
    if name == "elite_ice_golem":
        return "ice_golem"
    for prefix in ("evo_", "hero_"):
        if name.startswith(prefix):
            return name[len(prefix) :]
    return {"spirit_empress_air": "spirit_empress", "spirit_empress_ground": "spirit_empress", "x_bow": "xbow"}.get(
        name, name
    )


@lru_cache(maxsize=1)
def catalog():
    path = Path(__file__).resolve().parents[1] / "detection/reference_images/cn_random_cards/card_catalog.json"
    result = json.loads(path.read_text(encoding="utf-8"))
    result.update(
        {
            "goblin_demolisher": {"cost": 4, "type": "Troop"},
            "rune_giant": {"cost": 4, "type": "Troop"},
            "boss_bandit": {"cost": 6, "type": "Troop"},
            "berserker": {"cost": 2, "type": "Troop"},
            "spirit_empress": {"cost": 6, "type": "Troop"},
            "suspicious_bush": {"cost": 2, "type": "Troop"},
            "goblin_machine": {"cost": 5, "type": "Troop"},
            "goblinstein": {"cost": 5, "type": "Troop"},
            "little_prince": {"cost": 3, "type": "Troop"},
            "vines": {"cost": 3, "type": "Spell"},
            "void": {"cost": 3, "type": "Spell"},
            "gob_curse": {"cost": 2, "type": "Spell"},
        }
    )
    return result


def role_for(name, observed_cost=None):
    base = canonical(name)
    item = catalog().get(base)
    if not item:
        return None
    cost = observed_cost if type(observed_cost) is int and 1 <= observed_cost <= 10 else int(item["cost"])
    if name == "spirit_empress_ground":
        cost = observed_cost if type(observed_cost) is int and 1 <= observed_cost <= 10 else 3
    if base in LARGE_SPELLS:
        role = "large_spell"
    elif base in SMALL_SPELLS:
        role = "small_spell"
    elif base in CONTROL_SPELLS:
        role = "control_spell"
    elif base in BUFFS:
        role = "buff"
    elif base == "mirror":
        role = "mirror"
    elif base in REMOTE:
        role = "remote_win"
    elif base in {"mortar", "xbow"}:
        role = "siege"
    elif base == "elixir_collector":
        role = "collector"
    elif item["type"] == "Building":
        role = "building"
    elif item["type"] == "Spell":
        role = "control_spell"
    elif base in TANKS:
        role = "tank"
    elif base in RUSH:
        role = "rush"
    elif base in RANGED:
        role = "ranged"
    elif base in SWARMS:
        role = "swarm"
    elif base in {"ice_spirit", "electro_spirit", "fire_spirit", "heal_spirit", "ice_golem"}:
        role = "cycle"
    else:
        role = "fighter"
    air = base in AIR_TARGETS or (base == "spirit_empress" and name != "spirit_empress_ground")
    return CardRole(
        base, cost, role, air, base in SPLASH, base in TANK_KILLERS, base in TANKS | RUSH | REMOTE | {"mortar", "xbow"}
    )
