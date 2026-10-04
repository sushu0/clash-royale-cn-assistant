"""Final read-only delivery audit respecting the user's explicit stopped state."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psutil

root = Path(r"D:\codex\CodexWork\clash")
work = root / "work" / "wpf-rewrite-20261004"

def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

ui = read(root / "work" / "wpf-desktop" / "frontend-state.json")
assert ui["frontend_language"] == "C#" and ui["framework"] == "WPF" and not ui["preview"]
assert ui["state"] == "stopped" and ui["report_count"] == 2
assert ui["tray"]["tray_icon_added"] and ui["backend_running"]
gui = psutil.Process(ui["pid"])
assert gui.is_running() and Path(gui.exe()).resolve() == (root / "outputs/wpf-desktop-20261004/app/ClashAssistant.Desktop.exe").resolve()
children = gui.children()
bridges = [p for p in children if Path(p.exe()).name == "ClashBackend.exe"]
assert len(bridges) == 1
assert not [p for p in psutil.process_iter(["name", "cmdline"]) if p.info["name"] == "ClashBackend.exe" and "--component" in (p.info["cmdline"] or [])]
normal_exit = read(work / "normal-exit-verification.json")
assert normal_exit["gui_absent"] and normal_exit["bridge_absent"] and normal_exit["native_recovery"]["restored"]
hidden = read(work / "final-tray-hidden.json")
restored = read(work / "final-tray-restored.json")
assert hidden["pid"] == restored["pid"] and not hidden["visible"] and not hidden["emulator"]["embedded"]
assert restored["visible"] and restored["emulator"]["embedded"]
baseline = read(work / "old-reports-before.json")
original = read(root / "work/error-history-20261004/original-report-hashes.json")
for item in original:
    assert digest(item["path"]) == item["sha256"].lower()
drain = root / "work/random-mastery/DRAIN"
assert drain.stat().st_size == 80
assert digest(drain) == "a77cdf59b540802eb56a548087ecd033bd84e8e7c66a2d02851d4e12088d25f9"
monitor = read(work / "live-monitor.json")
assert not monitor["anomalies"]["pause_events"] and not monitor["anomalies"]["watchdog_error_lines"]
record = {
    "status": "PASS_FRONTEND_REWRITE_AND_USER_REQUESTED_STOP", "verified_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
    "frontend_language": "C#", "ui_framework": "WPF", "backend_language": "Python",
    "user_requested_state": "保持停止，保留导航校准请求", "drain_preserved": True,
    "frontend": ui, "frontend_process": {"pid": gui.pid, "executable": gui.exe(), "created_at": gui.create_time()},
    "bridge_process": {"pid": bridges[0].pid, "executable": bridges[0].exe(), "created_at": bridges[0].create_time()},
    "normal_exit": normal_exit, "same_instance_restore": {"hidden": hidden, "restored": restored},
    "history_original_files_unchanged": True, "historical_error_report_count": 2,
    "real_battle_cycles_completed": [1197, 1198], "three_continuous_battle_gate_passed": False,
    "run_end": "正常排空，用户明确要求继续保持停止", "live_monitor": str(work / "live-monitor.json"),
    "package_source_manifest": str(work / "wpf-package-source-manifest.json"),
    "validation": {"python_tests_passed": 133, "python_subtests_passed": 6, "python_tests_skipped": 1, "client_self_tests": 17, "viewmodel_self_tests": 12, "native_self_tests": 12},
    "delivery_guide": str(root / "outputs/WPF_DESKTOP_DELIVERY_20261004.md"), "shortcut_backup": str(work / "shortcut-backup"),
}
target = root / "outputs/WPF_DESKTOP_ACCEPTANCE_20261004.json"
target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"status": record["status"], "ui_pid": gui.pid, "bridge_pid": bridges[0].pid, "state": ui["state"], "reports": ui["report_count"], "acceptance": str(target)}, ensure_ascii=True))
