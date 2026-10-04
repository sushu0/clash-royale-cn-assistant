"""Read-only PrintWindow benchmark; never activate or alter windows."""
import ctypes
import hashlib
import json
import statistics
import time
from ctypes import wintypes
from pathlib import Path

import numpy as np
from PIL import Image

OUT = Path(__file__).parent
user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    pass

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumChildWindows.argtypes = [wintypes.HWND, WNDENUMPROC, wintypes.LPARAM]
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT,
                           wintypes.UINT, ctypes.c_void_p, ctypes.POINTER(BITMAPINFO),
                           wintypes.UINT]


def info(hwnd):
    text = ctypes.create_unicode_buffer(512)
    cls = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, text, 512)
    user32.GetClassNameW(hwnd, cls, 256)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    rect = wintypes.RECT()
    client = wintypes.RECT()
    point = wintypes.POINT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    user32.GetClientRect(hwnd, ctypes.byref(client))
    user32.ClientToScreen(hwnd, ctypes.byref(point))
    return {"hwnd": int(hwnd), "title": text.value, "class": cls.value,
            "pid": pid.value, "visible": bool(user32.IsWindowVisible(hwnd)),
            "iconic": bool(user32.IsIconic(hwnd)),
            "window_rect": [rect.left, rect.top, rect.right, rect.bottom],
            "client_size": [client.right, client.bottom],
            "client_origin": [point.x, point.y]}


def capture(hwnd, flags=3):
    client = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(client))
    width, height = client.right, client.bottom
    dc = user32.GetDC(hwnd)
    memdc = gdi32.CreateCompatibleDC(dc)
    bitmap = gdi32.CreateCompatibleBitmap(dc, width, height)
    old = gdi32.SelectObject(memdc, bitmap)
    try:
        start = time.perf_counter()
        ok = user32.PrintWindow(hwnd, memdc, flags)
        elapsed_print = time.perf_counter() - start
        header = BITMAPINFO()
        header.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        header.bmiHeader.biWidth = width
        header.bmiHeader.biHeight = -height
        header.bmiHeader.biPlanes = 1
        header.bmiHeader.biBitCount = 32
        header.bmiHeader.biCompression = 0
        raw = ctypes.create_string_buffer(width * height * 4)
        gdi32.SelectObject(memdc, old)
        scanlines = gdi32.GetDIBits(memdc, bitmap, 0, height, raw,
                                   ctypes.byref(header), 0)
        result = Image.frombuffer("RGB", (width, height), raw.raw,
                                  "raw", "BGRX", 0, 1).copy()
        return result, {"ok": bool(ok), "scanlines": scanlines,
                        "print_ms": elapsed_print * 1000,
                        "total_ms": (time.perf_counter() - start) * 1000}
    finally:
        gdi32.SelectObject(memdc, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memdc)
        user32.ReleaseDC(hwnd, dc)


def collect(parent=None):
    found = []
    @WNDENUMPROC
    def callback(hwnd, _lparam):
        found.append(info(hwnd))
        return True
    if parent is None:
        user32.EnumWindows(callback, 0)
    else:
        user32.EnumChildWindows(parent, callback, 0)
    return found


def main():
    tops = collect()
    candidates = [w for w in tops if "memu" in w["title"].lower()]
    report = {"foreground": info(user32.GetForegroundWindow()),
              "memu_windows": candidates}
    windows = []
    for w in candidates:
        children = collect(w["hwnd"])
        w["children"] = children
        if w["visible"] and w["client_size"][0] > 200:
            windows.append(w)
            windows.extend(c for c in children if c["visible"]
                           and min(c["client_size"]) > 200)
    tests = []
    for w in windows:
        test = {"window": w, "frames": []}
        previous = None
        for index in range(12):
            image, metadata = capture(w["hwnd"])
            pixels = np.asarray(image)
            metadata.update({"mean": float(pixels.mean()),
                             "std": float(pixels.std()),
                             "black_fraction": float(np.all(pixels < 4, axis=2).mean()),
                             "hash": hashlib.sha256(image.tobytes()).hexdigest(),
                             "diff_from_previous": None if previous is None else
                             float(np.abs(pixels.astype(float) - previous).mean())})
            previous = pixels.astype(float)
            test["frames"].append(metadata)
            if index in (0, 11):
                name = f"native-{w['hwnd']}-{index:02d}.png"
                image.save(OUT / name)
                metadata["image"] = name
            time.sleep(0.10)
        test["median_ms"] = statistics.median(f["total_ms"] for f in test["frames"])
        tests.append(test)
    report["tests"] = tests
    (OUT / "native-capture-probe.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
