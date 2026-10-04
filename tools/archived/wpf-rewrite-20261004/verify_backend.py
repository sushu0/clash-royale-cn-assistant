"""Read-only JSONL and no-window acceptance of source and frozen bridge."""

import ctypes
import hashlib
import json
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "py-clash-bot"))
from pyclashbot.utils.persistence import atomic_write_bytes, atomic_write_json


def owned_windows(pid):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    handles = []

    def collect(hwnd, _parameter):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            handles.append(int(hwnd))
        return True

    user32.EnumWindows(callback_type(collect), 0)
    return handles


pid_path = ROOT / "work" / "bot-processes.json"
before_pids = json.loads(pid_path.read_text(encoding="utf-8"))
report_paths = [path for path in (ROOT / "outputs" / "error-reports").glob("*/report.*") if path.is_file()]
before_reports = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in report_paths}
commands = [
    ("source", [str(ROOT / "work" / "venv" / "Scripts" / "python.exe"), str(ROOT / "py-clash-bot" / "scripts" / "cn_wpf_backend.py")]),
    ("frozen", [str(ROOT / "outputs" / "wpf-desktop-20261004" / "backend" / "ClashBackend.exe")]),
]
results = []
for label, command in commands:
    child = subprocess.Popen(command + ["--data-root", str(ROOT), "--read-only"], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    time.sleep(1)
    handles = owned_windows(child.pid)
    requested = [{"id": f"{label}-{name}", "command": name} for name in ("snapshot", "reports", "shutdown")]
    stdout, stderr = child.communicate("\n".join(json.dumps(row) for row in requested) + "\n", timeout=30)
    atomic_write_bytes(WORK / f"{label}-responses.jsonl", stdout.encode("utf-8"))
    atomic_write_bytes(WORK / f"{label}-stderr.log", stderr.encode("utf-8"))
    responses = [json.loads(line) for line in stdout.splitlines()]
    assert len(responses) == 3 and all(row["ok"] for row in responses), (label, stderr, responses)
    snapshot = responses[0]["data"]
    assert {"state", "selected_strategy", "live", "scopes", "reward_totals", "reports", "recent_events", "runtime", "updated_at"} <= set(snapshot)
    assert set(snapshot["scopes"]) == {"random", "567", "hog", "all"}
    assert responses[2]["data"]["shutdown"] is True
    results.append({"label": label, "pid": child.pid, "exit_code": child.returncode, "top_level_window_handles": handles, "no_windows": not handles, "state": snapshot["state"], "selected_strategy": snapshot["selected_strategy"], "live_session": snapshot["live"].get("session"), "live_state": snapshot["live"].get("state"), "history_total": snapshot["scopes"]["random"]["total"], "rewards": snapshot["reward_totals"], "report_count": len(snapshot["reports"]), "frozen": snapshot["frozen"], "runtime": snapshot["runtime"], "stdout_jsonl_only": True, "requested_commands": requested, "stderr": stderr})
after_pids = json.loads(pid_path.read_text(encoding="utf-8"))
after_reports = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in report_paths}
exe = ROOT / "outputs" / "wpf-desktop-20261004" / "backend" / "ClashBackend.exe"
result = {"passed": all(row["exit_code"] == 0 and row["no_windows"] for row in results) and before_pids == after_pids and before_reports == after_reports, "bot_process_record_unchanged": before_pids == after_pids, "existing_reports_unchanged": before_reports == after_reports, "bot_start_or_stop_requested": False, "exe": str(exe), "exe_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(), "results": results}
atomic_write_json(WORK / "backend-verification.json", result)
print(json.dumps(result, ensure_ascii=False))
