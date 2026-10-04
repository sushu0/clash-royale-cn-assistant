"""Persist final evidence for the native console and its read-only live view."""

import ast
import hashlib
import json
from datetime import datetime
from pathlib import Path

TASK = Path(r"D:\codex\CodexWork\clash")
RUN = TASK / "work" / "live-console-20261003"
ENTRY = TASK / "py-clash-bot" / "scripts" / "cn_bot_control.py"
VIEW = TASK / "py-clash-bot" / "pyclashbot" / "interface" / "cn_live_view.py"
THEME = TASK / "py-clash-bot" / "pyclashbot" / "interface" / "cn_console_theme.py"
SCREENSHOT = TASK / "outputs" / "live-console-preview.jpg"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def methods(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    window = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ControlWindow")
    return {node.name: ast.dump(node, include_attributes=False)
            for node in window.body if isinstance(node, ast.FunctionDef)}


def main():
    original = methods(RUN / "cn_bot_control.before.py")
    current = methods(ENTRY)
    retained = {name: current[name] == original[name] for name in (
        "_start_worker", "_stop_worker", "_history_worker", "_open_result", "_action", "_start", "_stop")}
    qa_reports = [read_json(RUN / "qa" / "validation.json"),
                  read_json(RUN / "qa" / "minimum" / "validation.json")]
    live = read_json(TASK / "work" / "random-frontend-state.json")
    paused = read_json(RUN / "paused-state.json")
    resumed = read_json(RUN / "resumed-state.json")
    passed_checks = sum(report["passed_count"] for report in qa_reports)
    total_checks = sum(report["check_count"] for report in qa_reports)
    checks = {
        "original_control_and_history_methods_retained": all(retained.values()),
        "existing_theme_retained": digest(THEME) == "5d5f85f030cb8da40a71890c3d87af76b9e13f34e5447394081e36815c76d14b",
        "offline_layout_and_interactions": passed_checks == total_checks,
        "no_forbidden_qa_operations": all(not report["forbidden_operations"] for report in qa_reports),
        "native_runtime_errors_absent": (RUN / "live-stderr.log").stat().st_size == 0,
        "live_real_device": live["live_view"]["state"] == "live" and live["live_view"]["source"] == "adb_screencap",
        "native_portrait_frame": live["live_view"]["frame_size"] == [419, 633],
        "statistics_fit": all(live["metric_fits"].values()) and live["hero_content_fits"],
        "pause_retains_robot_running": paused["live_view"]["state"] == "paused" and paused["state"] == "running",
        "resume_returns_to_live": resumed["live_view"]["state"] == "live" and resumed["state"] == "running"
        and resumed["live_view"]["frame_count"] > paused["live_view"]["frame_count"],
        "native_screenshot_saved": SCREENSHOT.is_file() and SCREENSHOT.stat().st_size > 0,
    }
    rollback = {"restore": {str(ENTRY): str(RUN / "cn_bot_control.before.py")},
                "new_component": str(VIEW), "close_scope": "control window only",
                "sources": {str(path): digest(path) for path in (ENTRY, VIEW, THEME)},
                "backup_sha256": digest(RUN / "cn_bot_control.before.py")}
    (RUN / "rollback.json").write_text(json.dumps(rollback, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {"observed_at": datetime.now().astimezone().isoformat(), "checks": checks,
              "passed": all(checks.values()), "offline_checks": {"passed": passed_checks, "total": total_checks},
              "source_methods": retained, "live_snapshot": live, "paused_snapshot": paused,
              "resumed_snapshot": resumed, "robot_processes": read_json(TASK / "work" / "bot-processes.json"),
              "screenshot": {"path": str(SCREENSHOT), "sha256": digest(SCREENSHOT)},
              "native_ui_interactions_observed": ["records", "strategy comparison", "run log", "pause", "resume", "reconnect", "maximize"],
              "sources": rollback["sources"],
              "visual_review": ["compact green navigation", "statistics on the left", "complete portrait image on the right",
                                "consistent typography and metric colors", "stable spacing and separate viewer controls"],
              "limitations": ["Read-only screen mirroring, target 2 FPS; no game input forwarded from this view.",
                              "Native Windows Tk UI; browser checks are not applicable.",
                              "Runtime values are observations and will continue to change."]}
    target = TASK / "outputs" / "live-console-validation.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "checks": checks, "offline_checks": report["offline_checks"],
                      "runtime_fps": live["live_view"]["fps"], "runtime_frame_count": live["live_view"]["frame_count"],
                      "report": str(target)}, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
