"""Validate the split native console with frozen history and injected offline frames.

No robot, ADB process, device input, or production diagnostic may be invoked.
Run with the existing project Python after the UI implementation is complete.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sqlite3
import sys
import time
import traceback
from pathlib import Path


TASK = Path(r"D:\codex\CodexWork\clash")
REPO = TASK / "py-clash-bot"
RUN = TASK / "work" / "live-console-20261003"
sys.path.insert(0, str(REPO))
sys.dont_write_bytecode = True


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qa-directory", type=Path, default=RUN / "qa")
    parser.add_argument("--minimum-only", action="store_true", help="Check only the 1240x800 production minimum layout")
    return parser.parse_args()


def install_write_guard(qa, audit):
    """Fail closed if the tested process attempts production writes or launches."""
    allowed = qa.resolve()

    def inside(value):
        if isinstance(value, (str, bytes, os.PathLike)):
            return Path(os.fsdecode(value)).resolve().is_relative_to(allowed)
        return True  # Integer descriptors are handled by the opening operation.

    def guard(event, args):
        blocked = False
        if event == "open":
            mode = args[1]
            flags = args[2]
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)))
            blocked = writing and not inside(args[0])
        elif event == "sqlite3.connect":
            blocked = not inside(args[0])
        elif event in {"os.mkdir", "os.chmod", "os.utime"}:
            blocked = not inside(args[0])
        elif event in {"os.rename", "os.replace"}:
            blocked = not inside(args[0]) or not inside(args[1])
        elif event in {"subprocess.Popen", "os.system", "os.startfile", "os.startfile/2", "os.remove", "os.rmdir", "socket.connect", "socket.bind", "socket.getaddrinfo"}:
            blocked = True
        if blocked:
            audit.append({"event": event, "target": str(args[0]) if args else ""})
            raise RuntimeError(f"QA safety guard blocked {event}")

    sys.addaudithook(guard)


def freeze_history(destination):
    source = TASK / "outputs" / "cn-battle-history.sqlite3"
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=10) as production:
        with sqlite3.connect(destination) as isolated:
            production.backup(isolated)
    return source


def settle(root, duration=0.08):
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        root.update()
        time.sleep(0.005)


def is_disabled(widget):
    instate = getattr(widget, "instate", None)
    return instate(["disabled"]) if callable(instate) else widget.cget("state") == "disabled"


def expected_metrics(console, data, rewards):
    return {
        "total": str(data["total"]["total"]),
        "wins": str(data["total"]["wins"]),
        "losses": str(data["total"]["losses"]),
        "rate": console.rate_text(data["total"]),
        "recent": console.rate_text(data["recent"]),
        "rewards": f"{rewards['rewards']:,}",
        "coins": f"{rewards['coins']:,}" + ("+" if rewards["unknown_coin_items"] else ""),
    }


def visible_bounds(root):
    """Report child widgets clipped by the client or their immediate parent."""
    width, height = root.winfo_width(), root.winfo_height()
    origin_x, origin_y = root.winfo_rootx(), root.winfo_rooty()
    errors = []

    def walk(parent):
        for child in parent.winfo_children():
            if child.winfo_ismapped():
                left = child.winfo_rootx() - origin_x
                top = child.winfo_rooty() - origin_y
                right = left + child.winfo_width()
                bottom = top + child.winfo_height()
                if left < -2 or top < -2 or right > width + 2 or bottom > height + 2:
                    errors.append({"kind": "client", "widget": str(child), "class": child.winfo_class(),
                                   "rectangle": [left, top, right, bottom]})
                parent_left = child.winfo_rootx() - parent.winfo_rootx()
                parent_top = child.winfo_rooty() - parent.winfo_rooty()
                parent_right = parent_left + child.winfo_width()
                parent_bottom = parent_top + child.winfo_height()
                if (parent_left < -2 or parent_top < -2 or parent_right > parent.winfo_width() + 2
                        or parent_bottom > parent.winfo_height() + 2):
                    errors.append({"kind": "parent", "widget": str(child), "parent": str(parent),
                                   "class": child.winfo_class(), "rectangle": [parent_left, parent_top, parent_right, parent_bottom],
                                   "parent_size": [parent.winfo_width(), parent.winfo_height()]})
                walk(child)

    walk(root)
    return errors


def widget_rectangle(root, widget):
    left = widget.winfo_rootx() - root.winfo_rootx()
    top = widget.winfo_rooty() - root.winfo_rooty()
    return [left, top, left + widget.winfo_width(), top + widget.winfo_height()]


def label_overflow(parent):
    errors = []
    for child in parent.winfo_children():
        if not child.winfo_ismapped():
            continue
        if child.winfo_class() in {"Label", "TLabel"}:
            if child.winfo_reqwidth() > child.winfo_width() + 2 or child.winfo_reqheight() > child.winfo_height() + 2:
                errors.append({"widget": str(child), "text": child.cget("text"),
                               "actual": [child.winfo_width(), child.winfo_height()],
                               "requested": [child.winfo_reqwidth(), child.winfo_reqheight()]})
        errors.extend(label_overflow(child))
    return errors


def layout_dimensions(window):
    attributes = {str(value): key for key, value in vars(window).items() if hasattr(value, "winfo_height")}

    def dimensions(widget):
        return {"widget": str(widget), "name": attributes.get(str(widget)),
                "actual": [widget.winfo_width(), widget.winfo_height()],
                "requested": [widget.winfo_reqwidth(), widget.winfo_reqheight()]}

    result = {"fixed_panels": [], "detail_panel": dimensions(window.detail_panel),
              "tree": dimensions(window.history_tree), "page": dimensions(window.page),
              "header_footer": []}
    for panel in window.fixed_panels:
        row = dimensions(panel)
        row.update(padding=panel.padding, body=dimensions(panel.body))
        result["fixed_panels"].append(row)
    for child in window.page.winfo_children():
        grid = child.grid_info()
        if grid and grid["row"] in (0, 5):
            row = dimensions(child)
            row["grid_row"] = grid["row"]
            row["grid_pady"] = str(grid["pady"])
            result["header_footer"].append(row)
    tree_style = window.history_tree.cget("style")
    result["tree"]["rowheight"] = window.root.style.lookup(tree_style, "rowheight")
    result["tree"]["visible_badges"] = sum(badge.winfo_ismapped() for badge in window.history_tree._badge_pool)
    result["detail_panel"]["body"] = dimensions(window.detail_panel.body)
    result["history_source_label"] = dimensions(window.history_source_label)
    result["history_source_label"]["mapped"] = bool(window.history_source_label.winfo_ismapped())
    return result


def main():
    args = parse_args()
    qa = args.qa_directory.resolve()
    if not qa.is_relative_to(RUN.resolve()):
        raise ValueError("QA output must stay in this task's live-console directory")
    qa.mkdir(parents=True, exist_ok=True)
    database = qa / "index.sqlite3"
    production_source = freeze_history(database)
    forbidden = []
    install_write_guard(qa, forbidden)

    spec = importlib.util.spec_from_file_location("cn_live_console_isolated_qa", REPO / "scripts" / "cn_bot_control.py")
    console = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(console)
    console.HISTORY_DB = database
    console.OUTPUTS = qa / "no-live-traces"
    console.RANDOM_TRACE = console.OUTPUTS / "random.jsonl"
    console.REWARDS_TRACE = console.OUTPUTS / "rewards.jsonl"
    history = console.BattleHistory(database)
    try:
        frozen = {scope: history.snapshot(scope) for scope in console.SCOPES.values()}
        frozen["reward_totals"] = history.reward_snapshot()
    finally:
        history.close()
    (qa / "expected-snapshots.json").write_text(json.dumps(frozen, ensure_ascii=False, indent=2), encoding="utf-8")

    report = {"production_source": str(production_source), "isolated_database": str(database),
              "checks": [], "layout": [], "forbidden_operations": forbidden,
              "safety": {"production_connection": "SQLite read-only source + backup API",
                         "trace_ingestion": "redirected to missing isolated paths",
                         "robot_actions": "stubbed before constructing widgets",
                         "windows_interaction": "native Tk only; no device input or external capture",
                         "mirror_source": "injected deterministic PIL frames; ADB capture disabled",
                         "browser_route": "not applicable: target is native Tk, not a web page"}}

    def check(name, condition, **details):
        report["checks"].append({"name": name, "passed": bool(condition), **details})

    simulated = {"state": "running"}
    actions = {"start": 0, "stop": 0, "worker": 0}
    result_calls = []
    console.bot_state = lambda: simulated["state"]
    console.selected_strategy = lambda: "random"
    reward_totals = frozen["reward_totals"]
    live = {"state": "battle", "completed": frozen["random"]["total"]["total"],
            "generated_decks": frozen["random"]["total"]["total"] + 8,
            "claim_all_batches": 112, "rewards_received": reward_totals["rewards"],
            "coins_received": reward_totals["coins"],
            "unknown_coin_items": reward_totals["unknown_coin_items"],
            "cards_confirmed": 23, "strategy_version": "random-mastery-qa-v18",
            "last_action": {"card": "arrows", "category": "spell", "phase": "confirmed"},
            "combat_profile": {"mode": "重型主攻 + 后排支援"},
            "decision_reason": "等待圣水恢复，观察对方进攻与可靠手牌识别后继续执行当前战术规则"}
    console.read_random_status = lambda: dict(live)
    events = [
        "2026-10-03 08:11:12 INFO 国服 1v1 连续对战已启动",
        "2026-10-03 08:12:13 INFO 对战开始 场次=801",
        "2026-10-03 08:14:15 INFO 对战结束 结果=胜利 已完成=801 出牌确认=23/24",
        "2026-10-03 08:14:16 WARNING QA提醒：等待底部状态识别",
    ]
    trace = [json.dumps({"event": "mastery_footer_checked", "footer_state": "none"})]
    console.tail_log = lambda path, max_lines=18: (events if path == console.BATTLE_LOG else trace)[-max_lines:]

    def start_spy(_window):
        actions["start"] += 1

    def stop_spy(_window):
        actions["stop"] += 1

    def forbidden_worker(*_args, **_kwargs):
        actions["worker"] += 1
        raise RuntimeError("A real robot worker must never run during console QA")

    console.ControlWindow._start = start_spy
    console.ControlWindow._stop = stop_spy
    console.ControlWindow._start_worker = staticmethod(forbidden_worker)
    console.ControlWindow._stop_worker = staticmethod(forbidden_worker)
    console.ControlWindow._open_result = lambda _window: result_calls.append("open")

    original_window = console.ttk.Window

    def transparent_window(*window_args, **window_kwargs):
        root = original_window(*window_args, **window_kwargs)
        root.attributes("-alpha", 0.0)
        return root

    console.ttk.Window = transparent_window

    def isolated_export(window, state):
        diagnostics = {"state": state, "scope": window.scope.get(),
                       "phase": window.hero_title.get(),
                       "metrics": {key: value.get() for key, value in window.metrics.items()},
                       "size": [window.root.winfo_width(), window.root.winfo_height()],
                       "hero_content_fits": window.hero_panel.body.winfo_reqheight() <= window.hero_panel.body.winfo_height(),
                       "metric_fits": {key: widget.winfo_reqwidth() <= widget.winfo_width()
                                       for key, widget in window.metric_values.items()}}
        (qa / "frontend-state.json").write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")

    console.ControlWindow._export_frontend_state = isolated_export
    from PIL import Image, ImageDraw

    frame_source = {"count": 0, "mode": "live"}
    real_live_view = console.LiveEmulatorView

    def injected_frame():
        if frame_source["mode"] == "offline":
            raise RuntimeError("QA simulated unavailable screenshot")
        frame_source["count"] += 1
        image = Image.new("RGB", (419, 633), "#123b30")
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 418, 70), fill="#234f42")
        draw.rectangle((0, 562, 418, 632), fill="#7c9476")
        draw.line((0, 315, 418, 315), fill="#f0d291", width=3)
        draw.text((20, 30), f"OFFLINE QA FRAME {frame_source['count']}", fill="white")
        return image

    def live_fixture(parent, **kwargs):
        return real_live_view(parent, **kwargs, capture=injected_frame)

    def reject_real_capture(_view):
        forbidden.append({"event": "real_capture", "target": "adb screencap"})
        raise RuntimeError("Real ADB capture is forbidden during offline QA")

    real_live_view._capture_png = reject_real_capture
    console.LiveEmulatorView = live_fixture
    window = None
    try:
        window = console.ControlWindow()
        window.root.title("QA · isolated console validation")
        window.root.geometry("1440x900+0+0")
        settle(window.root, 0.15)
        # Read the worker's real queue without waiting for scheduled UI ticks.
        deadline = time.monotonic() + 8
        while not window.history_snapshots and time.monotonic() < deadline:
            try:
                status, payload = window.history_events.get_nowait()
            except console.queue.Empty:
                settle(window.root, 0.03)
            else:
                if status != "ok":
                    raise RuntimeError(f"Isolated history reader failed: {payload}")
                window.history_snapshots = payload
                window._render_history()
        check("history worker supplied frozen snapshots", bool(window.history_snapshots))

        select_view = getattr(window, "_select_view", None)
        if not args.minimum_only:
            for name, scope in console.SCOPES.items():
                window.scope_combo.set(name)
                window.scope_combo.event_generate("<<ComboboxSelected>>")
                settle(window.root)
                observed = {key: variable.get() for key, variable in window.metrics.items()}
                expected = expected_metrics(console, frozen[scope], reward_totals)
                check(f"seven metrics in {name}", observed == expected, observed=observed, expected=expected)
                check(f"history rows in {name}", len(window.history_tree.get_children()) == len(frozen[scope]["records"]))
                check(f"version rows in {name}", len(window.version_tree.get_children()) == len(frozen[scope]["versions"]))

            window._render_rewards({"rewards": 112, "coins": 562000, "unknown_coin_items": 1})
            window._fit_metrics()
            settle(window.root)
            window._fit_metrics()
            settle(window.root)
            unknown_note = window.reward_coin_note
            note_parent = unknown_note.master
            note_left = unknown_note.winfo_rootx() - note_parent.winfo_rootx()
            note_top = unknown_note.winfo_rooty() - note_parent.winfo_rooty()
            note_fits = (note_left >= -2 and note_top >= -2
                         and note_left + unknown_note.winfo_width() <= note_parent.winfo_width() + 2
                         and note_top + unknown_note.winfo_height() <= note_parent.winfo_height() + 2
                         and unknown_note.winfo_reqwidth() <= unknown_note.winfo_width()
                         and unknown_note.winfo_reqheight() <= unknown_note.winfo_height())
            check("unknown coin quantity shows unclipped note and amount suffix",
                  unknown_note.winfo_manager() == "pack" and unknown_note.winfo_ismapped()
                  and unknown_note.cget("text") == "1 项金额待核实"
                  and window.metrics["coins"].get() == "562,000+" and note_fits,
                  text=unknown_note.cget("text"), coins=window.metrics["coins"].get(), note_fits=note_fits)
            window._render_rewards({"rewards": 112, "coins": 562000, "unknown_coin_items": 0})
            window._fit_metrics()
            settle(window.root)
            check("confirmed coin quantity hides uncertainty note",
                  unknown_note.winfo_manager() == "" and not unknown_note.winfo_ismapped()
                  and window.metrics["coins"].get() == "562,000")
            window._render_history()
            window._fit_metrics()
            settle(window.root)

            window.scope.set("随机卡组")
            window._render_history()
            select_view = getattr(window, "_select_view", None)
            check("sidebar view selector exists", callable(select_view))
            for index in range(3):
                if getattr(window, "nav_buttons", None):
                    window.nav_buttons[index].invoke()
                elif select_view:
                    select_view(index)
                else:
                    window.notebook.select(index)
                settle(window.root)
                check(f"sidebar selects pane {index}", window.notebook.index(window.notebook.select()) == index)
                if getattr(window, "nav_buttons", None):
                    check(f"sidebar marks pane {index} as selected",
                          [button._selected for button in window.nav_buttons] == [position == index for position in range(3)])
            if select_view:
                select_view(0)
            else:
                window.notebook.select(0)
            settle(window.root)

            rows = window.history_tree.get_children()
            if rows:
                row = rows[min(3, len(rows) - 1)]
                window.history_tree.selection_set(row)
                window.history_tree.yview_moveto(0.30)
                settle(window.root)
                before = window.history_tree.yview()
                window.history_key = None  # Exercise actual row rebuild, not cached early return.
                window._render_history()
                settle(window.root)
                after = window.history_tree.yview()
                check("history selection retained on rebuild", window.history_tree.selection() == (row,))
                check("history scroll retained on rebuild", abs(before[0] - after[0]) < 0.035, before=before, after=after)
                window.history_tree.selection_remove(*window.history_tree.selection())
                settle(window.root)
                check("result button disabled without selected row", is_disabled(window.open_result_button))
                window.history_tree.selection_set(row)
                settle(window.root)
                check("result button enabled for selected row", not is_disabled(window.open_result_button))
                window.open_result_button.invoke()
                check("result button invokes result viewer callback", result_calls == ["open"])

                if hasattr(window.history_tree, "_badge_pool"):
                    window.history_tree.yview_moveto(0)
                    window.history_tree.selection_remove(*window.history_tree.selection())
                    settle(window.root)
                    window.history_tree.refresh_badges()
                    badges = [badge for badge in window.history_tree._badge_pool if badge.winfo_ismapped()]
                    check("visible history result badges exist", bool(badges))
                    if badges:
                        badge = badges[0]
                        window.history_tree._select_badge(badge)
                        settle(window.root)
                        check("badge click selects matching result row",
                              window.history_tree.selection() == (badge._row_id,))
                        check("badge selection refreshes row background", badge.cget("bg") == "#edf3ed",
                              observed=badge.cget("bg"), expected="#edf3ed")
                        window.history_tree._select_badge(badge, open_result=True)
                        settle(window.root)
                        check("badge double activation opens selected result", result_calls == ["open", "open"])
                        before_wheel = window.history_tree.yview()
                        badge.event_generate("<MouseWheel>", delta=-120)
                        settle(window.root)
                        after_badge_wheel = window.history_tree.yview()
                        window.history_tree.event_generate("<MouseWheel>", delta=-120)
                        settle(window.root)
                        after_tree_wheel = window.history_tree.yview()
                        check("result badge forwards wheel scrolling",
                              after_badge_wheel[0] > before_wheel[0],
                              before=before_wheel, badge_after=after_badge_wheel,
                              tree_after=after_tree_wheel)
            else:
                check("history has rows for selection verification", False)

            for state in ("running", "starting", "stopped", "paused"):
                simulated["state"] = state
                window._refresh()
                settle(window.root)
                expected_start = state in {"stopped", "paused"}
                expected_stop = state in {"running", "starting"}
                check(f"button enabled states for {state}",
                      (not is_disabled(window.start_button)) == expected_start
                      and (not is_disabled(window.stop_button)) == expected_stop)
            simulated["state"] = "stopped"
            window._refresh()
            window.start_button.invoke()
            simulated["state"] = "running"
            window._refresh()
            window.stop_button.invoke()
            check("button command wiring uses expected actions", actions == {"start": 1, "stop": 1, "worker": 0}, calls=dict(actions))
            for busy in ("start", "stop"):
                window.busy = busy
                window._refresh()
                check(f"buttons disabled while {busy} busy", is_disabled(window.start_button) and is_disabled(window.stop_button))
            window.busy = None

            if select_view:
                select_view(2)
            else:
                window.notebook.select(2)
            window.raw_log.set(True)
            window._refresh()
            raw = window.log_text.get("1.0", "end-1c")
            check("raw log preserves fixture event lines", raw == "\n".join(events), observed=raw)
            window.raw_log.set(False)
            window._refresh()
            readable = window.log_text.get("1.0", "end-1c")
            check("readable event log renders event details", "第 801 场" in readable and "INFO" not in readable, observed=readable)
            window.auto_scroll.set(False)
            window.log_text.yview_moveto(0.0)
            window._refresh()
            check("automatic scroll can be disabled", not window.auto_scroll.get())

            # Cover mirror controls with injected frames before the layout matrix.
            view = window.live_view
            deadline = time.monotonic() + 3
            while view.diagnostics()["state"] != "live" and time.monotonic() < deadline:
                settle(window.root, 0.05)
            check("offline fixture supplies live portrait frame",
                  view.diagnostics()["state"] == "live"
                  and view.diagnostics()["frame_size"] == (419, 633),
                  diagnostics=view.diagnostics())
            view.pause_button.invoke()
            settle(window.root, 0.15)
            paused_count = view.diagnostics()["frame_count"]
            captured_count = frame_source["count"]
            settle(window.root, 0.60)
            check("pause button stops mirror reads and preserves bot state",
                  view.diagnostics()["state"] == "paused"
                  and view.diagnostics()["frame_count"] == paused_count
                  and frame_source["count"] == captured_count
                  and actions == {"start": 1, "stop": 1, "worker": 0},
                  diagnostics=view.diagnostics(), calls=dict(actions))
            view.pause_button.invoke()
            deadline = time.monotonic() + 3
            while view.diagnostics()["frame_count"] <= paused_count and time.monotonic() < deadline:
                settle(window.root, 0.05)
            check("resume button restores mirror frames",
                  view.diagnostics()["state"] == "live"
                  and view.diagnostics()["frame_count"] > paused_count,
                  diagnostics=view.diagnostics())
            frame_source["mode"] = "offline"
            view.reconnect_button.invoke()
            deadline = time.monotonic() + 3
            while view.diagnostics()["state"] != "offline" and time.monotonic() < deadline:
                settle(window.root, 0.05)
            check("unavailable capture displays offline state without stale image",
                  view.diagnostics()["state"] == "offline"
                  and view._photo is None and view._last_image is None,
                  diagnostics=view.diagnostics())
            frame_source["mode"] = "live"
            view.reconnect_button.invoke()
            deadline = time.monotonic() + 3
            while view.diagnostics()["state"] != "live" and time.monotonic() < deadline:
                settle(window.root, 0.05)
            check("reconnect restores mirror without robot actions",
                  view.diagnostics()["state"] == "live"
                  and actions == {"start": 1, "stop": 1, "worker": 0},
                  diagnostics=view.diagnostics(), calls=dict(actions))
            check("capture queue remains bounded", view.diagnostics()["queue_size"] <= 1)

        sizes = [("1240x800", (1240, 800)), ("1280x820", (1280, 820)), ("1440x900", (1440, 900)),
                 ("1660x940", (1660, 940)), ("maximized", None)]
        if args.minimum_only:
            sizes = sizes[:1]
        report["screen_size"] = [window.root.winfo_screenwidth(), window.root.winfo_screenheight()]
        for requested, geometry in sizes:
            if geometry:
                cap_width = max(1240, min(geometry[0], report["screen_size"][0] - 32))
                cap_height = max(800, min(geometry[1], report["screen_size"][1] - 80))
                window.root.state("normal")
                window.root.geometry(f"{cap_width}x{cap_height}+0+0")
            else:
                window.root.state("zoomed")
            settle(window.root, 0.12)
            window._refresh()
            settle(window.root)
            if hasattr(window, "_fit_metrics"):
                window._fit_metrics()
                settle(window.root)
            metrics_fit = {key: widget.winfo_reqwidth() <= widget.winfo_width()
                           for key, widget in window.metric_values.items()}
            layout = {"requested": requested, "actual": [window.root.winfo_width(), window.root.winfo_height()],
                      "metrics_fit": metrics_fit,
                      "hero_content_fits": window.hero_panel.body.winfo_reqheight() <= window.hero_panel.body.winfo_height(),
                      "views": []}
            for pane in range(3):
                if select_view:
                    select_view(pane)
                else:
                    window.notebook.select(pane)
                settle(window.root)
                overflow = visible_bounds(window.root)
                layout["views"].append({"pane": pane, "client_overflow": overflow})
                check(f"visible client bounds at {requested}, pane {pane}", not overflow, overflow=overflow)
                if pane == 0:
                    check(f"history source note visible at {requested}", window.history_source_label.winfo_ismapped()
                          and window.history_source_label.winfo_height() >= window.history_source_label.winfo_reqheight())
                    if requested == "1440x900":
                        report["dimensions_1440x900"] = layout_dimensions(window)
                        print(json.dumps({"dimensions_1440x900": report["dimensions_1440x900"]}, ensure_ascii=False))
            page_rectangle = widget_rectangle(window.root, window.page)
            live_rectangle = widget_rectangle(window.root, window.live_panel)
            layout.update(page_rectangle=page_rectangle, live_rectangle=live_rectangle,
                          live_canvas=widget_rectangle(window.root, window.live_view.canvas),
                          footer=widget_rectangle(window.root, window.footer),
                          mirror_diagnostics=window.live_view.diagnostics())
            check(f"statistics left and mirror right do not overlap at {requested}",
                  page_rectangle[2] <= live_rectangle[0] and page_rectangle[1] == live_rectangle[1],
                  page=page_rectangle, mirror=live_rectangle)
            check(f"whole mirror and footer are visible at {requested}",
                  all(widget.winfo_ismapped() and widget.winfo_width() > 1 and widget.winfo_height() > 1
                      for widget in (window.live_panel, window.live_view, window.live_view.canvas,
                                     window.live_view.pause_button, window.live_view.reconnect_button,
                                     window.footer)),
                  live_canvas=layout["live_canvas"], footer=layout["footer"])
            clipped_labels = label_overflow(window.page) + label_overflow(window.live_view)
            layout["clipped_labels"] = clipped_labels
            check(f"statistics and mirror labels fit at {requested}", not clipped_labels,
                  clipped_labels=clipped_labels)
            image_items = [item for item in window.live_view.canvas.find_all()
                           if window.live_view.canvas.type(item) == "image"]
            image_bounds = window.live_view.canvas.bbox(image_items[0]) if image_items else None
            canvas_width = window.live_view.canvas.winfo_width()
            canvas_height = window.live_view.canvas.winfo_height()
            check(f"complete portrait frame fits mirror canvas at {requested}",
                  bool(image_bounds) and image_bounds[0] >= -1 and image_bounds[1] >= -1
                  and image_bounds[2] <= canvas_width + 1 and image_bounds[3] <= canvas_height + 1,
                  image_bounds=image_bounds, canvas_size=[canvas_width, canvas_height])
            check(f"metric text fits at {requested}", all(metrics_fit.values()), observed=metrics_fit)
            check(f"hero content fits at {requested}", layout["hero_content_fits"])
            report["layout"].append(layout)
        check("production writes and external actions were not attempted", not forbidden)
        expected_actions = {"start": 0, "stop": 0, "worker": 0} if args.minimum_only else {"start": 1, "stop": 1, "worker": 0}
        close_calls = []
        view = window.live_view
        original_close = view.close

        def observed_close():
            close_calls.append("close")
            original_close()

        window.live_view.close = observed_close
        window._on_close()
        deadline = time.monotonic() + 1
        while view.diagnostics()["capture_thread_alive"] and time.monotonic() < deadline:
            time.sleep(0.01)
        check("window close cancels mirror capture and leaves robot actions unchanged",
              bool(close_calls) and view.diagnostics()["closed"]
              and not view.diagnostics()["capture_thread_alive"]
              and actions == expected_actions,
              diagnostics=view.diagnostics(), calls=dict(actions), close_calls=close_calls)
        window = None
    except Exception as error:
        report["exception"] = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
        check("QA completed without exception", False)
    finally:
        if window is not None:
            try:
                window.history_stop.set()
                window.live_view.close()
                window.root.destroy()
            except Exception as error:
                report["cleanup_error"] = str(error)
        report["passed"] = bool(report["checks"]) and all(item["passed"] for item in report["checks"])
        report["passed_count"] = sum(item["passed"] for item in report["checks"])
        report["check_count"] = len(report["checks"])
        (qa / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"passed": report["passed"], "checks": report["check_count"],
                          "passed_count": report["passed_count"],
                          "failures": [item["name"] for item in report["checks"] if not item["passed"]],
                          "report": str(qa / "validation.json"),
                          "exception": report.get("exception", {}).get("message")}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
