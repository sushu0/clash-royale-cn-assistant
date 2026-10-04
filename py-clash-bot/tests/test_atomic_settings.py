"""Settings preserve old keys and recover the last valid snapshot on write faults."""

import json
from pathlib import Path

import pytest

from pyclashbot.bot.cn_random_mastery_loop import RandomMasteryLoop
from pyclashbot.utils import caching, persistence
from pyclashbot.utils.caching import FileCache
from pyclashbot.utils.persistence import atomic_write_json, read_validated_json


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setattr(caching, "top_level", str(tmp_path))
    return FileCache("settings.json"), tmp_path / "settings.json"


def test_partial_settings_updates_merge_and_remain_json(settings):
    cache, path = settings
    cache.cache_data({"backend": "adb", "count": 5})
    cache.cache_data({"count": 6, "language": "zh"})
    assert cache.load_data() == {"backend": "adb", "count": 6, "language": "zh"}
    assert json.loads(path.read_text(encoding="utf-8")) == cache.load_data()
    assert path.with_suffix(".json.bak").exists()


def test_corrupt_primary_recovers_valid_settings_backup(settings):
    cache, path = settings
    cache.cache_data({"old": 1})
    cache.cache_data({"new": 2})
    path.write_text('{"damaged":', encoding="utf-8")
    assert cache.load_data() == {"old": 1}
    cache.cache_data({"recovered": True})
    assert cache.load_data() == {"old": 1, "recovered": True}
    assert json.loads(path.with_suffix(".json.bak").read_text(encoding="utf-8")) == {"old": 1}


def test_missing_primary_recovers_backup(settings):
    cache, path = settings
    atomic_write_json(path.with_suffix(".json.bak"), {"known": 7})
    assert cache.load_data() == {"known": 7}


def test_schema_invalid_primary_does_not_replace_valid_settings_backup(settings):
    cache, path = settings
    atomic_write_json(path.with_suffix(".json.bak"), {"known": 7})
    atomic_write_json(path, ["schema-invalid"])
    cache.cache_data({"restored": 8})
    assert cache.load_data() == {"known": 7, "restored": 8}
    assert json.loads(path.with_suffix(".json.bak").read_text(encoding="utf-8")) == {"known": 7}


def test_atomic_replace_failure_keeps_previous_complete_primary_and_no_temporary_files(settings, monkeypatch):
    cache, path = settings
    cache.cache_data({"old": 1})
    replace = Path.replace

    def locked(source, target):
        if Path(target) == path:
            raise PermissionError("synthetic locked snapshot")
        return replace(source, target)

    monkeypatch.setattr(Path, "replace", locked)
    monkeypatch.setattr(persistence.time, "sleep", lambda _: None)
    with pytest.raises(PermissionError):
        cache.cache_data({"new": 2})
    assert json.loads(path.read_text(encoding="utf-8")) == {"old": 1}
    assert not list(path.parent.glob("*.tmp"))
    assert cache.load_data() == {"old": 1}


def test_nonserializable_update_keeps_existing_settings(settings):
    cache, path = settings
    cache.cache_data({"old": 1})
    before = path.read_bytes()
    with pytest.raises(TypeError):
        cache.cache_data({"bad": object()})
    assert path.read_bytes() == before
    assert cache.load_data() == {"old": 1}


@pytest.mark.parametrize("bad", [None, [], "bad", True])
def test_invalid_update_shape_is_rejected_without_damage(settings, bad):
    cache, path = settings
    cache.cache_data({"old": 1})
    before = path.read_bytes()
    with pytest.raises(TypeError):
        cache.cache_data(bad)
    assert path.read_bytes() == before


def test_checkpoint_uses_valid_backup_when_primary_truncated(tmp_path):
    path = tmp_path / "checkpoint.json"
    earlier = {"schema": 1, "completed": 4, "generated": 5, "pending_battle": True}
    atomic_write_json(path, earlier)
    atomic_write_json(path, {**earlier, "completed": 5, "pending_battle": False}, backup=True)
    path.write_bytes(b'{"completed":')
    assert read_validated_json(path, RandomMasteryLoop._valid_checkpoint) == earlier
    assert path.read_bytes() == b'{"completed":'


def test_no_valid_checkpoint_raises_instead_of_defaulting_to_empty(tmp_path):
    path = tmp_path / "checkpoint.json"
    path.write_text('{"completed": "five"}', encoding="utf-8")
    with pytest.raises(ValueError, match="No valid"):
        read_validated_json(path, RandomMasteryLoop._valid_checkpoint, default={})


@pytest.mark.parametrize(
    "bad", [{"schema": True}, {"completed": True}, {"reward_receipts": None}, {"pending_battle": "yes"}]
)
def test_checkpoint_validator_rejects_wrong_field_types(bad):
    assert not RandomMasteryLoop._valid_checkpoint({"schema": 1, **bad})
