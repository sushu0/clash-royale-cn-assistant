"""Render live readouts with an isolated index and harmless action callbacks."""

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

TASK = Path(r"D:\codex\CodexWork\clash")
REPO = TASK / "py-clash-bot"
PREVIEW = TASK / "work" / "ui-redesign-20261003" / "preview"
PREVIEW.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(REPO))
spec = importlib.util.spec_from_file_location("console_preview", REPO / "scripts" / "cn_bot_control.py")
console = importlib.util.module_from_spec(spec)
spec.loader.exec_module(console)
with sqlite3.connect(console.HISTORY_DB.resolve().as_uri() + "?mode=ro", uri=True) as original:
    with sqlite3.connect(PREVIEW / "history.sqlite3") as isolated:
        original.backup(isolated)
console.HISTORY_DB = PREVIEW / "history.sqlite3"
console.FRONTEND_STATE = PREVIEW / "frontend-state.json"
console.ControlWindow._start = lambda self: self.notice.set("预览已确认启动按钮响应；后台机器人保持当前运行。")
console.ControlWindow._stop = lambda self: self.notice.set("预览已确认停止按钮响应；后台机器人保持当前运行。")
window = console.ControlWindow()
window.root.title("皇室战争 · 新版界面预览")
(PREVIEW / "process.json").write_text(json.dumps({"pid": __import__("os").getpid()}), encoding="utf-8")
window.run()
