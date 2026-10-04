"""Bounded history UI verification without touching the live game or bot."""
import sys
from functools import partial
from pathlib import Path

root = Path(r"D:\codex\CodexWork\clash")
work = root / "work" / "error-history-20261004"
sys.path.insert(0, str(root / "py-clash-bot"))
sys.stderr = (work / "preview-error.log").open("w", encoding="utf-8")
from scripts import cn_bot_control as app

app.NativeEmulatorView = partial(app.NativeEmulatorView, autostart=False)
app.FRONTEND_STATE = work / "preview-state.json"
app.ControlWindow._start_worker = staticmethod(lambda: "preview only")
app.ControlWindow._stop_worker = staticmethod(lambda: "preview only")
window = app.ControlWindow()
window.root.title("皇室战争助手 · 历史预览")
window._select_view(3)
window.root.after(45000, window._destroy_window)
window.run()
