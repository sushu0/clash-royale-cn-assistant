"""567 role hints: independent frames, provenance, and hostile-plaque gates."""

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from pyclashbot.detection.cn_battle_cues import read_cn_battle_cues
from pyclashbot.detection.cn_threats import read_cn_threats

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "cn_567_threats"
BANK = REPO / "pyclashbot" / "detection" / "reference_images" / "cn_567_threats"


def load_frame(path: Path) -> np.ndarray:
    frame = cv2.imread(str(path))
    assert frame is not None and frame.size > 0, f"Cannot decode threat fixture: {path}"
    return frame


def image(name):
    return load_frame(FIXTURES / name)


def role_hints(frame):
    return [r for r in read_cn_threats(frame, [], include_567=True) if r.get("origin") == "567_role"]


@pytest.mark.parametrize(
    "name,kind,heavy,point",
    [
        ("ground_drill_heldout.png", "ground", True, (103, 290)),
        ("baby_dragon_heldout.png", "air", False, (311, 294)),
    ],
)
def test_independent_frames_restore_explicit_role_and_hostile_anchor(name, kind, heavy, point):
    hints = role_hints(image(name))
    assert len(hints) == 1
    hint = hints[0]
    assert hint["kind"] == kind and hint["heavy"] is heavy
    assert (hint["x"], hint["y"]) == point
    assert hint["confidence"] >= hint["confidence_threshold"]
    assert hint["label_confidence"] >= 0.75
    assert hint["small"] is False
    assert hint["template_id"].startswith("567_")


def test_567_full_cues_chain_adds_previously_missed_anchor():
    frame = image("ground_drill_heldout.png")
    assert (103, 290) not in read_cn_battle_cues(frame)["enemies"]
    result = read_cn_battle_cues(frame, include_567=True)
    assert (103, 290) in result["enemies"]
    assert any(r.get("origin") == "567_role" and r.get("heavy") for r in result["threats"])


@pytest.mark.parametrize("name", ["ground_drill_source.png", "baby_dragon_source.png"])
def test_source_self_matches_are_not_counted_as_independent_validation(name):
    assert role_hints(image(name))[0]["confidence"] > 0.99


@pytest.mark.parametrize("name", ["ground_drill_heldout.png", "baby_dragon_heldout.png"])
def test_opt_in_preserves_old_hog_reader(name):
    frame = image(name)
    assert read_cn_threats(frame, []) == []
    assert not any(r.get("origin") == "567_role" for r in read_cn_battle_cues(frame)["threats"])


@pytest.mark.parametrize("name", ["ground_drill_heldout.png", "baby_dragon_heldout.png"])
def test_matching_sprite_with_blue_plaque_is_not_an_enemy(name):
    frame = image(name)
    hint = role_hints(frame)[0]
    x, y = hint["x"], hint["y"]
    tag = frame[y - 23 : y - 8, x - 7 : x + 8]
    hsv = cv2.cvtColor(tag, cv2.COLOR_BGR2HSV)
    red = ((hsv[:, :, 0] <= 9) | (hsv[:, :, 0] >= 166)) & (hsv[:, :, 1] >= 125) & (hsv[:, :, 2] >= 75)
    tag[red] = (220, 110, 15)
    assert not role_hints(frame)


@pytest.mark.parametrize("name", ["ground_drill_heldout.png", "baby_dragon_heldout.png"])
def test_red_without_white_or_gold_numeral_is_not_an_enemy(name):
    frame = image(name)
    hint = role_hints(frame)[0]
    x, y = hint["x"], hint["y"]
    tag = frame[y - 23 : y - 8, x - 7 : x + 8]
    hsv = cv2.cvtColor(tag, cv2.COLOR_BGR2HSV)
    numeral = ((hsv[:, :, 1] <= 90) & (hsv[:, :, 2] >= 190)) | (
        (hsv[:, :, 0] >= 16) & (hsv[:, :, 0] <= 38) & (hsv[:, :, 1] >= 90) & (hsv[:, :, 2] >= 180)
    )
    tag[numeral] = (25, 15, 125)
    assert not role_hints(frame)


def test_unrelated_units_friendly_units_and_non_battle_screens_abstain():
    folders = ["cn_threats", "cn_battle_cues", "cn_567", "cn_rewards", "cn_results"]
    checked = 0
    for folder in folders:
        for path in sorted((FIXTURES.parent / folder).glob("*.png")):
            assert not role_hints(load_frame(path)), path.name
            checked += 1
    assert checked >= 60


def test_manifest_and_saved_fixture_hashes_prove_independent_lineage():
    manifest = json.loads((BANK / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest) == 2
    for item in manifest:
        source = REPO / item["source"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == item["source_sha256"]
        assert item["source_trace"]["sha256"] == item["source_sha256"]
        assert hashlib.sha256((BANK / item["file"]).read_bytes()).hexdigest() == item["template_sha256"]
        x1, y1, x2, y2 = item["source_crop"]
        assert np.array_equal(load_frame(source)[y1:y2, x1:x2], load_frame(BANK / item["file"]))
        for heldout in item["independent_validation_sources"]:
            assert heldout["sha256"] != item["source_sha256"]
            assert hashlib.sha256((REPO / heldout["path"]).read_bytes()).hexdigest() == heldout["sha256"]
            assert heldout["trace_evidence"]["sha256"] == heldout["sha256"]
