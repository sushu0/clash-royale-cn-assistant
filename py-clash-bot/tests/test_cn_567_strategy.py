"""567 acceptance: actionable targets, survivor evidence, budgets and siege replay."""

from itertools import combinations
from pathlib import Path
from unittest.mock import Mock

import cv2
import pytest

from pyclashbot.bot.card_detection import identify_567_hand_frame
from pyclashbot.bot.cn_1v1_loop import ChineseOneVOneLoop, ChineseVision, RecoveryExhausted
from pyclashbot.bot.double_air_567_strategy import COSTS, SPELLS, Decision, DoubleAir567Strategy
from pyclashbot.detection.cn_battle_cues import read_cn_battle_cues


def read_frame(path):
    image = cv2.imread(path)
    assert image is not None, "Missing test fixture"
    return image


def hand(*cards):
    return [{"slot": i, "card": c, "variant": c, "available": True} for i, c in enumerate(cards)]


def decide(policy, cards, now, enemies=(), elixir=10, **extra):
    defaults = {"own_tower_fill": {"left": 1, "right": 1}, "far_warnings": [], "threats": []}
    defaults.update(extra)
    return policy.decide(hand(*cards), elixir, list(enemies), now, **defaults)


def test_deck_cost_and_machine_identity_are_distinct():
    assert sum(COSTS.values()) / 8 == 4.0
    assert COSTS["goblin_machine"] == 5
    assert "goblinstein" not in COSTS


def test_heavy_ground_uses_pekka_and_air_never_uses_ground_only_card():
    for kind, expected in (("rush", "pekka"), ("air", "mega_minion")):
        p = DoubleAir567Strategy(0)
        result = decide(
            p,
            ("pekka", "mega_minion", "bomber", "goblin_giant"),
            10,
            [(115, 380)],
            threats=[{"kind": kind, "confidence": 0.95, "x": 115, "y": 380}],
        )
        assert result.card == expected
        assert result.category == "defense"


def test_urgent_other_lane_prevents_counterpush():
    p = DoubleAir567Strategy(0)
    p.defenders = [{"card": "pekka", "point": (115, 330), "deployed": 8, "seen": 10, "frames": 3, "visible": True}]
    result = decide(
        p,
        ("goblin_giant", "mega_minion", "bomber", "zap"),
        11,
        [(303, 390)],
        allies=[(115, 330)],
        threats=[{"kind": "air", "confidence": 0.95, "x": 303, "y": 390}],
    )
    assert result.lane == "right" and result.card == "mega_minion"


def test_no_empty_spell_cycle_or_unobserved_survivor():
    p = DoubleAir567Strategy(0)
    for t in (1, 5, 10, 20):
        assert decide(p, ("arrows", "zap"), t) is None
    p = DoubleAir567Strategy(0)
    p.record(Decision(0, "pekka", "pekka", (137, 349), "defense", "defense", 10, "left"), True, 1)
    for t in (3, 4, 5):
        assert decide(p, ("goblin_giant", "mega_minion"), t, elixir=9) is None


def test_confirmed_survivor_can_counterpush_without_all_three_cores():
    p = DoubleAir567Strategy(0)
    p.record(Decision(0, "pekka", "pekka", (137, 349), "defense", "defense", 10, "left"), True, 1)
    decision = None
    for t in (2, 3, 4, 5, 6, 7, 8, 9, 10):
        decision = decide(p, ("goblin_giant", "mega_minion", "zap"), t, allies=[(137, 338)], elixir=9)
    assert decision is not None
    assert decision.card == "goblin_giant"
    assert decision.category == "counterpush"
    assert decision.reserve == 3


def test_no_blind_high_cost_chain_in_single_elixir():
    p = DoubleAir567Strategy(0)
    p.record(Decision(0, "pekka", None, (137, 349), "defend", "defense", 10, "left"), True, 1)
    for t in (2, 4, 6, 8):
        assert decide(p, ("goblin_giant", "mega_minion"), t) is None


