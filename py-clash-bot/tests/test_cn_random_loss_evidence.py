"""Sampled decision frames must survive screenshot-ring reuse for loss review."""

import hashlib
from pathlib import Path

import numpy as np
import pytest

from pyclashbot.bot.cn_random_mastery_loop import RandomMasteryLoop, RecoveryExhausted


def runner_at(folder):
    runner = RandomMasteryLoop.__new__(RandomMasteryLoop)
    runner.work = folder
    runner.evidence_sequence = 0
    return runner


@pytest.mark.parametrize("name", ["decision", "play", "battle", "battle-start"])
def test_review_frames_keep_original_hash_after_more_than_48_other_saves(tmp_path, name):
    runner = runner_at(tmp_path)
    original = np.zeros((30, 30, 3), dtype=np.uint8)
    original[8:20, 8:20] = (32, 64, 128)
    proof = runner._save(name, original)
    for value in range(1, 55):
        runner._save(name, np.full_like(original, value))
    path = Path(proof["path"])
    assert path.parent.name == "evidence"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == proof["sha256"]


def test_repeated_review_frame_deduplicates_without_rewriting(tmp_path):
    runner = runner_at(tmp_path)
    frame = np.full((30, 30, 3), 50, dtype=np.uint8)
    first = runner._save("decision", frame)
    path = Path(first["path"])
    stamp = path.stat().st_mtime_ns
    assert runner._save("decision", frame) == first
    assert path.stat().st_mtime_ns == stamp


def test_tampered_review_frame_is_preserved_and_blocks_evidence_reuse(tmp_path):
    runner = runner_at(tmp_path)
    frame = np.full((30, 30, 3), 50, dtype=np.uint8)
    proof = runner._save("play", frame)
    path = Path(proof["path"])
    path.write_bytes(b"tampered")
    with pytest.raises(RecoveryExhausted):
        runner._save("play", frame)
    assert path.read_bytes() == b"tampered"
