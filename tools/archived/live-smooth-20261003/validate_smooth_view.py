"""Measure native Tk display cadence and lifecycle using an isolated injected source.

Only this script's QA directory is writable. Device and robot operations are
blocked with an audit hook. The source is deterministic PIL data, and the actual
PhotoImage pixel handed to the canvas is inspected after every Tk event pump.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
import time
import traceback
from pathlib import Path

TASK = Path(r"D:\codex\CodexWork\clash")
REPO = TASK / "py-clash-bot"
RUN = TASK / "work" / "live-smooth-20261003"
sys.path.insert(0, str(REPO))
sys.dont_write_bytecode = True


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1)] if ordered else None


def install_guard(output, blocked):
    allowed = output.resolve()

    def inside(value):
        return not isinstance(value, (str, bytes, os.PathLike)) or Path(os.fsdecode(value)).resolve().is_relative_to(allowed)

    def audit(event, args):
        forbidden = False
        if event == "open":
            mode, flags = args[1:3]
            writing = (isinstance(mode, str) and any(char in mode for char in "wax+")) or (
                isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)))
            forbidden = writing and not inside(args[0])
        elif event in {"os.mkdir", "os.chmod", "os.utime"}:
            forbidden = not inside(args[0])
        elif event in {"os.rename", "os.replace"}:
            forbidden = not inside(args[0]) or not inside(args[1])
        elif event in {"subprocess.Popen", "os.system", "os.startfile", "os.startfile/2", "socket.connect", "socket.bind",
                       "socket.getaddrinfo", "os.remove", "os.rmdir", "sqlite3.connect"}:
            forbidden = True
        if forbidden:
            blocked.append({"event": event, "target": str(args[0]) if args else ""})
            raise RuntimeError(f"QA blocked {event}")

    sys.addaudithook(audit)


class SyntheticSource:
    def __init__(self, image_module):
        self.image_module = image_module
        self.lock = threading.Lock()
        self.count = 0
        self.mode = "live"
        self.times = {}
        self.block_next = False
        self.blocked_sequence = None
        self.entered = threading.Event()
        self.release = threading.Event()

    @staticmethod
    def color(sequence):
        return (sequence % 250 + 1, sequence // 250 % 250 + 1, 27)

    @staticmethod
    def sequence(color):
        return (int(color[0]) - 1) + (int(color[1]) - 1) * 250

    def __call__(self):
        with self.lock:
            self.count += 1
            sequence = self.count
            mode = self.mode
            block = self.block_next
            if block:
                self.block_next = False
                self.blocked_sequence = sequence
            self.times[sequence] = time.monotonic()
        if block:
            self.entered.set()
            if not self.release.wait(10):
                raise RuntimeError("QA blocked capture exceeded its bound")
        if mode == "offline":
            raise RuntimeError("QA intentionally disconnected injected source")
        time.sleep(0.003)
        return self.image_module.new("RGB", (419, 633), self.color(sequence))

    def block_once(self):
        self.entered.clear()
        self.release.clear()
        with self.lock:
            self.block_next = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=RUN / "qa")
    parser.add_argument("--minimum-display-fps", type=float, default=20.0)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(RUN.resolve()):
        raise ValueError("QA output must stay inside this task run")
    output.mkdir(parents=True, exist_ok=True)
    forbidden = []
    install_guard(output, forbidden)
    from PIL import Image
    import ttkbootstrap as ttk
    from pyclashbot.interface import cn_live_view as live_module

    source = SyntheticSource(Image)
    root = None
    view = None
    report = {"checks": [], "forbidden_operations": forbidden, "scope": "injected source; no robot/device operations",
              "display_measurement": "unique source pixels observed from canvas PhotoImage after Tk event processing",
              "limits": "offline Tk submission/paint cadence; external compositor and real capture source require separate live QA"}

    def check(name, condition, **details):
        report["checks"].append({"name": name, "passed": bool(condition), **details})

    displayed = []
    seen_sequence = None
    heartbeat = []

    def sample_photo():
        nonlocal seen_sequence
        if view._state != "live" or view._photo is None:
            return
        items = [item for item in view.canvas.find_all() if view.canvas.type(item) == "image"]
        if not items:
            return
        photo_name = str(view.canvas.itemcget(items[0], "image"))
        if not photo_name:
            return
        color = root.tk.call(photo_name, "get", 0, 0)
        if isinstance(color, str):
            color = root.tk.splitlist(color)
        if len(color) != 3 or int(color[2]) != 27:
            return
        sequence = source.sequence(color)
        if sequence == seen_sequence:
            return
        seen_sequence = sequence
        now = time.monotonic()
        with source.lock:
            captured_at = source.times.get(sequence)
            source_count = source.count
        displayed.append({"sequence": sequence, "at": now, "capture_at": captured_at,
                          "capture_to_canvas_seconds": now - captured_at if captured_at is not None else None,
                          "source_count": source_count})

    def pump(duration):
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            root.update()
            sample_photo()
            time.sleep(0.001)

    def wait_for(predicate, timeout=2):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            pump(0.015)
        return bool(predicate())

    def beat():
        heartbeat.append(time.monotonic())
        root.after(10, beat)

    try:
        root = ttk.Window(themename="litera")
        root.attributes("-alpha", 0.0)
        root.geometry("420x800+0+0")
        view = live_module.LiveEmulatorView(root, adb_path=RUN / "must-not-run-adb.exe", serial="OFFLINE-QA",
                                            cwd=RUN, capture=source)
        view.pack(fill="both", expand=True, padx=12, pady=12)
        root.after(10, beat)
        check("injected source reaches live", wait_for(lambda: view.diagnostics()["state"] == "live"),
              diagnostics=view.diagnostics())
        pump(0.2)
        displayed.clear()
        heartbeat.clear()
        start = time.monotonic()
        source_start_count = source.count
        pump(2.0)
        elapsed = time.monotonic() - start
        frames = list(displayed)
        display_fps = len(frames) / elapsed
        capture_fps = (source.count - source_start_count) / elapsed
        frame_intervals = [b["at"] - a["at"] for a, b in zip(frames, frames[1:])]
        timer_intervals = [b - a for a, b in zip(heartbeat, heartbeat[1:])]
        latencies = [item["capture_to_canvas_seconds"] for item in frames if item["capture_to_canvas_seconds"] is not None]
        report["performance"] = {"seconds": elapsed, "displayed_count": len(frames), "actual_display_fps": display_fps,
                                 "source_capture_fps": capture_fps, "diagnostics": view.diagnostics(),
                                 "display_interval_p95_ms": percentile(frame_intervals, 0.95) * 1000 if frame_intervals else None,
                                 "capture_to_canvas_p95_ms": percentile(latencies, 0.95) * 1000 if latencies else None,
                                 "timer_interval_p95_ms": percentile(timer_intervals, 0.95) * 1000 if timer_intervals else None,
                                 "timer_interval_max_ms": max(timer_intervals) * 1000 if timer_intervals else None}
        check("actual canvas display reaches useful cadence", display_fps >= args.minimum_display_fps,
              observed_fps=display_fps, required_fps=args.minimum_display_fps)
        check("capture-to-canvas latency stays bounded", bool(latencies) and percentile(latencies, 0.95) < 0.15,
              p95_seconds=percentile(latencies, 0.95))
        check("10ms Tk timer remains responsive while video refreshes",
              bool(timer_intervals) and percentile(timer_intervals, 0.95) < 0.05 and max(timer_intervals) < 0.15,
              p95_seconds=percentile(timer_intervals, 0.95), max_seconds=max(timer_intervals, default=None))
        check("frame canvas content is actually updated", len({item["sequence"] for item in frames}) >= 40)

        # Give the producer a deliberate UI gap; it must retain only the latest.
        before_gap = source.count
        time.sleep(0.25)
        with view._results.mutex:
            queued = list(view._results.queue)
        newest_age = time.monotonic() - queued[-1].captured_at if queued else None
        check("producer queue holds one recent frame while UI is delayed",
              view._results.maxsize == 1 and len(queued) <= 1 and source.count - before_gap >= 4
              and newest_age is not None and newest_age < 0.1,
              queue_size=len(queued), newest_age_seconds=newest_age, gap_captures=source.count - before_gap)
        pump(0.075)
        check("UI resumes with recent source content rather than a backlog",
              displayed and displayed[-1]["source_count"] - displayed[-1]["sequence"] <= 3,
              last_display=displayed[-1] if displayed else None)

        view.pause()
        pump(0.12)
        paused_source_count = source.count
        paused_display_count = len(displayed)
        pump(0.3)
        check("pause stops capture and displayed frames",
              source.count == paused_source_count and len(displayed) == paused_display_count
              and view.diagnostics()["state"] == "paused", diagnostics=view.diagnostics())
        view.resume()
        check("resume restores fresh display", wait_for(lambda: len(displayed) > paused_display_count),
              diagnostics=view.diagnostics())

        source.block_once()
        check("generation test has an in-flight capture", wait_for(source.entered.is_set))
        invalid_sequence = source.blocked_sequence
        view.reconnect()
        source.release.set()
        check("reconnect restores frames after generation change", wait_for(lambda: view.diagnostics()["state"] == "live"))
        pump(0.1)
        check("in-flight frame from prior generation never reaches canvas",
              invalid_sequence not in {item["sequence"] for item in displayed}, invalid_sequence=invalid_sequence)

        source.mode = "offline"
        view.reconnect()
        check("source failure becomes offline", wait_for(lambda: view.diagnostics()["state"] == "offline"),
              diagnostics=view.diagnostics())
        check("source failure clears old image instead of claiming live",
              view._last_image is None and view._photo is None and view.diagnostics()["state"] == "offline"
              and view.diagnostics().get("fps", 0) == 0, diagnostics=view.diagnostics())
        source.mode = "live"
        view.reconnect()
        check("reconnect recovers after disconnect", wait_for(lambda: view.diagnostics()["state"] == "live"),
              diagnostics=view.diagnostics())

        # A blocked source is distinguishable from an explicit source error.
        source.block_once()
        check("stale test has a blocked capture", wait_for(source.entered.is_set))
        stale_after = getattr(live_module, "STALE_AFTER", 2.5)
        check("missing frames visibly become stale",
              wait_for(lambda: view.diagnostics()["state"] == "stale", stale_after + 0.7),
              diagnostics=view.diagnostics(), status_label=view._status_label.cget("text"))
        source.release.set()
        check("stale source recovers once frames return", wait_for(lambda: view.diagnostics()["state"] == "live"))

        view.close()
        check("close marks closed state and cancels poll callback",
              view.diagnostics()["closed"] and view._after_id is None, diagnostics=view.diagnostics())
        check("close leaves no capture thread", wait_for(lambda: not view.diagnostics()["capture_thread_alive"], 1.0),
              diagnostics=view.diagnostics())
        report["final_diagnostics"] = view.diagnostics()
        check("no robot/device/external operations attempted", not forbidden)
    except Exception as error:
        report["exception"] = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
        check("QA completes without exception", False)
    finally:
        source.release.set()
        if view is not None:
            view.close()
        if root is not None:
            root.destroy()
        report["passed_count"] = sum(item["passed"] for item in report["checks"])
        report["check_count"] = len(report["checks"])
        report["passed"] = bool(report["checks"]) and all(item["passed"] for item in report["checks"])
        (output / "smooth-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"passed": report["passed"], "checks": report["check_count"], "passed_count": report["passed_count"],
                          "performance": report.get("performance"),
                          "failures": [item["name"] for item in report["checks"] if not item["passed"]],
                          "exception": report.get("exception", {}).get("message"),
                          "report": str(output / "smooth-validation.json")}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
