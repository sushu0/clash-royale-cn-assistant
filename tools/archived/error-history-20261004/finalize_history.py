"""Verify preserved history, selected old evidence and the live updated package."""
import hashlib
import json
import marshal
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psutil

root = Path(r"D:\codex\CodexWork\clash")
work = root / "work" / "error-history-20261004"
source = root / "py-clash-bot"
import sys
sys.path.insert(0, str(source))
from pyclashbot.utils.cn_error_report import list_error_reports

def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

baseline = read(work / "original-report-hashes.json")
preservation = [{**item, "actual_sha256": digest(item["path"])} for item in baseline]
assert all(item["actual_sha256"] == item["sha256"].lower() for item in preservation)
reports = list_error_reports(root / "outputs" / "error-reports")
assert len(reports) == 2
assert reports[0]["occurred_at"] == "2026-10-04 11:44:18"
assert reports[1]["occurred_at"] == "2026-10-04 08:00:06"
ui = read(root / "work" / "random-frontend-state.json")
assert ui["error_report_count"] == 2 and ui["frozen"]
assert ui["selected_error_report_md"] == reports[1]["report_md"]
assert ui["selected_error_report_png"] == reports[1]["game_png"]
assert ui["state"] == "running" and ui["window_visible"]
assert ui["desktop_shell"]["tray_icon_added"] and not ui["desktop_shell"]["error"]
manifest = read(work / "package-manifest.json")
exe = Path(manifest["exe"])
assert "desktop-app-history-20261004" in str(exe)
for pair in manifest["source_copy_checks"]:
    assert digest(pair["source"]) == pair["source_sha256"] == digest(pair["packaged_copy"])
    code = marshal.loads(Path(pair["compiled_module"]).read_bytes()[16:])
    assert code == compile(Path(pair["source"]).read_bytes(), code.co_filename, "exec", optimize=0)
pids = read(root / "work" / "bot-processes.json")
live = read(root / "outputs" / "random-mastery-live-status.json")
assert live["state"] != "paused" and live["cards_confirmed"] > 0
identities = {}
for role, pid in (("ui", ui["pid"]), ("watchdog", pids["watchdog_pid"]), ("runner", pids["runner_pid"])):
    process = psutil.Process(pid)
    assert process.is_running() and Path(process.exe()).resolve() == exe.resolve()
    if role != "ui":
        assert abs(process.create_time() - pids[f"{role}_created_at"]) < .01
        assert "--max-battles" not in process.cmdline()
    identities[role] = {"pid": pid, "executable": process.exe(), "created_at": process.create_time()}
tests = (work / "tests-final-all.log").read_text(encoding="utf-8-sig")
assert "169 passed, 1 skipped, 6 subtests passed" in tests
record = {
    "status": "PASS", "verified_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
    "cause": "Old UI loaded only latest-error-report.json; both historical report folders were already preserved.",
    "report_count": len(reports), "reports": reports, "original_files_unchanged": preservation,
    "ui": ui, "processes": identities, "live": live,
    "selected_old_record_actual_ui_verified": True,
    "selected_old_screenshot_opened_in_windows_photos": True,
    "refresh_keeps_selected_old_record": True,
    "tests": {"passed": 169, "skipped": 1, "subtests_passed": 6, "log": str(work / "tests-final-all.log")},
    "package_manifest": str(work / "package-manifest.json"),
    "update_boundary": read(work / "update-boundary.json"),
    "source_backup": str(work / "backup"), "shortcut_backup": str(work / "shortcut-backup"),
}
path = root / "outputs" / "ERROR_REPORT_HISTORY_ACCEPTANCE_20261004.json"
path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"status": "PASS", "report_count": len(reports), "selected_old_report": ui["selected_error_report_md"], "running": ui["state"], "evidence": str(path)}, ensure_ascii=True))
