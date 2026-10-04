"""Controlled pause acceptance; never mutates production state or game input."""
import json
import sys
import time
from pathlib import Path
from functools import partial

task_root = Path(r"D:\codex\CodexWork\clash")
case = task_root / "work" / "desktop-app-20261004" / "pause-selftest"
case_outputs = case / "outputs"
case_work = case / "work"
case_outputs.mkdir(parents=True, exist_ok=True)
case_work.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(task_root / "py-clash-bot"))
sys.stderr = (case / "ui-error.log").open("w", encoding="utf-8")
from scripts import cn_bot_control as app

for name in ("BATTLE_LOG", "WATCHDOG_LOG", "RANDOM_TRACE"):
    original = getattr(app, name)
    copy = case_outputs / original.name
    copy.write_text("\n".join(app.tail_log(original, 120)), encoding="utf-8")
    setattr(app, name, copy)
app.OUTPUTS = case_outputs
app.PID_FILE = case_work / "bot-processes.json"
app.RANDOM_STATUS = case_outputs / "random-mastery-live-status.json"
app.FRONTEND_STATE = case_outputs / "ui-state.json"
app.PID_FILE.write_text(json.dumps({"phase": "paused", "session": "desktop-acceptance", "strategy": "random", "reason": "功能验收故障（非实际机器人异常）：验证暂停时自动截图和错误报告。"}, ensure_ascii=False), encoding="utf-8")
app.RANDOM_STATUS.write_text(json.dumps({"state": "paused", "session": "desktop-acceptance", "validation_only": True, "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False), encoding="utf-8")
app.bot_state = lambda: "paused"
app.selected_strategy = lambda: "random"
app.NativeEmulatorView = partial(app.NativeEmulatorView, autostart=False)
app.ControlWindow._start = lambda self: None
app.ControlWindow._stop = lambda self: None
window = app.ControlWindow()
window.root.title("皇室战争助手 · 暂停报告验收")
window._select_view(3)
window.root.after(45000, window._destroy_window)
window.run()