def test_attack_reserves_held_defensive_card_cost():
    p = DoubleAir567Strategy(0)
    decide(p, ("goblin_giant", "baby_dragon", "arrows", "zap"), 1, elixir=9)
    assert decide(p, ("goblin_giant", "baby_dragon", "arrows", "zap"), 9, elixir=9) is None
    result = decide(p, ("goblin_giant", "baby_dragon", "arrows", "zap"), 10, elixir=10)
    assert result.card == "goblin_giant" and result.reserve == 4


def test_preparation_keeps_spell_or_troop_defense_reserve():
    p = DoubleAir567Strategy(0)
    cards = ("pekka", "baby_dragon", "arrows", "zap")
    decide(p, cards, 1)
    result = decide(p, cards, 10)
    assert result.card == "baby_dragon" and result.reserve == 3
    p = DoubleAir567Strategy(0)
    cards = ("pekka", "mega_minion", "baby_dragon", "zap")
    decide(p, cards, 1)
    result = decide(p, cards, 10)
    assert result.card == "mega_minion"
    assert result.elixir - COSTS[result.card] >= result.reserve == 4


def test_full_safe_heavy_hand_can_start_machine_while_holding_arrows():
    p = DoubleAir567Strategy(0)
    cards = ("pekka", "goblin_machine", "arrows", "zap")
    decide(p, cards, 1)
    result = decide(p, cards, 10)
    assert result.card == "goblin_machine" and result.category == "prepare"
    assert result.reserve == 3 and result.elixir - COSTS[result.card] >= 3
    p.record(result, True, 10)
    assert decide(p, cards, 12) is None


def test_all_seventy_opening_hands_have_a_safe_full_elixir_active_play():
    checked = 0
    for cards in combinations(COSTS, 4):
        p = DoubleAir567Strategy(0)
        assert decide(p, cards, 1) is None
        action = decide(p, cards, 10)
        assert action is not None, cards
        assert action.card not in SPELLS
        assert action.category in {"attack", "prepare"}
        assert action.elixir - COSTS[action.card] >= action.reserve >= 2
        checked += 1
    assert checked == 70


def test_recent_air_preparation_is_not_followed_by_the_other_air_card():
    p = DoubleAir567Strategy(0)
    p.record(Decision(0, "mega_minion", None, (165, 460), "prepare", "prepare", 10, "left"), True, 1)
    # v4 retains the opening protection and a continuously visible ally;
    # an unseen deployment no longer blocks an entire 25-second window.
    for t in range(2, 21):
        assert decide(p, ("baby_dragon", "pekka", "arrows", "zap"), t, allies=[(165, 455)]) is None


def test_two_air_defenders_not_sent_in_same_attack():
    p = DoubleAir567Strategy(0)
    p.wave = {"at": 1, "lane": "left", "supported": False, "air": True}
    p.defenders = [
        {"card": "goblin_giant", "point": (115, 330), "deployed": 1, "seen": 2, "frames": 3, "visible": True}
    ]
    for t in (3, 4, 5, 6, 7):
        result = decide(p, ("mega_minion", "baby_dragon", "arrows", "zap"), t, allies=[(115, 330)])
        assert result is None


def test_deploy_confirmation_never_clears_enemy_pressure():
    p = DoubleAir567Strategy(0)
    points = [(303, 390)]
    decision = decide(p, ("mega_minion", "goblin_giant"), 10, points)
    assert decision.category == "defense"
    p.record(decision, True, 11)
    result = decide(p, ("baby_dragon", "goblin_giant", "bomber"), 14, points)
    assert result.category == "defense" and result.card != "goblin_giant"


def test_frozen_stationary_siege_is_actionable_without_movement():
    frame = read_frame(str(Path(__file__).parent / "fixtures/cn_battle_cues/dark_ground_stationary_siege.png"))
    assert frame is not None, "Missing test fixture"
    cues = read_cn_battle_cues(frame, include_567=True)
    p = DoubleAir567Strategy(0)
    decision = None
    for t in (1, 2, 4):
        decision = decide(
            p, ("pekka", "goblin_machine", "arrows", "zap"), t, cues["enemies"], far_warnings=cues["far_warnings"]
        )
    assert decision is not None
    assert decision.category == "defense" and decision.threat_kind == "siege"
    assert decision.lane == "right"


