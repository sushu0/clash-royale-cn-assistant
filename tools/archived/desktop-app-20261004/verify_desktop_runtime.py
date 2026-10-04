"""Read-only OS evidence for the running desktop window and notification icon."""
import ctypes
import json
from ctypes import wintypes
from pathlib import Path

ROOT = Path(r"D:\codex\CodexWork\clash")
ui = json.loads((ROOT / "work" / "random-frontend-state.json").read_text(encoding="utf-8"))
shell = ui["desktop_shell"]
user = ctypes.WinDLL("user32", use_last_error=True)
user.IsWindowVisible.argtypes = [wintypes.HWND]
user.IsWindowVisible.restype = wintypes.BOOL
user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user.SendMessageW.restype = ctypes.c_ssize_t

class GUID(ctypes.Structure):
    _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]

class NOTIFYICONIDENTIFIER(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT), ("guidItem", GUID)]

identity = NOTIFYICONIDENTIFIER()
identity.cbSize = ctypes.sizeof(identity)
identity.hWnd = shell["tray_hwnd"]
identity.uID = 1
rect = wintypes.RECT()
query = ctypes.WinDLL("shell32", use_last_error=True).Shell_NotifyIconGetRect
query.argtypes = [ctypes.POINTER(NOTIFYICONIDENTIFIER), ctypes.POINTER(wintypes.RECT)]
query.restype = ctypes.c_long
result = query(ctypes.byref(identity), ctypes.byref(rect))
record = {
    "ui_pid": ui["pid"], "frozen": ui["frozen"], "state": ui["state"],
    "window_visible": bool(user.IsWindowVisible(shell["window_hwnd"])),
    "big_icon_handle": int(user.SendMessageW(shell["window_hwnd"], 0x7F, 1, 0)),
    "small_icon_handle": int(user.SendMessageW(shell["window_hwnd"], 0x7F, 0, 0)),
    "notify_icon_get_rect_hresult": result,
    "notify_icon_os_rect": [rect.left, rect.top, rect.right, rect.bottom] if result == 0 else None,
    "shell": shell,
}
path = ROOT / "work" / "desktop-app-20261004" / "desktop-runtime-os.json"
path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(record, ensure_ascii=True))
assert record["frozen"] and record["window_visible"]
assert record["big_icon_handle"] and record["small_icon_handle"]
assert record["shell"]["tray_icon_added"] and not record["shell"]["error"]
assert result == 0, "Windows did not locate the registered notification icon"
