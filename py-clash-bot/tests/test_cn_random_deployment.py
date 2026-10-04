"""Deployment must be proven by spend/cycle evidence, including one-elixir regen."""

from pathlib import Path

import cv2
import numpy as np

from pyclashbot.bot.coords import CN_RANDOM_HAND_ROIS
from pyclashbot.detection import cn_random_deployment as deployment


def images(monkeypatch, replacement):
    monkeypatch.setattr(deployment, "identify_random_hand", lambda _: [{"card": replacement}] * 4)
    return np.zeros((633, 419, 3), np.uint8), np.full((633, 419, 3), 90, np.uint8)


def test_regenerated_one_elixir_card_requires_two_replacement_frames(monkeypatch):
    before, after = images(monkeypatch, "knight")
    first = deployment.deployment_evidence(before, after, 0, "ice_spirit", 3, 3)
    assert not first["confirmed"]
    second = deployment.deployment_evidence(before, after, 0, "ice_spirit", 3, 3, first["after_card"])
    assert second["confirmed"] and second["method"] == "stable_replacement_card"


def test_selection_highlight_is_not_a_card_cycle(monkeypatch):
    before, after = images(monkeypatch, "ice_spirit")
    evidence = deployment.deployment_evidence(before, after, 0, "ice_spirit", 3, 3, "ice_spirit")
    assert not evidence["confirmed"]


def test_elixir_drop_requires_portrait_change(monkeypatch):
    before, after = images(monkeypatch, None)
    assert deployment.deployment_evidence(before, after, 0, "knight", 5, 2)["confirmed"]
    assert not deployment.deployment_evidence(before, before, 0, "knight", 5, 2)["confirmed"]


def test_result_transition_or_unknown_replacement_is_not_confirmed(monkeypatch):
    before, after = images(monkeypatch, None)
    assert not deployment.deployment_evidence(before, after, 0, "knight", 5, 5)["confirmed"]
    assert not deployment.deployment_evidence(before, after, 0, "knight", 5, None)["confirmed"]


def test_consumed_slot_confirms_low_cost_play_before_replacement_arrives(monkeypatch):
    source = cv2.imread(str(Path(__file__).parent / "fixtures/cn_random_hand/consumed_slot_live.png"))
    assert source is not None and source.size > 0, "Cannot decode cn_random_hand/consumed_slot_live.png"
    assert deployment.slot_was_consumed(source, 1)
    assert all(not deployment.slot_was_consumed(source, slot) for slot in (0, 2, 3))
    before = source.copy()
    x1, y1, x2, y2 = CN_RANDOM_HAND_ROIS[1]
    before[y1:y2, x1:x2] = 150
    monkeypatch.setattr(deployment, "identify_random_hand", lambda _: [{"card": None}] * 4)
    evidence = deployment.deployment_evidence(before, source, 1, "heal_spirit", 7, 7)
    assert evidence["confirmed"] and evidence["method"] == "consumed_hand_slot"
    # The selected-card animation must not establish consumption before the drop.
    assert not deployment.deployment_evidence(before, source, 1, "heal_spirit", 7, 7, selected_was_empty=True)[
        "confirmed"
    ]