def test_loss_never_stops_policy():
    # Results deliberately have no entry point in this policy.
    p = DoubleAir567Strategy(0)
    assert not hasattr(p, "win_rate")
    assert not hasattr(p, "loss_streak")


def test_recovery_exhaustion_is_terminal_and_does_not_restart_device():
    loop = ChineseOneVOneLoop.__new__(ChineseOneVOneLoop)
    loop.recovery_attempts = 3
    loop._trace = Mock()
    loop.logger = Mock()
    loop.device = Mock()
    with pytest.raises(RecoveryExhausted):
        loop._recover("test disconnect")
    loop.device.adb.assert_not_called()


def test_unknown_opening_tower_reading_is_not_zero_damage():
    loop = ChineseOneVOneLoop.__new__(ChineseOneVOneLoop)
    loop.opening_recorded = False
    loop.opening_samples = []
    loop.battle_resumed = False
    loop.completed = 0
    loop._trace = Mock()
    loop._finish_opening()
    assert loop.opening_result["left"]["observed_loss_fraction"] is None
    assert loop.opening_result["left"]["complete_45s_window"] is False


def test_real_classic_result_and_mode_guard():
    folder = Path(__file__).parent / "fixtures/cn_567"
    v = ChineseVision()
    frame = read_frame(str(folder / "classic_loss.png"))
    assert frame is not None, "Missing test fixture"
    assert v.classify(frame)[0] == "result"
    assert v.outcome(frame) == "失败"
    assert v.classic_selected(read_frame(str(folder / "classic1v1_lobby.png")))
    assert not v.classic_selected(read_frame(str(folder / "classic2v2_lobby.png")))


def test_rainbow_reward_open_and_reveal_are_handled_without_clicking_unknown():
    folder = Path(__file__).parent / "fixtures/cn_567"
    v = ChineseVision()
    for name in ("rainbow_open.png", "rainbow_reveal.png"):
        assert v.classify(read_frame(str(folder / name)))[0] == "reward"
    for name in ("hand_machine.png", "classic1v1_lobby.png", "classic2v2_lobby.png", "classic_loss.png"):
        assert v.classify(read_frame(str(folder / name)))[0] != "reward"


def test_real_machine_is_not_goblinstein_and_level11_swarm_is_visible():
    frame = read_frame(str(Path(__file__).parent / "fixtures/cn_567/hand_machine.png"))
    assert frame is not None, "Missing test fixture"
    observed = identify_567_hand_frame(frame)
    assert observed[1]["card"] == "goblin_machine" and observed[1]["available"]
    cues = read_cn_battle_cues(frame)
    assert len(cues["enemies"] + cues["far_warnings"]) >= 5


def test_ten_loop_gate_waits_for_reopening_and_preserves_unknown_results(tmp_path):
    loop = ChineseOneVOneLoop.__new__(ChineseOneVOneLoop)
    loop.cycle_pending = True
    loop.returned_lobby = True
    loop.closed_loops = 9
    loop.completed = 10
    loop.gate_passed = False
    loop.result_counts = {"胜利": 0, "失败": 9, "未知": 1}
    loop.total_deployment_failures = 2
    loop.validation_dir = tmp_path
    loop.strategy_name = "567"
    loop.logger = Mock()
    loop._trace = Mock()
    assert not (tmp_path / "validation-passed.json").exists()
    loop._begin_battle()
    assert loop.closed_loops == 10 and loop.gate_passed
    assert loop.result_counts["胜利"] == 0
    assert loop.result_counts["未知"] == 1
    assert (tmp_path / "validation-passed.json").exists()


def test_resume_does_not_count_as_a_full_reopened_loop(tmp_path):
    loop = ChineseOneVOneLoop.__new__(ChineseOneVOneLoop)
    loop.cycle_pending = True
    loop.returned_lobby = True
    loop.closed_loops = 9
    loop.completed = 10
    loop.gate_passed = False
    loop.validation_dir = tmp_path
    loop.strategy_name = "567"
    loop.logger = Mock()
    loop._trace = Mock()
    loop._begin_battle(resumed=True)
    assert loop.closed_loops == 0
    assert not loop.gate_passed
    assert not (tmp_path / "validation-passed.json").exists()
