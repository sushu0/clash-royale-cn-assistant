"""Persist the UI acceptance already observed without changing the robot state."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import psutil

ROOT = Path(r"D:\codex\CodexWork\clash")
WORK = ROOT / "work" / "ui-polish-20261004"


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main():
    current_path = ROOT / "work" / "wpf-desktop" / "frontend-state.json"
    frontend = load(current_path)
    baseline = load(WORK / "evidence-before" / "evidence-before.json")
    assert frontend["state"] == "stopped" and frontend["page"] == 0
    assert frontend["frontend_language"] == "C#" and frontend["framework"] == "WPF"
    assert psutil.pid_exists(frontend["pid"])
    assert frontend["ui"]["can_start"] is False
    assert frontend["ui"]["calibration_requested"] is True
    assert frontend["ui"]["recent_row_count"] == 10
    assert frontend["ui"]["recent_visible_capacity"] >= 6
    assert frontend["tray"]["start_enabled"] is False
    assert frontend["emulator"]["embedded"] is True
    assert frontend["emulator"]["game_input_sent"] is False
    assert frontend["report_count"] == 2
    report_hashes = []
    for report in baseline["report_files"]:
        actual = digest(Path(report["path"]))
        assert actual == report["sha256"]
        report_hashes.append({"path": report["path"], "sha256": actual})
    drain = ROOT / "work" / "random-mastery" / "DRAIN"
    assert digest(drain) == "A77CDF59B540802EB56A548087ECD033BD84E8E7C66A2D02851D4E12088D25F9"
    assert load(ROOT / "work" / "bot-processes.json")["phase"] == "stopped"
    vm = load(WORK / "viewmodel-check-result.json")
    native = load(WORK / "interop-check-result.json")
    assert vm["failed"] == 0 and vm["count"] == 35
    assert native.get("failed", 0) == 0
    final_dll = ROOT / "outputs" / "wpf-desktop-20261004" / "app" / "ClashAssistant.Desktop.dll"
    assert digest(final_dll) == "0A2B0D1D74CAB6145EBCEA566622B3C8B0C60581A88CC40549A288C6CE5F4122"
    record = {
        "status": "PASS_UI_POLISH_AND_PRESERVED_USER_STOP",
        "verified_at": datetime.now().isoformat(), "version": "2026.10.4.3",
        "frontend": frontend,
        "ui_observations": {
            "five_pages_rendered": True, "keyboard_page_navigation": True,
            "normal_window_full_recent_rows": 6, "maximized_full_recent_rows": 8,
            "recent_records_available": 10, "two_history_reports_selectable": True,
            "original_report_images_previewed": True,
            "game_splitter_dragged": True, "game_width_tested": [320, 392],
            "collapse_detaches_without_starting_bot": True,
            "restore_reembeds": True, "collapse_main_window_unobscured_after_fix": True,
            "chinese_logs_rendered_after_decoder_fix": True,
            "native_background_requested": "#142239",
            "native_letterbox_colour_verified": False,
            "note": "Native preview preserves aspect ratio and can show padding; no pixel-colour claim is made.",
        },
        "validation": {
            "release_publish": "PASS", "viewmodel_cases": vm["count"],
            "native_interop_cases": 12, "python_backend_cases": 28,
            "python_compile_and_ruff": "PASS",
            "readonly_frozen_backend": str(WORK / "staged-backend-acceptance.json"),
            "independent_source_pdb_baml_and_backend_lineage": str(WORK / "final-package-verification" / "final-delivery-manifest.json"),
            "no_new_frontend_errors_after_repaired_startup": True,
        },
        "preserved": {"reports": report_hashes, "drain_sha256": digest(drain), "bot_started_for_this_polish": False},
        "rollback": {"app": str(WORK / "package-before" / "app"), "backend": str(WORK / "package-before" / "backend"), "method": "Exit software normally, then copy these original app and backend directories back to outputs/wpf-desktop-20261004."},
    }
    target = ROOT / "outputs" / "WPF_UI_POLISH_ACCEPTANCE_20261004.json"
    target.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (WORK / "final-frontend-state.json").write_bytes(current_path.read_bytes())
    print(f"PASS: {target}; frontend PID={frontend['pid']}; state=stopped; visible rows={frontend['ui']['recent_visible_capacity']}")


if __name__ == "__main__":
    main()
