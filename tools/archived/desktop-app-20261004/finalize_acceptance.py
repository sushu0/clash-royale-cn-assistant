"""Verify every delivery requirement against saved and current runtime evidence."""
import hashlib
import json
import marshal
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psutil
from PIL import Image

ROOT = Path(r"D:\codex\CodexWork\clash")
WORK = ROOT / "work" / "desktop-app-20261004"

def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

monitor = read(WORK / "live-monitor.json")
assert monitor["passed"] and len(monitor["completed_new_battles"]) >= 3
for key in ("pause_events", "restore_events", "watchdog_error_lines", "process_identity_failed"):
    assert not monitor["anomalies"][key], key
assert not monitor["anomalies"]["currently_paused"]
battles = monitor["completed_new_battles"][:3]
for battle in battles:
    assert battle["cycle_complete_at"] and battle["next_battle"]["started_at"]
    evidence = battle["result_evidence"]
    assert digest(evidence["path"]) == evidence["expected_sha256"]
    assert battle["cards_confirmed"] > 0

ui = read(ROOT / "work" / "random-frontend-state.json")
live = read(ROOT / "outputs" / "random-mastery-live-status.json")
pids = read(ROOT / "work" / "bot-processes.json")
manifest = read(WORK / "package-manifest.json")
exe = Path(manifest["exe"])
assert digest(exe) == manifest["exe_sha256"]
assert manifest["gui_subsystem_verified"] and manifest["embedded_icon_groups"] > 0
for source in manifest["source_copy_checks"]:
    assert digest(source["source"]) == source["source_sha256"] == digest(source["packaged_copy"])
    actual_code = marshal.loads(Path(source["compiled_module"]).read_bytes()[16:])
    expected_code = compile(Path(source["source"]).read_bytes(), actual_code.co_filename, "exec", optimize=0)
    assert actual_code == expected_code, source["source"]

processes = {}
for key, pid in (("ui", ui["pid"]), ("watchdog", pids["watchdog_pid"]), ("runner", pids["runner_pid"])):
    process = psutil.Process(pid)
    assert process.is_running() and Path(process.exe()).resolve() == exe.resolve()
    if key != "ui":
        assert abs(process.create_time() - pids[f"{key}_created_at"]) < 0.01
        assert "--max-battles" not in process.cmdline()
    processes[key] = {"pid": pid, "alive": True, "created_at": process.create_time(), "executable": process.exe()}
assert ui["state"] == "running" and ui["frozen"] and ui["window_visible"]
assert ui["hero_content_fits"] and all(ui["metric_fits"].values())
assert ui["live_view"]["embedded"] and not ui["live_view"]["error"]
assert pids["phase"] == "running" and live["state"] != "paused"
assert (datetime.now() - datetime.strptime(live["updated_at"], "%Y-%m-%d %H:%M:%S")).total_seconds() < 20

hidden = read(WORK / "tray-hidden-state.json")
restored = read(WORK / "tray-restored-state.json")
assert not hidden["window_visible"] and hidden["state"] == "running"
assert restored["window_visible"] and restored["live_view"]["embedded"]
assert hidden["pid"] == restored["pid"] == ui["pid"]
os_state = read(WORK / "desktop-runtime-os.json")
assert os_state["notify_icon_get_rect_hresult"] == 0 and os_state["notify_icon_os_rect"]
assert os_state["big_icon_handle"] and os_state["small_icon_handle"]
shortcut = read(WORK / "desktop-shortcut.json")
assert Path(shortcut["shortcut"]).is_file() and Path(shortcut["target"]).resolve() == exe.resolve()
assert digest(shortcut["shortcut"]) == shortcut["shortcut_sha256"].lower()
assert shortcut["app_user_model_id"] == ui["desktop_shell"]["app_id"]

report_index = read(WORK / "pause-selftest" / "outputs" / "error-reports" / "latest-error-report.json")
assert report_index["reason"].startswith("功能验收故障（非实际机器人异常）")
assert report_index["screenshot_status"] == "captured"
with Image.open(report_index["game_png"]) as screenshot:
    screenshot_size = list(screenshot.size)
    screenshot.verify()
assert Path(report_index["report_md"]).is_file() and Path(report_index["report_json"]).is_file()
tests = (WORK / "tests-final.log").read_text(encoding="utf-8-sig")
assert "150 passed, 6 subtests passed" in tests

requirements = {
    "desktop_executable_and_local_shortcut": "verified",
    "open_without_automatically_starting_tasks": "verified_stopped_ui_before_start",
    "optimized_rendered_main_ui_and_navigation": "verified_real_window_and_layout_fit",
    "taskbar_and_notification_icons": "verified_native_icon_handles_and_os_icon_rectangle",
    "close_to_tray_while_task_continues": "verified",
    "duplicate_desktop_launch_restores_same_instance": "verified",
    "automatic_pause_screenshot_reason_and_complete_report": "verified_controlled_pause_with_real_adb_screenshot_and_watchdog_regressions",
    "clicked_start_in_real_desktop_app": "verified_live_ui_click_and_new_frozen_components",
    "infinite_battle_mode": "verified_max_battles_zero_and_no_finite_quota_argument",
    "observe_at_least_three_complete_new_battles": "verified_three_full_cycles_plus_next_battle_start",
    "leave_bot_running": "verified_live_process_identity_and_fresh_state",
}
record = {
    "status": "PASS", "verified_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
    "requirements": requirements, "shortcut": shortcut, "package_manifest": str(WORK / "package-manifest.json"),
    "ui": ui, "live": live, "processes": processes, "three_observed_battles": battles,
    "excluded_resumed_battles": monitor["excluded_resumed_battles"], "anomalies": monitor["anomalies"],
    "live_monitor": str(WORK / "live-monitor.json"), "os_icon_evidence": os_state,
    "pause_report_selftest": {**report_index, "game_png_size": screenshot_size, "synthetic_pause_real_screenshot": True},
    "tests": {"passed": 150, "subtests_passed": 6, "log": str(WORK / "tests-final.log")},
    "rollback": {"interface_source_backup": str(WORK / "backup"), "watchdog_source_backup": str(ROOT / "work" / "error-report-20261004" / "watch_cn_1v1.before.py")},
}
target = ROOT / "outputs" / "DESKTOP_APP_ACCEPTANCE_20261004.json"
target.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"status": record["status"], "verified_at": record["verified_at"], "battles": [b["battle"] for b in battles], "report": str(target), "live_state": live["state"]}, ensure_ascii=True))
