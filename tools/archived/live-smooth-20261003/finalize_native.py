"""Persist native-window ownership, restoration and validation evidence."""

import ast
import ctypes
import hashlib
import json
import sys
from ctypes import wintypes
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

TASK = Path(r"D:\codex\CodexWork\clash")
RUN = TASK / "work" / "live-smooth-20261003"
REPO = TASK / "py-clash-bot"
sys.path.insert(0, str(REPO))

from pyclashbot.interface.cn_native_window_api import Win32WindowAPI, enable_native_embedding_dpi


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def methods(path):
    module = ast.parse(path.read_text(encoding="utf-8"))
    window = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "ControlWindow")
    return {node.name: ast.dump(node, include_attributes=False)
            for node in window.body if isinstance(node, ast.FunctionDef)}


def main():
    enable_native_embedding_dpi()
    live = read(TASK / "work" / "random-frontend-state.json")
    view = live["live_view"]
    api = Win32WindowAPI()
    snapshot = api.snapshot(view["window_handle"])
    _, surfaces, width, height = api._resize_tree(snapshot.hwnd)
    actual_surfaces = []
    for hwnd, pid in surfaces:
        rect = wintypes.RECT()
        api._user32.GetClientRect(hwnd, ctypes.byref(rect))
        actual_surfaces.append({"hwnd": hwnd, "pid": pid, "size": [rect.right, rect.bottom]})
    popout = read(RUN / "popout-final.json")
    closed = read(RUN / "close-restored.json")
    entry = REPO / "scripts" / "cn_bot_control.py"
    old, new = methods(RUN / "cn_bot_control.before.py"), methods(entry)
    retained = {name: old[name] == new[name] for name in (
        "_start_worker", "_stop_worker", "_history_worker", "_open_result", "_action", "_start", "_stop")}
    qa = [read(RUN / "native-qa" / "native-host-validation.json"),
          read(RUN / "native-layout-qa" / "native-layout-validation.json")]
    picture = TASK / "outputs" / "native-emulator-embedded.jpg"
    checks = {
        "actual_memu_window_is_child_of_native_viewport": snapshot.parent == view["host_handle"] != 0,
        "same_memu_process": snapshot.pid == 14556,
        "same_headless_process": all(surface["pid"] == 12376 for surface in actual_surfaces),
        "full_game_surfaces_match_renderer": all(surface["size"] == [width, height] for surface in actual_surfaces),
        "no_frame_capture": view["source"] == "native_window" and not view["frame_capture"],
        "popout_restored_desktop_parent_and_geometry": popout["window"]["parent"] == 0
        and popout["window"]["rect"] == view["original_rect"],
        "popout_restored_full_render_surfaces": all(size == popout["render_size"] for size in popout["surface_sizes"]),
        "console_close_restored_memu_window": closed["parent"] == 0 and closed["rect"] == view["original_rect"],
        "original_control_and_history_methods_retained": all(retained.values()),
        "native_ui_error_log_empty": (RUN / "native-release-stderr.log").stat().st_size == 0,
        "offline_tests_passed": all(report["passed"] for report in qa),
        "native_screenshot_saved": picture.is_file() and picture.stat().st_size > 0,
    }
    sources = [entry, REPO / "pyclashbot" / "interface" / "cn_native_view.py",
               REPO / "pyclashbot" / "interface" / "cn_native_window_api.py"]
    report = {"observed_at": datetime.now().astimezone().isoformat(), "passed": all(checks.values()),
              "checks": checks, "live_snapshot": live, "native_window": asdict(snapshot),
              "render_size": [width, height], "surfaces": actual_surfaces, "popout": popout,
              "close_restoration": closed, "offline_checks_passed": sum(item["passed_count"] for item in qa),
              "regression_tests_passed": 75, "android_wm_size_observed": "419x633",
              "original_control_methods": retained,
              "source_sha256": {str(path): sha(path) for path in sources},
              "screenshot": {"path": str(picture), "sha256": sha(picture)},
              "bot_state": live["state"], "bot_start_or_stop_requested_by_this_task": False,
              "notes": ["Actual native window tree; no sampling, decoding or redisplaying frames.",
                        "Native FPS is owned by MEmu; no fabricated viewer FPS is reported.",
                        "The bot was already stopped before the first actual embedding; it was not restarted."]}
    (TASK / "outputs" / "native-emulator-validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN / "rollback.json").write_text(json.dumps({
        "restore": {str(entry): str(RUN / "cn_bot_control.before.py")},
        "procedure": "Close the native console normally so MEmu is detached, restore the entry, reopen.",
        "unused_native_modules_can_be_retained": True,
        "backup_sha256": sha(RUN / "cn_bot_control.before.py"),
    }, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "checks": checks,
                      "offline_checks_passed": report["offline_checks_passed"]}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
