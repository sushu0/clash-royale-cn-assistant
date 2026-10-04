"""Selecting older incidents stays stable across refresh and opens its evidence."""

from pathlib import Path
from unittest.mock import Mock

from scripts import cn_bot_control as console


class HistoryTree:
    def __init__(self):
        self.rows = {}
        self.selected = ()

    def get_children(self):
        return tuple(self.rows)

    def delete(self, *items):
        for item in items:
            self.rows.pop(item, None)

    def insert(self, _parent, _position, *, iid, values):
        self.rows[iid] = values

    def selection(self):
        return self.selected

    def selection_set(self, iid):
        self.selected = (iid,)

    def see(self, _iid):
        pass


def make_record(root, name, stamp, reason, *, screenshot=True):
    folder = root / "error-reports" / name
    folder.mkdir(parents=True)
    report = folder / "report.md"
    report.write_text(reason, encoding="utf-8")
    png = folder / "game.png"
    if screenshot:
        png.write_bytes(b"test-evidence")
    return {
        "event_id": name,
        "created_at": stamp,
        "occurred_at": stamp,
        "reason": reason,
        "report_dir": str(folder),
        "report_md": str(report),
        "report_json": str(folder / "report.json"),
        "game_png": str(png) if screenshot else None,
        "screenshot_status": "captured" if screenshot else "failed",
    }


def history_window(tmp_path, monkeypatch, records):
    monkeypatch.setattr(console, "OUTPUTS", tmp_path)
    monkeypatch.setattr(console, "list_error_reports", lambda _: records)
    window = console.ControlWindow.__new__(console.ControlWindow)
    window._error_history_next_refresh = 0.0
    window._error_catalog_signature = None
    window._selected_error_report = None
    window._selected_report_path = None
    window._error_catalog = {}
    window._report_signature = None
    window.error_history_tree = HistoryTree()
    window.error_history_info = Mock()
    window.open_report_button = Mock()
    window.open_error_image_button = Mock()
    window.error_text = Mock()
    return window


def test_history_lists_both_incidents_and_selects_newest_initially(tmp_path, monkeypatch):
    older = make_record(tmp_path, "older", "2026-10-04T08:00:00+08:00", "morning incident")
    newer = make_record(tmp_path, "newer", "2026-10-04T11:44:00+08:00", "midday incident")
    window = history_window(tmp_path, monkeypatch, [newer, older])
    window._refresh_error_report(force=True)
    assert len(window.error_history_tree.rows) == 2
    assert window._selected_error_report == newer["report_dir"]
    assert window.error_text.insert.call_args.args[1] == "midday incident"


def test_new_incident_and_periodic_refresh_preserve_older_selection(tmp_path, monkeypatch):
    older = make_record(tmp_path, "older", "2026-10-04T08:00:00+08:00", "morning incident")
    newer = make_record(tmp_path, "newer", "2026-10-04T11:44:00+08:00", "midday incident")
    records = [newer, older]
    window = history_window(tmp_path, monkeypatch, records)
    window._refresh_error_report(force=True)
    window.error_history_tree.selection_set(older["report_dir"])
    window._select_error_report()
    assert window._selected_report_path == Path(older["report_md"])
    window.error_text.insert.reset_mock()
    newest = make_record(tmp_path, "newest", "2026-10-04T12:00:00+08:00", "third incident")
    records.insert(0, newest)
    window._refresh_error_report(force=True)
    assert len(window.error_history_tree.rows) == 3
    assert window._selected_error_report == older["report_dir"]
    window.error_text.insert.assert_not_called()  # Keep the reader's scroll position.


def test_open_actions_use_the_selected_old_report_and_screenshot(tmp_path, monkeypatch):
    older = make_record(tmp_path, "older", "2026-10-04T08:00:00+08:00", "morning incident")
    newer = make_record(tmp_path, "newer", "2026-10-04T11:44:00+08:00", "midday incident")
    window = history_window(tmp_path, monkeypatch, [newer, older])
    window._refresh_error_report(force=True)
    window.error_history_tree.selection_set(older["report_dir"])
    window._select_error_report()
    opened = []
    monkeypatch.setattr(console.os, "startfile", opened.append)
    window._open_error_report()
    window._open_error_image()
    assert opened == [Path(older["report_md"]), Path(older["game_png"])]


def test_screenshot_failure_keeps_history_and_report_available(tmp_path, monkeypatch):
    older = make_record(tmp_path, "older", "2026-10-04T08:00:00+08:00", "incident without screenshot", screenshot=False)
    window = history_window(tmp_path, monkeypatch, [older])
    window._refresh_error_report(force=True)
    assert len(window.error_history_tree.rows) == 1
    window.open_report_button.configure.assert_called_with(state="normal")
    window.open_error_image_button.configure.assert_called_with(state="disabled")


def test_reopened_window_rediscovers_previous_incidents(tmp_path, monkeypatch):
    records = [make_record(tmp_path, "previous", "2026-10-04T08:00:00+08:00", "old saved incident")]
    first = history_window(tmp_path, monkeypatch, records)
    first._refresh_error_report(force=True)
    second = history_window(tmp_path, monkeypatch, records)
    second._refresh_error_report(force=True)
    assert second.error_history_tree.rows == first.error_history_tree.rows
