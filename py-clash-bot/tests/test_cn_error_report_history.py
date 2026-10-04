"""History survives latest-index loss and never follows linked report resources."""

import io
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from pyclashbot.utils import cn_error_report as reports


def write_report(
    root,
    folder_name,
    *,
    event_id,
    created_at,
    occurred_at=None,
    screenshot_status="captured",
    markdown=True,
    image=True,
):
    folder = root / folder_name
    folder.mkdir(parents=True)
    report = {
        "schema": 1,
        "event_id": event_id,
        "created_at": created_at,
        "reason": f"pause {event_id}",
        "runtime": {"session": f"session-{event_id}", "strategy": "random", "phase": "paused"},
        "snapshots": {"pid_state": {"phase": "paused"}, "live_state": {}},
        "screenshot": {"status": screenshot_status},
    }
    if occurred_at:
        report["snapshots"]["pid_state"]["ended_at"] = occurred_at
    (folder / "report.json").write_text(json.dumps(report), encoding="utf-8")
    if markdown:
        (folder / "report.md").write_text(f"# pause {event_id}\n", encoding="utf-8")
    if image:
        encoded = io.BytesIO()
        Image.new("RGB", (4, 6)).save(encoded, format="PNG")
        (folder / "game.png").write_bytes(encoded.getvalue())
    return folder


