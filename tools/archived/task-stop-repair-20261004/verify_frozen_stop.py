"""Exercise packaged cancellation with a blocking local fake tool, never a game."""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

import psutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--fake-tool", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    task = args.work.resolve()
    task.mkdir(parents=True, exist_ok=True)
    root = task / ("isolated-" + str(time.time_ns()))
    (root / "work").mkdir(parents=True)
    marker = root / "startup-waiting.txt"
    (root / "work/runtime-config.json").write_text(
        json.dumps({"adb": str(args.fake_tool), "memuc": str(args.fake_tool), "serial": "offline-test"}),
        encoding="utf-8",
    )
    (root / "work/bot-selected-strategy.txt").write_text("random", encoding="utf-8")
    env = dict(os.environ)
    env.update(PYCLASHBOT_DATA_ROOT=str(root), CLASH_FAKE_TOOL_MARKER=str(marker))
    responses = queue.Queue()
    diagnostics = task / "frozen-stderr.log"
    with diagnostics.open("w", encoding="utf-8") as errors:
        process = subprocess.Popen(
            [str(args.backend), "--data-root", str(root)], cwd=args.backend.parent,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors, text=True,
            encoding="utf-8", env=env, creationflags=subprocess.CREATE_NO_WINDOW,
        )

        def read():
            for line in process.stdout:
                responses.put(json.loads(line))

        worker = threading.Thread(target=read, daemon=True)
        worker.start()
        received = {}

        def send(identity, command):
            process.stdin.write(json.dumps({"id": identity, "command": command}) + "\n")
            process.stdin.flush()

        def receive(identity, timeout=12):
            deadline = time.monotonic() + timeout
            while identity not in received:
                received_row = responses.get(timeout=max(0.001, deadline - time.monotonic()))
                received[received_row["id"]] = received_row
            return received[identity]

        try:
            send("before", "snapshot")
            before = receive("before")
            assert before["ok"] and before["data"]["runtime"]["data_root"] == str(root)
            send("start", "start")
            deadline = time.monotonic() + 10
            while not marker.is_file() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert marker.is_file(), "Frozen startup did not reach the fake blocking ADB command"
            requested = time.monotonic()
            send("stop", "stop")
            stopped = receive("stop", timeout=5)
            stop_seconds = time.monotonic() - requested
            assert stopped["ok"] and stopped["data"]["state"] == "stopped", stopped
            assert stop_seconds < 3, stop_seconds
            cancelled = receive("start", timeout=5)
            assert not cancelled["ok"] and "取消" in cancelled["error"], cancelled
            send("after", "snapshot")
            after = receive("after")
            assert after["ok"] and after["data"]["state"] == "stopped"
            assert after["data"]["busy"] is None
            children = psutil.Process(process.pid).children(recursive=True)
            child_records = []
            console_hosts = []
            system_console = Path(os.environ["WINDIR"]) / "System32/conhost.exe"
            for child in children:
                try:
                    row = child.as_dict(attrs=["pid", "name", "exe", "cmdline", "status"])
                    if Path(row["exe"]).resolve() == system_console.resolve():
                        # CREATE_NO_WINDOW's invisible console host lives with
                        # the bridge; it is not an active bot or startup tool.
                        console_hosts.append(row)
                    else:
                        child_records.append(row)
                except psutil.NoSuchProcess:
                    continue
            if child_records:
                (task / "remaining-children.json").write_text(
                    json.dumps({"children": child_records, "responses": received}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            assert not child_records, child_records
            stop_record = json.loads((root / "work/bot-processes.json").read_text(encoding="utf-8"))
            assert stop_record["exit_reason"] == "user_stopped"
            assert (root / "work/bot-processes.stop.json").is_file()
            send("stop-again", "stop")
            again = receive("stop-again")
            assert again["ok"] and again["data"]["state"] == "stopped"
            send("shutdown", "shutdown")
            assert receive("shutdown")["ok"]
            process.wait(timeout=8)
            assert process.returncode == 0
            record = {
                "status": "PASS", "kind": "isolated_packaged_backend_with_blocking_fake_tool",
                "backend": str(args.backend), "fake_tool": str(args.fake_tool), "isolated_data_root": str(root),
                "stop_response_seconds": stop_seconds, "start_cancelled": True,
                "no_remaining_bot_or_startup_tool_processes": True, "stop_is_idempotent": True,
                "expected_hidden_windows_console_hosts": console_hosts,
                "durable_stop_barrier": True, "real_game_or_emulator_used": False,
                "responses": received,
            }
            target = task / "frozen-stop-acceptance.json"
            target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"status": "PASS", "stop_response_seconds": stop_seconds, "report": str(target)}))
        finally:
            if process.poll() is None:
                for child in psutil.Process(process.pid).children(recursive=True):
                    child.kill()
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
