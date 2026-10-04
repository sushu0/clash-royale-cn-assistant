"""Actual CN normal/evolution hands; deployment is not a damage-effect test."""

import hashlib
import json
from pathlib import Path

import cv2
import pytest

from pyclashbot.bot.card_detection import identify_567_hand_frame
from pyclashbot.bot.double_air_567_strategy import COSTS

FOLDER = Path(__file__).parent / "fixtures/cn_evo_bomber"


@pytest.mark.parametrize(
    ("filename", "slot", "variant", "evolution_ready"),
    [
        ("normal_hand.png", 2, "bomber", False),
        ("evolution_hand.png", 0, "evo_bomber", True),
    ],
)
def test_real_bomber_forms_share_base_identity_and_two_elixir_cost(filename, slot, variant, evolution_ready):
    frame = cv2.imread(str(FOLDER / filename))
    assert frame is not None and frame.shape == (633, 419, 3)
    hand = identify_567_hand_frame(frame)
    bomber = hand[slot]
    assert bomber["card"] == "bomber"
    assert bomber["variant"] == variant
    assert bomber["available"] is True
    assert bomber["variant_confident"] is True
    assert bomber["evolution_ready"] is evolution_ready
    assert COSTS[bomber["card"]] == 2
    for other in hand:
        if other["slot"] != slot:
            assert other["card"] != "bomber"
            assert not other.get("evolution_ready", False)


def test_portable_images_match_logged_events_and_preserve_variant_evidence():
    manifest = json.loads((FOLDER / "sources.json").read_text(encoding="utf-8"))
    assert {sample["file"] for sample in manifest["samples"]} == {
        "normal_hand.png",
        "evolution_hand.png",
    }
    for sample in manifest["samples"]:
        event = sample["original_event"]
        evidence = event[sample["evidence_key"]]
        digest = hashlib.sha256((FOLDER / sample["file"]).read_bytes()).hexdigest()
        assert digest == sample["sha256"] == evidence["sha256"]
        assert event["session"] == "20260928-153455"
        assert event["mode"] == "classic_1v1"
        assert event["battle"] == 1
        logged_bomber = event["hand"][sample["bomber_slot"]]
        frame = cv2.imread(str(FOLDER / sample["file"]))
        assert frame is not None and frame.size > 0, f"Cannot decode evolution fixture: {sample['file']}"
        actual = identify_567_hand_frame(frame)
        observed_bomber = actual[sample["bomber_slot"]]
        for key in ("slot", "card", "variant", "evolution_ready", "variant_confident"):
            assert observed_bomber[key] == logged_bomber[key]
        if sample["file"] == "evolution_hand.png":
            assert sample["evidence_key"] == "evidence_before"
            assert event["time"] == "2026-09-28 15:37:31"
            assert event["decision"]["card"] == "bomber"
            assert event["decision"]["variant"] == "evo_bomber"
        else:
            assert event["time"] == "2026-09-28 15:35:16"
