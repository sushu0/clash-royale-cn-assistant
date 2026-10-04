"""Native recovery journal checks use a fake API and never mutate real HWNDs."""

import json
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import Mock

import psutil
import pytest

from pyclashbot.interface import cn_native_view as native
from pyclashbot.interface.cn_native_window_api import WindowSnapshot


class FakeWindowAPI:
    def __init__(self, executable, snapshot):
        self.executable = executable.resolve()
        self.saved = snapshot
        self.restores = []
        self.changes = []

    def is_window(self, hwnd, pid):
        return hwnd == self.saved.hwnd and pid == self.saved.pid

    def window_executable(self, _):
        return self.executable

    def find_window(self, _):
        return self.saved.hwnd

    def snapshot(self, _):
        return self.saved

    def restore(self, hwnd, saved):
        self.restores.append((hwnd, saved))

    def set_style(self, *arguments):
        self.changes.append(("style", arguments))

    def set_ex_style(self, *arguments):
        self.changes.append(("ex_style", arguments))

    def set_parent(self, *arguments):
        self.changes.append(("parent", arguments))

    def move_window(self, *arguments):
        self.changes.append(("move", arguments))


@pytest.fixture
def recovery(tmp_path, monkeypatch):
    executable = tmp_path / "MEmu.exe"
    snapshot = WindowSnapshot(
        300,
        20,
        0,
        0x80000000,
        0x40000,
        {
            "flags": 0,
            "showCmd": 1,
            "ptMinPosition": (0, 0),
            "ptMaxPosition": (0, 0),
            "rcNormalPosition": (10, 10, 470, 750),
        },
        (10, 10, 470, 750),
        (20, 30, 419, 633),
    )
    path = tmp_path / "native-recovery.json"
    row = {
        "schema": 1,
        "restored": False,
        "owner_pid": 10,
        "owner_created_at": 100.0,
        "window_created_at": 200.0,
        "executable": str(executable.resolve()),
        "snapshot": asdict(snapshot),
    }
    path.write_text(json.dumps(row), encoding="utf-8")

    def process(pid=None):
        if pid == 10:
            raise psutil.NoSuchProcess(10)
        return SimpleNamespace(create_time=lambda: 200.0 if pid == 20 else 500.0)

    monkeypatch.setattr(native.psutil, "Process", process)
    api = FakeWindowAPI(executable, snapshot)
    host = native.NativeWindowHost(api, executable, path)
    value = SimpleNamespace(
        path=path, row=row, api=api, host=host, executable=executable, snapshot=snapshot, hosts=[host]
    )
    yield value
    for candidate in value.hosts:
        release = getattr(candidate, "_release_ownership", None)
        if release is not None:
            release()


def _rewrite(recovery):
    recovery.path.write_text(json.dumps(recovery.row), encoding="utf-8")


def test_abandoned_verified_window_is_restored_before_new_embedding(recovery):
    recovery.host.attach(900, 419, 633)
    assert recovery.api.restores[0][0] == 300
    assert recovery.host.embedded
    new = json.loads(recovery.path.read_text())
    assert not new["restored"]
    assert new["snapshot"]["parent"] == 0


def test_live_matching_host_is_never_taken_over(recovery, monkeypatch):
    monkeypatch.setattr(native.psutil, "Process", lambda *_: SimpleNamespace(create_time=lambda: 100.0))
    with pytest.raises(RuntimeError, match=r"托管|控制台"):
        recovery.host.attach(900, 419, 633)
    assert recovery.api.restores == []
    assert recovery.api.changes == []


@pytest.mark.parametrize("marker", ["false", 1, None])
def test_nonboolean_restored_marker_cannot_bypass_active_host(recovery, monkeypatch, marker):
    recovery.row["restored"] = marker
    _rewrite(recovery)
    monkeypatch.setattr(native.psutil, "Process", lambda *_: SimpleNamespace(create_time=lambda: 100.0))
    with pytest.raises(RuntimeError):
        recovery.host.attach(900, 419, 633)
    assert recovery.api.restores == []
    assert recovery.api.changes == []


def test_attach_race_cannot_create_two_live_hosts_for_one_window(recovery, monkeypatch):
    recovery.path.unlink()
    second_api = FakeWindowAPI(recovery.executable, recovery.snapshot)
    second = native.NativeWindowHost(second_api, recovery.executable, recovery.path)
    recovery.hosts.append(second)
    errors = []

    def find(_):
        try:
            second.attach(901, 419, 633)
        except RuntimeError as error:
            errors.append(error)
        return recovery.snapshot.hwnd

    monkeypatch.setattr(recovery.api, "find_window", find)
    recovery.host.attach(900, 419, 633)
    assert errors
    assert recovery.host.embedded and not second.embedded
    assert second_api.changes == []


def test_reparenting_keeps_exclusive_native_ownership(recovery, monkeypatch):
    recovery.path.unlink()
    recovery.host.attach(900, 419, 633)
    second_api = FakeWindowAPI(recovery.executable, recovery.snapshot)
    second = native.NativeWindowHost(second_api, recovery.executable, recovery.path)
    recovery.hosts.append(second)
    blocked = []

    def find(_):
        try:
            second.attach(901, 419, 633)
        except RuntimeError as error:
            blocked.append(error)
        return recovery.snapshot.hwnd

    monkeypatch.setattr(recovery.api, "find_window", find)
    recovery.host.attach(902, 419, 633)
    assert blocked
    assert recovery.host.embedded and not second.embedded


