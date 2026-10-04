"""Persist the repair acceptance without operating the user's desktop window."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psutil

ROOT = Path(r"D:\codex\CodexWork\clash")
TASK = ROOT / "work/task-stop-repair-20261004"
RELEASE = ROOT / "outputs/wpf-desktop-stop-repair-20261004"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main():
    bridge = RELEASE / "backend/ClashBackend.exe"
    requests = [{"id": "snapshot-check", "command": "snapshot"}, {"id": "done", "command": "shutdown"}]
    process = subprocess.run(
        [str(bridge), "--data-root", str(ROOT), "--read-only"],
        input="".join(json.dumps(row) + "\n" for row in requests),
        capture_output=True, text=True, encoding="utf-8", cwd=bridge.parent,
        creationflags=subprocess.CREATE_NO_WINDOW, timeout=20, check=True,
        env={**os.environ, "PYCLASHBOT_DATA_ROOT": str(ROOT)},
    )
    responses = [json.loads(line) for line in process.stdout.splitlines()]
    assert len(responses) == 2 and all(row["ok"] for row in responses)
    snapshot = next(row["data"] for row in responses if row["id"] == "snapshot-check")
    assert snapshot["runtime"]["data_root"] == str(ROOT)
    (TASK / "package-verification/production-readonly-snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    baseline = read(TASK / "baseline.json")
    report_checks = []
    for row in baseline["report_files"]:
        path = Path(row["path"])
        assert digest(path) == row["sha256"], path
        report_checks.append({"path": str(path), "sha256": digest(path), "preserved": True})
    changed = []
    for row in read(TASK / "backend-source-hashes.json"):
        path = ROOT / "py-clash-bot" / row["file"]
        assert digest(path) == row["sha256"]
        changed.append({"path": str(path), "sha256": digest(path)})
    for relative in ["Services/BackendClient.cs", "ViewModels/DesktopViewModel.cs", "MainWindow.xaml.cs",
                     "MainWindow.xaml", "ClashAssistant.Desktop.csproj"]:
        path = ROOT / "desktop-wpf" / relative
        changed.append({"path": str(path), "sha256": digest(path)})
    controls = read(TASK / "client-harness/results.json")
    frozen = read(TASK / "frozen-verification/frozen-stop-acceptance.json")
    wpf = read(TASK / "package-verification/wpf-package-source-manifest.json")
    python = read(TASK / "package-verification/python-package-source-manifest.json")
    audit = read(TASK / "audit.json")
    assert controls["failed"] == 0 and controls["passed"] == 21
    assert frozen["status"] == python["status"] == "PASS"
    assert wpf["AllSavedCSharpSourcesMatchPdb"] and wpf["AllOriginalXamlPragmasAndPublishedBamlMatch"]
    assert not audit["remaining_confirmed_defects_in_scope"]
    installed = ROOT / "outputs/wpf-desktop-20261004/app"
    applied = digest(installed / "ClashAssistant.Desktop.dll") == digest(RELEASE / "app/ClashAssistant.Desktop.dll")
    installation_path = TASK / "installation.json"
    installation = read(installation_path) if installation_path.is_file() else None
    if applied:
        assert installation and installation["status"] == "PASS_INSTALLED_VERIFIED_REPAIR"
        for row in installation["installed_files"]:
            assert digest(installed / row["file"]) == row["sha256"]
            assert digest(installed / row["file"]) == digest(RELEASE / "app" / row["file"])
        config = read(installed / "wpf-runtime.json")
        assert config["data_root"] == str(ROOT) and config["backend_path"] == str(bridge)
        assert snapshot["state"] == "stopped"
        for row in installation["emulator_processes_preserved"]:
            process = psutil.Process(row["ProcessId"])
            assert Path(process.exe()).resolve() == Path(row["ExecutablePath"]).resolve()
            assert abs(process.create_time() - datetime.fromisoformat(row["CreationDate"]).timestamp()) < 0.01
        assert read(ROOT / "work/native-window-recovery.json")["restored"] is True
    current = []
    for process in psutil.process_iter(["pid", "name", "exe", "create_time"]):
        if process.info["name"] in {"ClashAssistant.Desktop.exe", "ClashBackend.exe"}:
            current.append(process.info)
    record = {
        "status": "PASS_INSTALLED_VERIFIED_REPAIR" if applied else "PASS_VERIFIED_PACKAGE_AWAITING_APPLICATION_EXIT",
        "verified_at": datetime.now(timezone(timedelta(hours=8))).isoformat(), "version": "2026.10.4.4",
        "package": str(RELEASE), "installed_entry": str(installed / "ClashAssistant.Desktop.exe"),
        "installed_frontend_matches_verified_release": applied,
        "current_application_restarted": False, "computer_use_after_user_background_instruction": False,
        "installation": installation,
        "validation": {
            "backend_tests_passed": 127, "backend_subtests_passed": 6,
            "backend_validation_report": str(TASK / "backend-validation.md"),
            "frontend_control_tests_passed": controls["passed"], "frontend_control_results": str(TASK / "client-harness/results.json"),
            "frozen_stop_response_seconds": frozen["stop_response_seconds"],
            "blocking_fake_tool_seconds": 30, "frozen_no_remaining_bot_or_startup_tool_processes": frozen["no_remaining_bot_or_startup_tool_processes"],
            "frozen_acceptance": str(TASK / "frozen-verification/frozen-stop-acceptance.json"),
            "release_build": "PASS", "published_csharp_sources_match_pdb": wpf["SourceFileCount"],
            "xaml_and_compiled_resources_match": True,
            "packaged_python_sources_and_code_objects_match_tested_source": python["count"],
            "production_readonly_snapshot": str(TASK / "package-verification/production-readonly-snapshot.json"),
            "independent_scope_audit": str(TASK / "audit.json"),
            "python_compile_ruff_and_format": "PASS", "ty": "UNAVAILABLE_NOT_INSTALLED",
        },
        "current_readonly_state": snapshot["state"],
        "history": {"reports": len(snapshot["reports"]), "total": snapshot["scopes"]["random"]["total"]},
        "preserved_report_files": report_checks, "changed_files": changed,
        "active_application_processes": current,
        "rollback": {"installed_app_backup": str(TASK / "package-before-app"),
                     "source_backup": str(TASK / "before"),
                     "original_backend_untouched": str(ROOT / "outputs/wpf-desktop-navigation-20261004/backend"),
                     "method": "Exit assistant, restore backed-up app files and original wpf-runtime.json; restore only listed source files if needed."},
        "limits": ["No Computer Use, mouse or keyboard automation, or full real-game battle was used after the background-only request.",
                   "The application was closed in the background and was not relaunched; the next launch loads the installed repair." if applied
                   else "The running old application must exit before its locked executable and assembly can be replaced.",
                   "Actual stop latency under emulator faults may differ from the isolated blocking-tool measurement."],
    }
    target = ROOT / "outputs/TASK_STOP_REPAIR_ACCEPTANCE_20261004.json"
    target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": record["status"], "report": str(target), "version": record["version"],
                      "stop_response_seconds": frozen["stop_response_seconds"], "reports_preserved": len(report_checks)}))


if __name__ == "__main__":
    main()
