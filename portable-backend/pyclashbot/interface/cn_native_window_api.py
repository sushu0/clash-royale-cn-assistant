"""Win32 ownership and geometry for reversible native emulator embedding."""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from pyclashbot.utils.platform import is_windows

GWL_STYLE = -16
GWL_EXSTYLE = -20
GW_OWNER = 4
WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PER_MONITOR_AWARE = -3
WM_EXITSIZEMOVE = 0x0232


class _WindowPlacement(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.UINT),
        ("flags", wintypes.UINT),
        ("showCmd", wintypes.UINT),
        ("ptMinPosition", wintypes.POINT),
        ("ptMaxPosition", wintypes.POINT),
        ("rcNormalPosition", wintypes.RECT),
    ]


class WindowPlacementData(TypedDict):
    flags: int
    showCmd: int
    ptMinPosition: tuple[int, int]
    ptMaxPosition: tuple[int, int]
    rcNormalPosition: tuple[int, int, int, int]


@dataclass(frozen=True)
class WindowSnapshot:
    """Original window state; rect is screen geometry, placement is opaque."""

    hwnd: int
    pid: int
    parent: int
    style: int
    ex_style: int
    placement: WindowPlacementData
    rect: tuple[int, int, int, int]
    content_rect: tuple[int, int, int, int] | None = None


def enable_native_embedding_dpi() -> bool:
    """Match MEmu's per-monitor V1 context before the calling thread creates Tk."""
    if not is_windows():
        return False
    user32 = ctypes.WinDLL("user32", use_last_error=True)  # ty: ignore[unresolved-attribute]  # Windows-only API behind platform gate
    user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
    user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    context = ctypes.c_void_p(PER_MONITOR_AWARE)
    process_set = bool(user32.SetProcessDpiAwarenessContext(context))
    # Process awareness can already be fixed by another dependency. The UI
    # thread still needs the matching context before it creates any windows.
    thread_set = bool(user32.SetThreadDpiAwarenessContext(context))
    return process_set or thread_set