def test_closed_window_resize_does_not_make_own_journal_block_reembedding(recovery, monkeypatch):
    recovery.path.unlink()
    recovery.host.attach(900, 419, 633)
    monkeypatch.setattr(recovery.api, "is_window", lambda *_: False)
    with pytest.raises(RuntimeError):
        recovery.host.resize(419, 633)
    recovery.api.saved = WindowSnapshot(
        400,
        21,
        0,
        recovery.snapshot.style,
        recovery.snapshot.ex_style,
        recovery.snapshot.placement,
        recovery.snapshot.rect,
        recovery.snapshot.content_rect,
    )
    monkeypatch.setattr(recovery.api, "is_window", lambda hwnd, pid: hwnd == 400 and pid == 21)
    recovery.host.attach(900, 419, 633)
    assert recovery.host.embedded
    assert recovery.host.snapshot_state is not None and recovery.host.snapshot_state.hwnd == 400


def test_reused_owner_pid_does_not_block_verified_abandoned_window(recovery, monkeypatch):
    monkeypatch.setattr(
        native.psutil, "Process", lambda pid=None: SimpleNamespace(create_time=lambda: 101.0 if pid == 10 else 200.0)
    )
    recovery.host._recover_abandoned_host()
    assert len(recovery.api.restores) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner_created_at", float("nan")),
        ("owner_created_at", float("inf")),
        ("owner_pid", True),
        ("owner_pid", -1),
        ("window_created_at", "invalid"),
    ],
)
def test_invalid_identity_never_restores_native_window(recovery, field, value):
    recovery.row[field] = value
    _rewrite(recovery)
    with pytest.raises(RuntimeError):
        recovery.host._recover_abandoned_host()
    assert recovery.api.restores == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("rect", [0, 0, 0, 0]),
        ("rect", [0, 0, 419]),
        ("rect", "bad"),
        ("content_rect", [0, 0, 0, 633]),
        ("content_rect", [0, 0, 419, -1]),
        ("placement", []),
        ("placement", {"showCmd": "bad"}),
    ],
)
def test_invalid_snapshot_geometry_never_reaches_restore(recovery, field, value):
    recovery.row["snapshot"][field] = value
    _rewrite(recovery)
    with pytest.raises(RuntimeError):
        recovery.host._recover_abandoned_host()
    assert recovery.api.restores == []


def test_other_installation_journal_is_not_applied(recovery):
    recovery.row["executable"] = str(recovery.executable.parent / "other/MEmu.exe")
    _rewrite(recovery)
    with pytest.raises(RuntimeError):
        recovery.host._recover_abandoned_host()
    assert recovery.api.restores == []


def test_reused_window_pid_does_not_receive_old_state(recovery, monkeypatch):
    def process(pid=None):
        if pid == 10:
            raise psutil.NoSuchProcess(10)
        return SimpleNamespace(create_time=lambda: 201.0)

    monkeypatch.setattr(native.psutil, "Process", process)
    with pytest.raises(RuntimeError, match="身份"):
        recovery.host._recover_abandoned_host()
    assert recovery.api.restores == []


def test_window_executable_must_still_match_this_installation(recovery):
    recovery.api.executable = recovery.executable.parent / "unrelated.exe"
    with pytest.raises(RuntimeError, match=r"模拟器|窗口"):
        recovery.host._recover_abandoned_host()
    assert recovery.api.restores == []


def test_restore_failure_preserves_pending_journal(recovery, monkeypatch):
    before = recovery.path.read_bytes()
    monkeypatch.setattr(recovery.api, "restore", Mock(side_effect=OSError("native restore failed")))
    with pytest.raises((OSError, RuntimeError)):
        recovery.host._recover_abandoned_host()
    assert recovery.path.read_bytes() == before


def test_corrupt_json_is_preserved_and_displayed_as_ui_error(recovery, monkeypatch):
    recovery.path.write_text("{invalid", encoding="utf-8")
    view = object.__new__(native.NativeEmulatorView)
    view._closed = False
    view.host = recovery.host
    view.native_surface = Mock()
    view.viewport = Mock()
    view.native_surface.winfo_id.return_value = 900
    view.viewport.winfo_width.return_value = 419
    view.viewport.winfo_height.return_value = 633
    monkeypatch.setattr(view, "_show_state", Mock())
    monkeypatch.setattr(view, "_resize", Mock())
    view.attach()
    assert view._state == "offline"
    assert view._error
    assert recovery.path.read_text() == "{invalid"
    assert recovery.api.restores == []


def test_poll_restore_failure_is_displayed_without_killing_tk_callback(monkeypatch):
    view = object.__new__(native.NativeEmulatorView)
    view._closed = False
    view._state = "embedded"
    view._error = None
    view.host = SimpleNamespace(
        snapshot_state=SimpleNamespace(hwnd=300, pid=20),
        embedded=True,
        api=SimpleNamespace(is_window=lambda *_: False),
        detach=Mock(side_effect=RuntimeError("recovery journal blocked")),
    )
    monkeypatch.setattr(view, "after", Mock(return_value=1))
    monkeypatch.setattr(view, "attach", Mock())
    monkeypatch.setattr(view, "_show_state", Mock())
    view._poll()
    assert "journal blocked" in (view._error or "")


def test_detach_rechecks_window_process_identity_before_restore(recovery, monkeypatch):
    recovery.path.unlink()
    recovery.host.attach(900, 419, 633)

    def reused(pid=None):
        return SimpleNamespace(create_time=lambda: 201.0 if pid == 20 else 500.0)

    monkeypatch.setattr(native.psutil, "Process", reused)
    try:
        recovery.host.detach()
    except RuntimeError:
        pass
    assert recovery.api.restores == []
