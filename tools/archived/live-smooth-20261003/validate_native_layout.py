"""Minimum native-console layout and close ordering; fake HWND, frozen statistics."""

from __future__ import annotations

import importlib.util
import json
import sys
import traceback
from pathlib import Path

TASK = Path(r"D:\codex\CodexWork\clash")
REPO = TASK / "py-clash-bot"
RUN = TASK / "work" / "live-smooth-20261003"
sys.path.insert(0, str(REPO))
sys.dont_write_bytecode = True


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    output = RUN / "native-layout-qa"
    output.mkdir(parents=True, exist_ok=True)
    helpers = load("original_layout_helpers", TASK / "work" / "live-console-20261003" / "validate_layout.py")
    database = output / "frozen-index.sqlite3"
    production_source = helpers.freeze_history(database)
    forbidden = []
    helpers.install_write_guard(output, forbidden)
    console = load("native_console_isolated", REPO / "scripts" / "cn_bot_control.py")
    fake_module = load("native_api_fake", RUN / "validate_native_host.py")
    from pyclashbot.interface.cn_native_view import NativeEmulatorView, WindowSnapshot

    console.HISTORY_DB = database
    console.OUTPUTS = output / "isolated-traces"
    console.RANDOM_TRACE = console.OUTPUTS / "random.jsonl"
    console.REWARDS_TRACE = console.OUTPUTS / "rewards.jsonl"
    history = console.BattleHistory(database)
    try:
        frozen = {scope: history.snapshot(scope) for scope in console.SCOPES.values()}
        frozen["reward_totals"] = history.reward_snapshot()
    finally:
        history.close()
    console.bot_state = lambda: "running"
    console.enable_native_embedding_dpi = lambda: True  # Own-process DPI is irrelevant to fake HWND lifecycle.
    console.selected_strategy = lambda: "random"
    console.read_random_status = lambda: {"state": "battle", "completed": 812, "cards_confirmed": 23,
                                         "last_action": {"card": "arrows", "category": "spell", "phase": "confirmed"},
                                         "decision_reason": "离线布局检查", "strategy_version": "offline-qa"}
    console.tail_log = lambda *_args, **_kwargs: []
    console.ControlWindow._history_worker = lambda _window: None
    console.ControlWindow._export_frontend_state = lambda *_args, **_kwargs: None

    def block_action(*_args, **_kwargs):
        forbidden.append({"event": "robot_action", "target": "disabled in native layout QA"})
        raise RuntimeError("Robot actions are forbidden in native layout QA")

    for method in ("_start", "_stop", "_start_worker", "_stop_worker"):
        setattr(console.ControlWindow, method, block_action)
    original_window = console.ttk.Window

    def transparent_window(*args, **kwargs):
        root = original_window(*args, **kwargs)
        root.attributes("-alpha", 0.0)
        return root

    console.ttk.Window = transparent_window
    api = fake_module.FakeSurfaceAPI(WindowSnapshot)

    def fake_native_view(parent, **kwargs):
        return NativeEmulatorView(parent, **kwargs, api=api)

    console.NativeEmulatorView = fake_native_view
    report = {"checks": [], "forbidden_operations": forbidden, "production_source": str(production_source),
              "frozen_database": str(database), "scope": "1240x800 native Tk layout and root close ordering",
              "limits": "Native API is fake; no emulator HWND or real embedding is exercised"}

    def check(name, condition, **details):
        report["checks"].append({"name": name, "passed": bool(condition), **details})

    window = None
    try:
        window = console.ControlWindow()
        window.root.geometry("1240x800+0+0")
        window.history_snapshots = frozen
        window._render_history()
        helpers.settle(window.root, 0.25)
        window._refresh()
        helpers.settle(window.root, 0.2)
        window._fit_metrics()
        helpers.settle(window.root, 0.08)
        page_rect = helpers.widget_rectangle(window.root, window.page)
        native_rect = helpers.widget_rectangle(window.root, window.live_panel)
        check("statistics stay left and native host stays right", page_rect[2] <= native_rect[0]
              and page_rect[1] == native_rect[1], statistics=page_rect, native=native_rect)
        check("native viewport and controls fit minimum console size",
              all(widget.winfo_ismapped() and widget.winfo_width() > 1 and widget.winfo_height() > 1
                  for widget in (window.live_panel, window.live_view, window.live_view.viewport,
                                 window.live_view.native_surface, window.live_view.embed_button,
                                 window.live_view.popout_button)))
        surface_rect = helpers.widget_rectangle(window.live_view.viewport, window.live_view.native_surface)
        viewport_size = [window.live_view.viewport.winfo_width(), window.live_view.viewport.winfo_height()]
        check("native clipping surface fits and centers inside viewport",
              surface_rect[0] >= 0 and surface_rect[1] >= 0 and surface_rect[2] <= viewport_size[0]
              and surface_rect[3] <= viewport_size[1]
              and abs(surface_rect[0] - (viewport_size[0] - surface_rect[2])) <= 1
              and abs(surface_rect[1] - (viewport_size[1] - surface_rect[3])) <= 1,
              surface=surface_rect, viewport=viewport_size)
        check("native window is attached to the dedicated clipping frame",
              api.state.parent == window.live_view.native_surface.winfo_id())
        for pane in range(3):
            window._select_view(pane)
            helpers.settle(window.root, 0.08)
            overflow = helpers.visible_bounds(window.root)
            check(f"minimum console client fits pane {pane}", not overflow, overflow=overflow)
        labels = helpers.label_overflow(window.page) + helpers.label_overflow(window.live_view)
        check("statistics and native-view labels fit minimum size", not labels, clipped=labels)
        expected = helpers.expected_metrics(console, frozen["random"], frozen["reward_totals"])
        observed = {key: value.get() for key, value in window.metrics.items()}
        check("left statistics preserve frozen counts and rewards", observed == expected, observed=observed, expected=expected)
        check("native diagnostics do not claim an invented video FPS",
              window.live_view.diagnostics().get("source") == "native_window"
              and "fps" not in window.live_view.diagnostics(), diagnostics=window.live_view.diagnostics())
        resize_count = sum(call["name"] == "resize_render_surfaces" for call in api.calls)
        move_count = sum(call["name"] == "move_window" for call in api.calls)
        helpers.settle(window.root, 1.05)
        check("native view poll synchronizes render surfaces while preserving top geometry",
              sum(call["name"] == "resize_render_surfaces" for call in api.calls) > resize_count
              and sum(call["name"] == "move_window" for call in api.calls) == move_count,
              diagnostics=window.live_view.diagnostics())
        report["layout"] = {"actual_size": [window.root.winfo_width(), window.root.winfo_height()],
                            "statistics": page_rect, "native": native_rect,
                            "viewport": helpers.widget_rectangle(window.root, window.live_view.viewport)}

        # A detach failure must keep the embedding parent alive for a safe retry.
        api.fail_once = "restore"
        window._on_close()
        check("root survives a failed native detach", bool(window.root.winfo_exists())
              and not window.history_stop.is_set() and not window.live_view.diagnostics()["closed"]
              and window.live_view.host.snapshot_state is not None, notice=window.notice.get())
        destroy_observation = []
        original_destroy = window.root.destroy

        def observed_destroy():
            destroy_observation.append({"restored": api.original_restored(), "calls": len(api.calls)})
            original_destroy()

        window.root.destroy = observed_destroy
        window._on_close()
        check("successful close restores native window before destroying Tk host",
              bool(destroy_observation) and destroy_observation[0]["restored"], observed=destroy_observation)
        check("successful close stops only the statistics reader", window.history_stop.is_set() and not forbidden)
        report["native_calls"] = api.calls
        window = None
    except Exception as error:
        report["exception"] = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
        check("minimum layout QA completes without exception", False)
    finally:
        if window is not None:
            try:
                window.live_view.close()
                window.root.destroy()
            except Exception as error:
                report["cleanup_error"] = str(error)
    report["passed_count"] = sum(item["passed"] for item in report["checks"])
    report["check_count"] = len(report["checks"])
    report["passed"] = bool(report["checks"]) and all(item["passed"] for item in report["checks"])
    (output / "native-layout-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "checks": report["check_count"], "passed_count": report["passed_count"],
                      "failures": [item["name"] for item in report["checks"] if not item["passed"]],
                      "exception": report.get("exception", {}).get("message"),
                      "report": str(output / "native-layout-validation.json")}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
