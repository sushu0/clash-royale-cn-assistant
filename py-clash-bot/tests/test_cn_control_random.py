# ruff: noqa: RUF001
# Native Chinese punctuation and multiplication glyphs are intentional UI/OCR text.
"""The control console uses random-mode state and keeps reward results distinct."""

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

path = Path(__file__).resolve().parents[1] / "scripts" / "cn_bot_control.py"
spec = importlib.util.spec_from_file_location("cn_control_random_tests", path)
assert spec is not None and spec.loader is not None
console = importlib.util.module_from_spec(spec)
spec.loader.exec_module(console)


def test_random_scope_and_policy_are_named_for_the_current_mode():
    assert console.SCOPES["随机卡组"] == "random"
    assert "领取全部" in console.policy_text("random-mastery-claim-all-v6-20260930")


def test_no_claim_button_is_not_presented_as_success():
    events = [{"event": "mastery_footer_checked", "footer_state": "none"}, {"event": "play", "confirmed": True}]
    assert console.random_reward_text(events) == "没有领取全部按钮，无可领奖励"


def test_only_confirmed_claims_are_presented_as_collected():
    events = [{"event": "mastery_footer_checked", "footer_state": "claim_all"}]
    assert console.random_reward_text(events) == "发现领取全部按钮"
    events.append({"event": "claim_all_unverified"})
    assert "待确认" in console.random_reward_text(events)
    events.append({"event": "claim_all_confirmed"})
    assert console.random_reward_text(events) == "领取全部已确认"


def _result_window(tmp_path, monkeypatch, expected_hash):
    monkeypatch.setattr(console, "WORK", tmp_path)
    source = tmp_path / "result.png"
    data = (Path(__file__).with_name("fixtures") / "cn_random_mastery/mastery_list.png").read_bytes()
    source.write_bytes(data)
    manifest = tmp_path / "random-mastery" / "sample" / "battle-0001.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"evidence": {"path": str(source), "sha256": expected_hash or hashlib.sha256(data).hexdigest()}}),
        encoding="utf-8",
    )
    messages, opened = [], []
    monkeypatch.setattr(console.os, "startfile", opened.append)
    window = console.ControlWindow.__new__(console.ControlWindow)
    window.history_tree = SimpleNamespace(selection=lambda: ["row"])
    window.history_records = {"row": {"strategy": "random", "session": "sample", "battle": 1, "evidence": str(source)}}
    window.notice = SimpleNamespace(set=messages.append)
    return window, messages, opened


def test_overwritten_result_image_is_not_opened(tmp_path, monkeypatch):
    window, messages, opened = _result_window(tmp_path, monkeypatch, "0" * 64)
    window._open_result()
    assert not opened
    assert "无法确认匹配" in messages[-1]


def test_verified_result_is_preserved_before_opening(tmp_path, monkeypatch):
    window, messages, opened = _result_window(tmp_path, monkeypatch, None)
    window._open_result()
    assert not messages
    assert len(opened) == 1
    assert opened[0].parent.name == "random-result-evidence"
    assert opened[0].read_bytes() == (tmp_path / "result.png").read_bytes()


def test_start_keeps_the_logged_in_game_process_and_selects_random(tmp_path, monkeypatch):
    for name in ("PYTHON", "ADB", "MEMUC", "WATCHDOG"):
        path = tmp_path / name
        path.touch()
        monkeypatch.setattr(console, name, path)
    states = iter(["stopped", "running"])
    monkeypatch.setattr(console, "bot_state", lambda: next(states))
    monkeypatch.setattr(console, "selected_strategy", lambda: "random")
    calls, launches = [], []

    def fake_run(command, timeout=20):
        calls.append(command)
        output = (
            "running"
            if "isvmrunning" in command
            else "device"
            if "get-state" in command
            else ("1" if "getprop" in command else "package:" + console.PACKAGE if "packages" in command else "")
        )
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    monkeypatch.setattr(console, "_run", fake_run)
    monkeypatch.setattr(console.subprocess, "Popen", lambda command, **kwargs: launches.append(command))
    assert "已启动" in console.ControlWindow._start_worker()
    assert all("force-stop" not in command for command in calls)
    assert any("monkey" in command for command in calls)
    assert launches[0][launches[0].index("--strategy") + 1] == "random"
