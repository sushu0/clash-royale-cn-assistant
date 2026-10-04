"""Read current embedded HWND geometry, without capture or window messages."""
import ctypes
import json
from ctypes import wintypes
from pathlib import Path

from pyclashbot.interface.cn_native_window_api import Win32WindowAPI, enable_native_embedding_dpi

enable_native_embedding_dpi()
api = Win32WindowAPI()
user32 = api._user32
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.ClientToScreen.restype = wintypes.BOOL
user32.GetWindowDpiAwarenessContext.argtypes = [wintypes.HWND]
user32.GetWindowDpiAwarenessContext.restype = ctypes.c_void_p
user32.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
user32.GetAwarenessFromDpiAwarenessContext.restype = ctypes.c_int
user32.GetDpiForWindow.argtypes = [wintypes.HWND]
user32.GetDpiForWindow.restype = wintypes.UINT


def detail(hwnd):
    rect = wintypes.RECT()
    client = wintypes.RECT()
    origin = wintypes.POINT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    user32.GetClientRect(hwnd, ctypes.byref(client))
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    parent = int(user32.GetParent(hwnd) or 0)
    parent_point = wintypes.POINT(rect.left, rect.top)
    if parent:
        user32.ScreenToClient(parent, ctypes.byref(parent_point))
    return {"hwnd": hwnd, "title": api._text(hwnd), "class": api._text(hwnd, window_class=True),
            "pid": api._pid(hwnd), "parent": parent,
            "rect": [rect.left, rect.top, rect.right, rect.bottom],
            "client": [client.right, client.bottom],
            "client_origin_screen": [origin.x, origin.y],
            "parent_client_pos": [parent_point.x, parent_point.y],
            "style": f"0x{api._get_long(hwnd, -16):08X}",
            "exstyle": f"0x{api._get_long(hwnd, -20):08X}",
            "dpi": user32.GetDpiForWindow(hwnd),
            "dpi_awareness": user32.GetAwarenessFromDpiAwarenessContext(
                user32.GetWindowDpiAwarenessContext(hwnd))}


root = 1179668
host = 264896
memu = 461152
result = {"gui_root": detail(root), "host": detail(host), "memu_root": detail(memu),
          "descendants": [detail(w) for w in api._windows(memu)]}
out = Path(__file__).parent
(out / "native-embedded-tree.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps({**{k: v for k, v in result.items() if k != "descendants"},
                  "primary_descendants": [w for w in result["descendants"]
                                          if min(w["client"]) > 200]}, indent=2))
