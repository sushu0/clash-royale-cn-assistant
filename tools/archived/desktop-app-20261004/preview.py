"""A bounded UI preview which never sends game input or attaches its window."""
import sys
from pathlib import Path
from functools import partial

task_root = Path(r"D:\codex\CodexWork\clash")
sys.path.insert(0, str(task_root / "py-clash-bot"))
sys.stderr = (task_root / "work" / "desktop-app-20261004" / "preview-error.log").open("w", encoding="utf-8")
from scripts import cn_bot_control as app

app.bot_state = lambda: "stopped"
app.NativeEmulatorView = partial(app.NativeEmulatorView, autostart=False)
window = app.ControlWindow()
window.root.title("皇室战争助手 · 界面验证")
window._start = lambda: None
window._stop = lambda: None
window.root.after(45000, window._destroy_window)
window.run()