class Win32WindowAPI:
    """Operate on existing emulator windows without capture or game input."""

    def __init__(self) -> None:
        if not is_windows():
            raise RuntimeError("原生模拟器嵌入仅支持 Windows")
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)  # ty: ignore[unresolved-attribute]  # Windows-only API behind platform gate
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # ty: ignore[unresolved-attribute]  # Windows-only API behind platform gate
        self._callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)  # ty: ignore[unresolved-attribute]  # Windows-only API behind platform gate
        self._bind_functions()

    def _bind_functions(self) -> None:
        user32 = self._user32
        user32.EnumWindows.argtypes = [self._callback_type, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.EnumChildWindows.argtypes = [wintypes.HWND, self._callback_type, wintypes.LPARAM]
        user32.EnumChildWindows.restype = wintypes.BOOL
        user32.GetParent.argtypes = [wintypes.HWND]
        user32.GetParent.restype = wintypes.HWND
        user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetWindow.restype = wintypes.HWND
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetClassNameW.restype = ctypes.c_int
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.GetClientRect.restype = wintypes.BOOL
        user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        user32.ScreenToClient.restype = wintypes.BOOL
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
        user32.SetParent.restype = wintypes.HWND
        user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.PostMessageW.restype = wintypes.BOOL
        user32.GetWindowPlacement.argtypes = [wintypes.HWND, ctypes.POINTER(_WindowPlacement)]
        user32.GetWindowPlacement.restype = wintypes.BOOL
        user32.SetWindowPlacement.argtypes = [wintypes.HWND, ctypes.POINTER(_WindowPlacement)]
        user32.SetWindowPlacement.restype = wintypes.BOOL
        kernel32 = self._kernel32
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

    def _pid(self, hwnd: int) -> int:
        pid = wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value

    def _text(self, hwnd: int, *, window_class: bool = False) -> str:
        buffer = ctypes.create_unicode_buffer(512)
        function = self._user32.GetClassNameW if window_class else self._user32.GetWindowTextW
        function(hwnd, buffer, len(buffer))
        return buffer.value

    def _windows(self, parent: int | None = None) -> list[int]:
        result: list[int] = []

        @self._callback_type
        def collect(hwnd: int, _lparam: int) -> bool:
            result.append(int(hwnd))
            return True

        if parent is None:
            self._user32.EnumWindows(collect, 0)
        else:
            self._user32.EnumChildWindows(parent, collect, 0)
        return result

    def _executable(self, pid: int) -> Path | None:
        process = self._kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not process:
            return None
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            length = wintypes.DWORD(len(buffer))
            if not self._kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(length)):
                return None
            return Path(buffer.value)
        finally:
            self._kernel32.CloseHandle(process)

    @staticmethod
    def _path_key(path: Path) -> str:
        return os.path.normcase(str(path.resolve()))

    def _renderer(self, hwnd: int) -> int | None:
        for child in self._windows(hwnd):
            if self._text(child) == "RenderWindowWindow":
                client = wintypes.RECT()
                if self._user32.GetClientRect(child, ctypes.byref(client)) and client.right > 0 and client.bottom > 0:
                    return child
        return None

    def find_window(self, executable: Path) -> int | None:
        """Return the unique unowned Qt emulator window from this exact executable."""
        expected = self._path_key(executable)
        matches = []
        paths: dict[int, Path | None] = {}
        for hwnd in self._windows():
            if self._user32.GetWindow(hwnd, GW_OWNER) or not self._text(hwnd, window_class=True).startswith("Qt"):
                continue
            pid = self._pid(hwnd)
            if pid not in paths:
                paths[pid] = self._executable(pid)
            path = paths[pid]
            if path is not None and self._path_key(path) == expected and self._renderer(hwnd) is not None:
                matches.append(hwnd)
        return matches[0] if len(matches) == 1 else None

    def is_window(self, hwnd: int, pid: int) -> bool:
        """Check ownership too, so a recycled HWND is not moved or restored."""
        return bool(self._user32.IsWindow(hwnd)) and self._pid(hwnd) == pid

    def window_executable(self, hwnd: int) -> Path | None:
        executable = self._executable(self._pid(hwnd))
        return executable.resolve() if executable is not None else None

    def _get_long(self, hwnd: int, index: int) -> int:
        ctypes.set_last_error(0)  # ty: ignore[unresolved-attribute]  # Windows-only API behind platform gate
        value = self._user32.GetWindowLongPtrW(hwnd, index)
        error = ctypes.get_last_error()  # ty: ignore[unresolved-attribute]  # Windows-only API behind platform gate
        if not value and error:
            raise ctypes.WinError(error)  # ty: ignore[unresolved-attribute]  # Windows-only API behind platform gate
        return value & 0xFFFFFFFF

    def snapshot(self, hwnd: int) -> WindowSnapshot:
        pid = self._pid(hwnd)
        if not pid or not self.is_window(hwnd, pid):
            raise RuntimeError("模拟器窗口已经关闭")
        rect = wintypes.RECT()
        if not self._user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise ctypes.WinError(ctypes.get_last_error())  # ty: ignore[unresolved-attribute]  # Windows-only API behind platform gate
        placement = _WindowPlacement()
        placement.length = ctypes.sizeof(placement)
        if not self._user32.GetWindowPlacement(hwnd, ctypes.byref(placement)):
            raise ctypes.WinError(ctypes.get_last_error())  # ty: ignore[unresolved-attribute]  # Windows-only API behind platform gate
        saved_placement: WindowPlacementData = {
            "flags": int(placement.flags),
            "showCmd": int(placement.showCmd),
            "ptMinPosition": (placement.ptMinPosition.x, placement.ptMinPosition.y),
            "ptMaxPosition": (placement.ptMaxPosition.x, placement.ptMaxPosition.y),
            "rcNormalPosition": (
                placement.rcNormalPosition.left,
                placement.rcNormalPosition.top,
                placement.rcNormalPosition.right,
                placement.rcNormalPosition.bottom,
            ),
        }
        content_rect = None
        renderer = self._renderer(hwnd)
        if renderer is not None:
            render_rect = wintypes.RECT()
            if self._user32.GetWindowRect(renderer, ctypes.byref(render_rect)):
                point = wintypes.POINT(render_rect.left, render_rect.top)
                if self._user32.ScreenToClient(hwnd, ctypes.byref(point)):
                    content_rect = (
                        point.x,
                        point.y,
                        render_rect.right - render_rect.left,
                        render_rect.bottom - render_rect.top,
                    )
        return WindowSnapshot(
            hwnd=hwnd,
            pid=pid,
            parent=int(self._user32.GetParent(hwnd) or 0),
            style=self._get_long(hwnd, GWL_STYLE),
            ex_style=self._get_long(hwnd, GWL_EXSTYLE),
            placement=saved_placement,
            rect=(rect.left, rect.top, rect.right, rect.bottom),
            content_rect=content_rect,
        )

    def _set_long(self, hwnd: int, index: int, value: int) -> None:
        ctypes.set_last_error(0)  # ty: ignore[unresolved-attribute]  # Windows-only API behind platform gate
        previous = self._user32.SetWindowLongPtrW(hwnd, index, value)
        error = ctypes.get_last_error()  # ty: ignore[unresolved-attribute]  # Windows-only API behind platform gate
        if not previous and error:
            raise ctypes.WinError(error)  # ty: ignore[unresolved-attribute]  # Windows-only API behind platform gate

    def set_style(self, hwnd: int, style: int) -> None:
        self._set_long(hwnd, GWL_STYLE, style)

    def set_ex_style(self, hwnd: int, ex_style: int) -> None:
        self._set_long(hwnd, GWL_EXSTYLE, ex_style)

    def set_parent(self, hwnd: int, parent: int) -> None:
        ctypes.set_last_error(0)  # ty: ignore[unresolved-attribute]  # Windows-only API behind platform gate
        previous = self._user32.SetParent(hwnd, parent or None)
        error = ctypes.get_last_error()  # ty: ignore[unresolved-attribute]  # Windows-only API behind platform gate
        if not previous and error:
            raise ctypes.WinError(error)  # ty: ignore[unresolved-attribute]  # Windows-only API behind platform gate

    def move_window(self, hwnd: int, x: int, y: int, width: int, height: int) -> None:
        """Move in current parent-client coordinates, or screen for a top-level."""
        if width <= 0 or height <= 0:
            raise ValueError("模拟器窗口尺寸必须为正数")
        if not self._user32.SetWindowPos(
            hwnd,
            None,
            x,
            y,
            width,
            height,
            SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        ):
            raise ctypes.WinError(ctypes.get_last_error())  # ty: ignore[unresolved-attribute]  # Windows-only API behind platform gate

    def _resize_tree(self, hwnd: int) -> tuple[int, list[tuple[int, int]], int, int]:
        """Validate the exact MEmu / Qt / Headless tree before any resize event."""
        root_pid = self._pid(hwnd)
        root_path = self._executable(root_pid)
        if (
            not root_pid
            or not self.is_window(hwnd, root_pid)
            or root_path is None
            or root_path.name.casefold() != "memu.exe"
            or not self._text(hwnd, window_class=True).startswith("Qt")
        ):
            raise RuntimeError("无法确认原模拟器窗口; 已停止调整")
        root_client = wintypes.RECT()
        if not self._user32.GetClientRect(hwnd, ctypes.byref(root_client)):
            raise ctypes.WinError(ctypes.get_last_error())  # ty: ignore[unresolved-attribute]  # Windows-only API behind platform gate
        if root_client.right <= root_client.left or root_client.bottom <= root_client.top:
            raise RuntimeError("模拟器主窗口尺寸不可用; 已停止调整")
        renderer = self._renderer(hwnd)
        if (
            renderer is None
            or not self.is_window(renderer, root_pid)
            or not self._text(renderer, window_class=True).startswith("Qt")
        ):
            raise RuntimeError("未找到原模拟器的渲染窗口; 已停止调整")
        renderer_parent = int(self._user32.GetParent(renderer) or 0)
        if not self.is_window(renderer_parent, root_pid) or self._text(renderer_parent) != "CenterWidgetWindow":
            raise RuntimeError("模拟器渲染窗口父级不匹配; 已停止调整")
        client = wintypes.RECT()
        if not self._user32.GetClientRect(renderer, ctypes.byref(client)):
            raise ctypes.WinError(ctypes.get_last_error())  # ty: ignore[unresolved-attribute]  # Windows-only API behind platform gate
        width, height = client.right - client.left, client.bottom - client.top
        if width <= 0 or height <= 0:
            raise RuntimeError("渲染窗口尺寸不可用; 已停止调整")
        children = [
            child
            for child in self._windows(renderer)
            if self._text(child, window_class=True) == "subWin" and self._text(child) == "sub"
        ]
        if len(children) != 2:
            raise RuntimeError("模拟器渲染子窗口结构不明确; 已停止调整")
        outer = next((child for child in children if int(self._user32.GetParent(child) or 0) == renderer), None)
        if outer is None:
            raise RuntimeError("模拟器渲染子窗口父级不匹配; 已停止调整")
        inner = next((child for child in children if int(self._user32.GetParent(child) or 0) == outer), None)
        if inner is None:
            raise RuntimeError("模拟器渲染子窗口层级不匹配; 已停止调整")
        surface_pid = self._pid(outer)
        surface_path = self._executable(surface_pid)
        if (
            not surface_pid
            or surface_path is None
            or surface_path.name.casefold() != "memuheadless.exe"
            or not self.is_window(outer, surface_pid)
            or not self.is_window(inner, surface_pid)
        ):
            raise RuntimeError("模拟器渲染子窗口所属进程不匹配; 已停止调整")
        # Validate both surfaces completely before changing either one.
        for surface in (outer, inner):
            surface_client = wintypes.RECT()
            if not self._user32.GetClientRect(surface, ctypes.byref(surface_client)):
                raise ctypes.WinError(ctypes.get_last_error())  # ty: ignore[unresolved-attribute]  # Windows-only API behind platform gate
            if surface_client.right <= surface_client.left or surface_client.bottom <= surface_client.top:
                raise RuntimeError("模拟器渲染子窗口尺寸不可用; 已停止调整")
        return renderer, [(outer, surface_pid), (inner, surface_pid)], width, height

    def finish_resize(self, hwnd: int) -> None:
        """Post only the normal native resize-completed lifecycle event to MEmu."""
        self._resize_tree(hwnd)
        if not self._user32.PostMessageW(hwnd, WM_EXITSIZEMOVE, 0, 0):
            raise ctypes.WinError(ctypes.get_last_error())  # ty: ignore[unresolved-attribute]  # Windows-only API behind platform gate

    def resize_render_surfaces(self, hwnd: int) -> None:
        """Size the two Headless surfaces to their existing Qt renderer client."""
        renderer, surfaces, width, height = self._resize_tree(hwnd)
        expected_parent = renderer
        for surface, pid in surfaces:
            if not self.is_window(surface, pid) or int(self._user32.GetParent(surface) or 0) != expected_parent:
                raise RuntimeError("模拟器渲染子窗口已变化; 已停止调整")
            client = wintypes.RECT()
            if not self._user32.GetClientRect(surface, ctypes.byref(client)):
                raise ctypes.WinError(ctypes.get_last_error())  # ty: ignore[unresolved-attribute]  # Windows-only API behind platform gate
            if (client.right - client.left, client.bottom - client.top) != (width, height):
                if not self._user32.SetWindowPos(
                    surface,
                    None,
                    0,
                    0,
                    width,
                    height,
                    SWP_NOZORDER | SWP_NOACTIVATE,
                ):
                    raise ctypes.WinError(ctypes.get_last_error())  # ty: ignore[unresolved-attribute]  # Windows-only API behind platform gate
            expected_parent = surface

    def restore(self, hwnd: int, snapshot: WindowSnapshot) -> None:
        """Detach before host destruction, restoring original placement and styles."""
        if hwnd != snapshot.hwnd or not self.is_window(hwnd, snapshot.pid):
            raise RuntimeError("原模拟器窗口已关闭; 无法恢复其他窗口")
        if snapshot.parent and not self._user32.IsWindow(snapshot.parent):
            raise RuntimeError("模拟器原父窗口已关闭")
        self.set_parent(hwnd, snapshot.parent)
        self.set_style(hwnd, snapshot.style)
        self.set_ex_style(hwnd, snapshot.ex_style)
        left, top, right, bottom = snapshot.rect
        if snapshot.parent and snapshot.style & WS_CHILD:
            point = wintypes.POINT(left, top)
            if not self._user32.ScreenToClient(snapshot.parent, ctypes.byref(point)):
                raise ctypes.WinError(ctypes.get_last_error())  # ty: ignore[unresolved-attribute]  # Windows-only API behind platform gate
            left, top = point.x, point.y
        self.move_window(hwnd, left, top, right - snapshot.rect[0], bottom - snapshot.rect[1])
        placement = _WindowPlacement()
        placement.length = ctypes.sizeof(placement)
        placement.flags = int(snapshot.placement["flags"])
        placement.showCmd = int(snapshot.placement["showCmd"])
        placement.ptMinPosition = wintypes.POINT(*snapshot.placement["ptMinPosition"])
        placement.ptMaxPosition = wintypes.POINT(*snapshot.placement["ptMaxPosition"])
        placement.rcNormalPosition = wintypes.RECT(*snapshot.placement["rcNormalPosition"])
        if not self._user32.SetWindowPlacement(hwnd, ctypes.byref(placement)):
            raise ctypes.WinError(ctypes.get_last_error())  # ty: ignore[unresolved-attribute]  # Windows-only API behind platform gate
        # Qt completes its child layout asynchronously in another process.
        # Wait briefly before restoring the Headless render surfaces as well.
        time.sleep(0.1)
        try:
            self.resize_render_surfaces(hwnd)
        except RuntimeError:
            # A VM may have closed its render children. The surviving MEmu
            # top-level has already been safely detached and restored.
            pass
