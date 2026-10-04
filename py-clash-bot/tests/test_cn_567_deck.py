"""Real CN deck previews, plus controlled reorder/missing-card regressions."""

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from pyclashbot.bot.coords import CN_567_DECK_ROIS
from pyclashbot.detection.cn_567_deck import EXPECTED_CARDS, read_567_deck

FOLDER = Path(__file__).resolve().parents[1] / "pyclashbot/detection/reference_images/cn_567"
OLD = ("pekka", "goblin_giant", "goblin_machine", "baby_dragon", "mega_minion", "bomber", "zap", "arrows")
NEW = ("pekka", "goblin_giant", "bomber", "baby_dragon", "mega_minion", "goblin_machine", "zap", "arrows")


def image(filename):
    frame = cv2.imread(str(FOLDER / filename))
    assert frame is not None and frame.size > 0, f"Cannot decode deck fixture: {FOLDER / filename}"
    return frame


def crop(frame, slot):
    x1, y1, x2, y2 = CN_567_DECK_ROIS[slot]
    return frame[y1:y2, x1:x2]


@pytest.mark.parametrize(
    ("filename", "expected", "bomber_variant"),
    [
        ("verified_deck.png", OLD, "bomber"),
        ("verified_deck_evo.png", NEW, "evo_bomber"),
    ],
)
def test_real_decks_keep_base_identities_and_observed_variant(filename, expected, bomber_variant):
    result = read_567_deck(image(filename))
    assert result["valid"], result
    assert tuple(item["card"] for item in result["matches"]) == expected
    bomber = next(item for item in result["matches"] if item["card"] == "bomber")
    assert bomber["variant"] == bomber["matched_variant"] == bomber_variant
    assert all(item["score"] >= 0.90 for item in result["matches"])
    assert next(item for item in result["matches"] if item["card"] == "goblin_machine")["variant"] == "goblin_machine"
    assert "goblinstein" not in {item["card"] for item in result["matches"]}


@pytest.mark.parametrize("filename", ["verified_deck.png", "verified_deck_evo.png"])
@pytest.mark.parametrize("shift", range(1, 8))
def test_every_card_can_move_to_every_slot(filename, shift):
    original = image(filename)
    moved = original.copy()
    before = read_567_deck(original)
    for slot in range(8):
        crop(moved, slot)[:] = crop(original, (slot + shift) % 8)
    after = read_567_deck(moved)
    assert after["valid"], after
    assert [(m["card"], m["variant"]) for m in after["matches"]] == [
        (before["matches"][(slot + shift) % 8]["card"], before["matches"][(slot + shift) % 8]["variant"])
        for slot in range(8)
    ]


@pytest.mark.parametrize("slot", range(8))
def test_duplicate_replaces_required_card_and_rejects_deck(slot):
    frame = image("verified_deck_evo.png")
    crop(frame, slot)[:] = crop(frame, (slot + 1) % 8)
    result = read_567_deck(frame)
    assert not result["valid"]
    assert result["reason"] == "duplicate_or_missing_cards"


@pytest.mark.parametrize("slot", range(8))
def test_missing_or_unknown_card_is_never_forced_into_expected_identity(slot):
    frame = image("verified_deck_evo.png")
    crop(frame, slot)[:] = 0
    result = read_567_deck(frame)
    assert not result["valid"]
    assert result["matches"][slot]["card"] is None
    assert result["reason"] == "unrecognized_or_ambiguous_slots"


def test_two_bomber_variants_do_not_count_as_two_distinct_cards():
    frame = image("verified_deck_evo.png")
    crop(frame, 5)[:] = crop(image("verified_deck.png"), 5)
    result = read_567_deck(frame)
    assert not result["valid"] and result["reason"] == "duplicate_or_missing_cards"
    assert result["matches"][2]["variant"] == "evo_bomber"
    assert result["matches"][5]["variant"] == "bomber"


def test_actual_old_hog_deck_is_rejected():
    path = Path(__file__).parent / "fixtures/cn_567/wrong_hog_deck.png"
    frame = cv2.imread(str(path))
    assert frame is not None and frame.size > 0, f"Cannot decode deck fixture: {path}"
    result = read_567_deck(frame)
    assert not result["valid"]
    assert all(item["card"] is None for item in result["matches"])


@pytest.mark.parametrize("foreign_slot", range(8))
def test_real_foreign_art_cannot_fill_the_missing_machine_slot(foreign_slot):
    path = Path(__file__).parent / "fixtures/cn_567/wrong_hog_deck.png"
    wrong_deck = cv2.imread(str(path))
    assert wrong_deck is not None and wrong_deck.size > 0, f"Cannot decode deck fixture: {path}"
    frame = image("verified_deck_evo.png")
    crop(frame, 5)[:] = crop(wrong_deck, foreign_slot)
    result = read_567_deck(frame)
    assert not result["valid"]
    assert result["matches"][5]["card"] is None


def test_manifest_is_bound_to_reviewed_images_and_never_aliases_goblinstein():
    manifest = json.loads((FOLDER / "deck_manifest.json").read_text(encoding="utf-8"))
    for source in manifest["references"]:
        assert hashlib.sha256((FOLDER / source["file"]).read_bytes()).hexdigest() == source["sha256"]
        assert {item["card"] for item in source["cards"]} == EXPECTED_CARDS
        assert all(
            item["variant"] == item["card"] or (item["card"], item["variant"]) == ("bomber", "evo_bomber")
            for item in source["cards"]
        )


@pytest.mark.parametrize(
    "frame", [None, np.zeros((10, 10, 3), dtype=np.uint8), np.zeros((633, 419, 3), dtype=np.float32)]
)
def test_invalid_frame_rejects_without_a_match(frame):
    assert read_567_deck(frame) == {"valid": False, "matches": [], "reason": "invalid_frame"}


def test_unavailable_reference_bank_rejects():
    with patch("pyclashbot.detection.cn_567_deck._references", return_value=()):
        assert read_567_deck(image("verified_deck_evo.png"))["reason"] == "reference_data_invalid"
