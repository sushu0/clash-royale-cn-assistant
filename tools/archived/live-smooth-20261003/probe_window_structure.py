"""Read-only native MEmu HWND structure for a reversible embedding design."""
import ctypes
import json
from ctypes import wintypes
from pathlib import Path

OUT = Path(__file__).parent
u = ctypes.WinDLL("user32", use_last_error=True)
u.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
CALLBACK = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
u.EnumWindows.argtypes = [CALLBACK, wintypes.LPARAM]
u.EnumChildWindows.argtypes = [wintypes.HWND, CALLBACK, wintypes.LPARAM]
u.GetParent.argtypes = [wintypes.HWND]
u.GetParent.restype = wintypes.HWND
u.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
u.GetAncestor.restype = wintypes.HWND
u.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
u.GetWindow.restype = wintypes.HWND
u.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
u.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
u.IsWindowVisible.argtypes = [wintypes.HWND]
u.IsIconic.argtypes = [wintypes.HWND]
u.GetWindowDpiAwarenessContext.argtypes = [wintypes.HWND]
u.GetWindowDpiAwarenessContext.restype = ctypes.c_void_p
u.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
u.GetAwarenessFromDpiAwarenessContext.restype = ctypes.c_int
u.GetDpiForWindow.argtypes = [wintypes.HWND]
u.GetDpiForWindow.restype = wintypes.UINT
u.AreDpiAwarenessContextsEqual.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
u.AreDpiAwarenessContextsEqual.restype = wintypes.BOOL

STYLES = {"WS_CHILD": 0x40000000, "WS_POPUP": 0x80000000,
          "WS_VISIBLE": 0x10000000, "WS_DISABLED": 0x08000000,
          "WS_CLIPSIBLINGS": 0x04000000, "WS_CLIPCHILDREN": 0x02000000,
          "WS_CAPTION": 0x00C00000, "WS_BORDER": 0x00800000,
          "WS_DLGFRAME": 0x00400000, "WS_SYSMENU": 0x00080000,
          "WS_THICKFRAME": 0x00040000, "WS_MINIMIZEBOX": 0x00020000,
          "WS_MAXIMIZEBOX": 0x00010000}
EXSTYLES = {"WS_EX_APPWINDOW": 0x00040000, "WS_EX_NOACTIVATE": 0x08000000,
            "WS_EX_TOOLWINDOW": 0x00000080, "WS_EX_TOPMOST": 0x00000008,
            "WS_EX_LAYERED": 0x00080000, "WS_EX_TRANSPARENT": 0x00000020,
            "WS_EX_COMPOSITED": 0x02000000}


def rect_value(rect):
    return [rect.left, rect.top, rect.right, rect.bottom]


def basic(hwnd):
    title = ctypes.create_unicode_buffer(512)
    cls = ctypes.create_unicode_buffer(256)
    u.GetWindowTextW(hwnd, title, 512)
    u.GetClassNameW(hwnd, cls, 256)
    pid = wintypes.DWORD()
    thread = u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return {"hwnd": int(hwnd), "title": title.value, "class": cls.value,
            "pid": pid.value, "thread_id": thread}


def detail(hwnd):
    result = basic(hwnd)
    parent = u.GetParent(hwnd)
    owner = u.GetWindow(hwnd, 4)
    style = u.GetWindowLongPtrW(hwnd, -16) & 0xFFFFFFFF
    exstyle = u.GetWindowLongPtrW(hwnd, -20) & 0xFFFFFFFF
    rect, client, origin = wintypes.RECT(), wintypes.RECT(), wintypes.POINT()
    u.GetWindowRect(hwnd, ctypes.byref(rect))
    u.GetClientRect(hwnd, ctypes.byref(client))
    u.ClientToScreen(hwnd, ctypes.byref(origin))
    top_left = wintypes.POINT(rect.left, rect.top)
    if parent and style & STYLES["WS_CHILD"]:
        u.ScreenToClient(parent, ctypes.byref(top_left))
    result.update({"parent": basic(parent) if parent else None,
                   "owner": basic(owner) if owner else None,
                   "root": int(u.GetAncestor(hwnd, 2) or 0),
                   "root_owner": int(u.GetAncestor(hwnd, 3) or 0),
                   "style": style, "style_hex": f"0x{style:08X}",
                   "styles": [name for name, flag in STYLES.items() if style & flag == flag],
                   "exstyle": exstyle, "exstyle_hex": f"0x{exstyle:08X}",
                   "exstyles": [name for name, flag in EXSTYLES.items() if exstyle & flag == flag],
                   "screen_rect": rect_value(rect), "client_rect": rect_value(client),
                   "client_origin_screen": [origin.x, origin.y],
                   "position_parent_client_or_screen": [top_left.x, top_left.y],
                   "window_size": [rect.right - rect.left, rect.bottom - rect.top],
                   "dpi": u.GetDpiForWindow(hwnd),
                   "dpi_awareness": u.GetAwarenessFromDpiAwarenessContext(
                       u.GetWindowDpiAwarenessContext(hwnd)),
                   "dpi_per_monitor_v1": bool(u.AreDpiAwarenessContextsEqual(
                       u.GetWindowDpiAwarenessContext(hwnd), ctypes.c_void_p(-3))),
                   "dpi_per_monitor_v2": bool(u.AreDpiAwarenessContextsEqual(
                       u.GetWindowDpiAwarenessContext(hwnd), ctypes.c_void_p(-4))),
                   "visible": bool(u.IsWindowVisible(hwnd)), "iconic": bool(u.IsIconic(hwnd))})
    return result


def collect(parent=None):
    rows = []
    @CALLBACK
    def callback(hwnd, _lparam):
        rows.append(detail(hwnd))
        return True
    if parent is None:
        u.EnumWindows(callback, 0)
    else:
        u.EnumChildWindows(parent, callback, 0)
    return rows


tops = collect()
memu = [w for w in tops if w["title"] == "MEmu" and w["visible"]
        and min(w["window_size"]) > 200]
result = {"top_windows": memu, "children": [],
          "tk_windows": [w for w in tops if w["class"] == "TkTopLevel"]}
for w in memu:
    result["children"].extend(collect(w["hwnd"]))
(OUT / "native-window-structure.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps({"top_windows": memu,
                  "tk_windows": result["tk_windows"],
                  "primary_children": [c for c in result["children"]
                                       if min(c["window_size"]) > 200]}, indent=2))