@pytest.mark.parametrize("latest_state", ["missing", "corrupt", "stale"])
def test_independent_pause_history_survives_latest_index_loss_and_restart(tmp_path, latest_state):
    root = tmp_path / "outputs" / "error-reports"
    older = write_report(root, "z-old-folder", event_id="pause-1", created_at="2026-10-04T08:00:06+08:00")
    newer = write_report(root, "a-new-folder", event_id="pause-2", created_at="2026-10-04T11:44:18+08:00")
    latest = root / "latest-error-report.json"
    if latest_state == "corrupt":
        latest.write_text("{broken latest", encoding="utf-8")
    elif latest_state == "stale":
        latest.write_text(json.dumps({"event_id": "pause-1", "report_dir": str(older)}), encoding="utf-8")
    before = {str(path): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    first = reports.list_error_reports(root)
    restarted_read = reports.list_error_reports(root)
    assert [row["event_id"] for row in first] == ["pause-2", "pause-1"]
    assert first == restarted_read
    assert first[0]["report_dir"] == str(newer)
    assert first[1]["report_dir"] == str(older)
    assert first[0]["session"] == "session-pause-2"
    assert first[0]["runtime"]["phase"] == "paused"
    assert all(not row["pending"] and not row["incomplete"] for row in first)
    assert before == {str(path): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_history_sorts_by_event_occurrence_instead_of_folder_name_or_delayed_capture(tmp_path):
    root = tmp_path / "error-reports"
    write_report(
        root,
        "zz-delayed-old",
        event_id="old",
        created_at="2026-10-04T12:00:00+08:00",
        occurred_at="2026-10-04 08:00:00",
    )
    write_report(
        root, "aa-new", event_id="new", created_at="2026-10-04T11:44:18+08:00", occurred_at="2026-10-04 11:44:18"
    )
    rows = reports.list_error_reports(root)
    assert [row["event_id"] for row in rows] == ["new", "old"]
    assert rows[0]["occurred_at"] == "2026-10-04 11:44:18"
    assert rows[1]["created_at"] == "2026-10-04T12:00:00+08:00"


def test_history_timezone_sort_compares_actual_instants(tmp_path):
    root = tmp_path / "error-reports"
    write_report(root, "local", event_id="local", created_at="2026-10-04T08:00:00+08:00")
    write_report(root, "utc", event_id="utc", created_at="2026-10-04T01:00:00+00:00")
    assert [row["event_id"] for row in reports.list_error_reports(root)] == ["utc", "local"]


def test_corrupt_report_cannot_hide_good_history_and_pending_reports_are_marked(tmp_path):
    root = tmp_path / "error-reports"
    write_report(root, "complete", event_id="good", created_at="2026-10-04T08:00:06+08:00")
    write_report(
        root,
        "pending",
        event_id="waiting",
        created_at="2026-10-04T11:44:18+08:00",
        screenshot_status="pending",
        markdown=False,
        image=False,
    )
    broken = root / "broken"
    broken.mkdir()
    (broken / "report.json").write_text("{partial JSON", encoding="utf-8")
    invalid = root / "invalid-type"
    invalid.mkdir()
    (invalid / "report.json").write_text("[]", encoding="utf-8")
    rows = reports.list_error_reports(root)
    assert [row["event_id"] for row in rows] == ["waiting", "good"]
    assert rows[0]["pending"] and rows[0]["incomplete"]
    assert rows[0]["report_md"] is None and rows[0]["game_png"] is None
    assert Path(rows[0]["report_json"]).is_file()


def test_screenshot_failure_is_complete_but_missing_captured_file_is_incomplete(tmp_path):
    root = tmp_path / "error-reports"
    write_report(
        root,
        "failed-image",
        event_id="failed",
        created_at="2026-10-04T11:44:18+08:00",
        screenshot_status="failed",
        image=False,
    )
    write_report(root, "missing-image", event_id="missing", created_at="2026-10-04T08:00:06+08:00", image=False)
    rows = reports.list_error_reports(root)
    assert rows[0]["screenshot_status"] == "failed"
    assert not rows[0]["incomplete"] and rows[0]["game_png"] is None
    assert rows[1]["screenshot_status"] == "captured"
    assert rows[1]["incomplete"] and rows[1]["game_png"] is None


def test_complete_report_larger_than_state_limit_remains_in_history(tmp_path):
    root = tmp_path / "error-reports"
    folder = write_report(root, "large", event_id="large", created_at="2026-10-04T11:44:18+08:00")
    data = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    data["logs"] = [{"lines": ["bot log tail " + "x" * (reports.MAX_STATE_BYTES + 1024)]}]
    (folder / "report.json").write_text(json.dumps(data), encoding="utf-8")
    assert (folder / "report.json").stat().st_size > reports.MAX_STATE_BYTES
    rows = reports.list_error_reports(root)
    assert len(rows) == 1 and rows[0]["event_id"] == "large" and not rows[0]["incomplete"]


def test_metadata_resource_paths_cannot_redirect_history_buttons_outside_report(tmp_path):
    root = tmp_path / "error-reports"
    folder = write_report(root, "safe", event_id="safe", created_at="2026-10-04T11:44:18+08:00")
    external = tmp_path / "unrelated.txt"
    external.write_text("unrelated user data", encoding="utf-8")
    data = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    data.update(report_dir=str(tmp_path), report_md=str(external), report_json=str(external), game_png=str(external))
    data["screenshot"]["path"] = str(external)
    (folder / "report.json").write_text(json.dumps(data), encoding="utf-8")
    row = reports.list_error_reports(root)[0]
    for key, filename in (("report_md", "report.md"), ("report_json", "report.json"), ("game_png", "game.png")):
        assert row[key] == str(folder / filename)
    assert row["report_dir"] == str(folder)


def create_directory_link(link, target):
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, check=False)
        if result.returncode:
            pytest.skip("Directory symlink/junction creation is unavailable")


def test_catalog_never_enters_directory_junction_or_symlink(tmp_path):
    root = tmp_path / "error-reports"
    safe = write_report(root, "safe", event_id="safe", created_at="2026-10-04T08:00:06+08:00")
    external = write_report(
        tmp_path / "external", "outside", event_id="outside", created_at="2026-10-04T11:44:18+08:00"
    )
    create_directory_link(root / "linked-report", external)
    create_directory_link(tmp_path / "linked-root", root)
    rows = reports.list_error_reports(root)
    assert [row["event_id"] for row in rows] == ["safe"]
    assert rows[0]["report_dir"] == str(safe)
    assert reports.list_error_reports(tmp_path / "linked-root") == []


def test_catalog_rejects_linked_json_and_marks_linked_optional_resources_unavailable(tmp_path):
    root = tmp_path / "error-reports"
    json_folder = root / "linked-json"
    json_folder.mkdir(parents=True)
    resource_folder = write_report(
        root,
        "linked-resources",
        event_id="resources",
        created_at="2026-10-04T08:00:06+08:00",
        markdown=False,
        image=False,
    )
    external = write_report(
        tmp_path / "external", "outside", event_id="outside", created_at="2026-10-04T11:44:18+08:00"
    )
    try:
        (json_folder / "report.json").symlink_to(external / "report.json")
        (resource_folder / "report.md").symlink_to(external / "report.md")
        (resource_folder / "game.png").symlink_to(external / "game.png")
    except OSError:
        pytest.skip("File symlink creation requires Windows developer mode or privilege")
    rows = reports.list_error_reports(root)
    assert [row["event_id"] for row in rows] == ["resources"]
    assert rows[0]["report_md"] is None and rows[0]["game_png"] is None and rows[0]["incomplete"]


@pytest.mark.parametrize("resource", ["report.json", "report.md", "game.png"])
def test_windows_reparse_resources_are_rejected_without_symlink_privilege(tmp_path, monkeypatch, resource):
    root = tmp_path / "error-reports"
    flagged = write_report(root, "flagged", event_id="flagged", created_at="2026-10-04T11:44:18+08:00")
    write_report(root, "safe", event_id="safe", created_at="2026-10-04T08:00:06+08:00")
    original_lstat = Path.lstat

    def reparse_lstat(path):
        metadata = original_lstat(path)
        if path == flagged / resource:
            return SimpleNamespace(
                st_mode=metadata.st_mode,
                st_file_attributes=1024,
                st_dev=metadata.st_dev,
                st_ino=metadata.st_ino,
            )
        return metadata

    monkeypatch.setattr(Path, "lstat", reparse_lstat)
    rows = reports.list_error_reports(root)
    if resource == "report.json":
        assert [row["event_id"] for row in rows] == ["safe"]
    else:
        assert [row["event_id"] for row in rows] == ["flagged", "safe"]
        key = "report_md" if resource == "report.md" else "game_png"
        assert rows[0][key] is None and rows[0]["incomplete"]


def test_missing_history_root_returns_empty_without_creating_files(tmp_path):
    missing = tmp_path / "outputs" / "error-reports"
    assert reports.list_error_reports(missing) == []
    assert not missing.exists()
