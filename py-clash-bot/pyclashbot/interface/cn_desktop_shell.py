"""Windows desktop identity, native tray actions and a local single-instance gate.

The Win32 tray window owns its own message loop. It only puts actions into a
queue; Tk widgets and application callbacks are touched by Tk's main thread.
Importing this module never loads a Windows DLL or starts a thread.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import queue
import threading
from ctypes import wintypes
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from tkinter import Tk

APP_ID = "Codex.ClashAssistant.Desktop.2026"
APP_TITLE = "皇室战争助手"
WM_APP = 0x8000
WM_TRAY = WM_APP + 42
WM_STATUS = WM_APP + 43
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_NULL = 0x0000
WM_SETICON = 0x0080
WM_CONTEXTMENU = 0x007B
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
NIN_SELECT = 0x0400
NIN_KEYSELECT = 0x0401
NIM_ADD = 0
NIM_MODIFY = 1
NIM_DELETE = 2
NIM_SETVERSION = 4
NIF_MESSAGE = 1
NIF_ICON = 2
NIF_TIP = 4
NIF_SHOWTIP = 0x80
MF_GRAYED = 1
MF_SEPARATOR = 0x0800
TPM_RETURNCMD = 0x0100
TPM_NONOTIFY = 0x0080
TPM_RIGHTBUTTON = 0x0002
ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
IDI_APPLICATION = 32512
ICON_SMALL = 0
ICON_BIG = 1
COMMAND_SHOW = 1
COMMAND_START = 2
COMMAND_STOP = 3
COMMAND_EXIT = 4


class _Guid(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _NotifyIconData(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uTimeoutOrVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", _Guid),
        ("hBalloonIcon", wintypes.HICON),
    ]


class _WindowClass(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


def _tooltip(text: str) -> str:
    """Shell's limit is 127 UTF-16 code units, not 127 Unicode code points."""
    label = f"{APP_TITLE} · {text}".replace("\x00", " ")
    return label.encode("utf-16-le")[:254].decode("utf-16-le", errors="ignore")


def _menu_entries(running: bool) -> tuple[tuple[int, str, int], ...]:
    return (
        (COMMAND_SHOW, "显示主界面", 0),
        (COMMAND_START, "开始运行", MF_GRAYED if running else 0),
        (COMMAND_STOP, "停止任务", 0 if running else MF_GRAYED),
        (0, "", MF_SEPARATOR),
        (COMMAND_EXIT, "退出软件", 0),
    )


class _Win32:
    """Declare pointer-size-correct ctypes signatures in one platform gate."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("Windows 桌面外壳仅支持 Windows")
        self.user = ctypes.WinDLL("user32", use_last_error=True)  # ty: ignore[unresolved-attribute]
        self.shell = ctypes.WinDLL("shell32", use_last_error=True)  # ty: ignore[unresolved-attribute]
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # ty: ignore[unresolved-attribute]
        self.callback_type = ctypes.WINFUNCTYPE(  # ty: ignore[unresolved-attribute]
            ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        )
        user_signatures = {
            "RegisterClassW": ([ctypes.POINTER(_WindowClass)], wintypes.ATOM),
            "UnregisterClassW": ([wintypes.LPCWSTR, wintypes.HINSTANCE], wintypes.BOOL),
            "CreateWindowExW": (
                [
                    wintypes.DWORD,
                    wintypes.LPCWSTR,
                    wintypes.LPCWSTR,
                    wintypes.DWORD,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    wintypes.HWND,
                    wintypes.HMENU,
                    wintypes.HINSTANCE,
                    ctypes.c_void_p,
                ],
                wintypes.HWND,
            ),
            "DefWindowProcW": ([wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], ctypes.c_ssize_t),
            "DestroyWindow": ([wintypes.HWND], wintypes.BOOL),
            "GetMessageW": ([ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT], wintypes.BOOL),
            "TranslateMessage": ([ctypes.POINTER(wintypes.MSG)], wintypes.BOOL),
            "DispatchMessageW": ([ctypes.POINTER(wintypes.MSG)], ctypes.c_ssize_t),
            "PostQuitMessage": ([ctypes.c_int], None),
            "PostMessageW": ([wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL),
            "SendMessageW": ([wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], ctypes.c_ssize_t),
            "RegisterWindowMessageW": ([wintypes.LPCWSTR], wintypes.UINT),
            "LoadImageW": (
                [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT],
                wintypes.HANDLE,
            ),
            "LoadIconW": ([wintypes.HINSTANCE, ctypes.c_void_p], wintypes.HICON),
            "DestroyIcon": ([wintypes.HICON], wintypes.BOOL),
            "GetAncestor": ([wintypes.HWND, wintypes.UINT], wintypes.HWND),
            "GetSystemMetrics": ([ctypes.c_int], ctypes.c_int),
            "CreatePopupMenu": ([], wintypes.HMENU),
            "AppendMenuW": ([wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR], wintypes.BOOL),
            "DestroyMenu": ([wintypes.HMENU], wintypes.BOOL),
            "GetCursorPos": ([ctypes.POINTER(wintypes.POINT)], wintypes.BOOL),
            "SetForegroundWindow": ([wintypes.HWND], wintypes.BOOL),
            "TrackPopupMenu": (
                [
                    wintypes.HMENU,
                    wintypes.UINT,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    wintypes.HWND,
                    ctypes.c_void_p,
                ],
                wintypes.UINT,
            ),
        }
        kernel_signatures = {
            "GetModuleHandleW": ([wintypes.LPCWSTR], wintypes.HMODULE),
            "CreateMutexW": ([ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
            "CreateEventW": ([ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
            "SetEvent": ([wintypes.HANDLE], wintypes.BOOL),
            "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
            "GetLastError": ([], wintypes.DWORD),
        }
        shell_signatures = {
            "Shell_NotifyIconW": ([wintypes.DWORD, ctypes.POINTER(_NotifyIconData)], wintypes.BOOL),
            "SetCurrentProcessExplicitAppUserModelID": ([wintypes.LPCWSTR], ctypes.c_long),
        }
        for library, signatures in (
            (self.user, user_signatures),
            (self.kernel, kernel_signatures),
            (self.shell, shell_signatures),
        ):
            for name, (args, result) in signatures.items():
                function = getattr(library, name)
                function.argtypes = args
                function.restype = result

    def icon(self, path: Path, size: int) -> tuple[int, bool]:
        handle = self.user.LoadImageW(None, str(path), IMAGE_ICON, size, size, LR_LOADFROMFILE)
        if handle:
            return int(handle), True
        return int(self.user.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION)) or 0), False


def set_app_identity() -> bool:
    """Call before creating Tk when possible; use the same identity in shortcuts."""
    if os.name != "nt":
        return False
    return _Win32().shell.SetCurrentProcessExplicitAppUserModelID(APP_ID) == 0


class SingleInstance:
    """Same-session Windows mutex; duplicate launches can only request Show.

    There is no TCP port, command parsing, process enumeration or PID heuristic.
    The launcher interpreter and its child cannot be confused with an app copy.
    """

    def __init__(self, name: str = APP_TITLE) -> None:
        self.name = name
        self.is_primary = True
        self._api: _Win32 | None = None
        self._mutex = 0
        self._event = 0
        self._timer: str | None = None
        self._root: Tk | None = None
        self._on_show: Callable[[], None] | None = None
        self._closed = False

    @property
    def acquired(self) -> bool:
        return self.is_primary and not self._closed

    def acquire(self) -> bool:
        if self._closed:
            raise RuntimeError("单实例锁已经关闭")
        if self._api is not None or os.name != "nt":
            return self.is_primary
        self._api = _Win32()
        suffix = hashlib.sha256(f"{APP_ID}:{self.name}".encode()).hexdigest()[:24]
        # Create the event first, so a rapid duplicate can signal even before
        # the primary Tk window and tray message loop have been constructed.
        self._event = int(
            self._api.kernel.CreateEventW(None, False, False, f"Local\\ClashAssistant.{suffix}.Show") or 0
        )
        if not self._event:
            raise OSError("无法创建软件唤起事件")
        self._mutex = int(self._api.kernel.CreateMutexW(None, False, f"Local\\ClashAssistant.{suffix}.Instance") or 0)
        error = self._api.kernel.GetLastError()
        if not self._mutex:
            self.close()
            raise OSError("无法创建软件单实例锁")
        self.is_primary = error != ERROR_ALREADY_EXISTS
        if not self.is_primary:
            self.request_focus()
        return self.is_primary

    def request_focus(self) -> bool:
        return bool(self._api and self._event and self._api.kernel.SetEvent(self._event))

    def consume_show_request(self) -> bool:
        return bool(
            self._api
            and self._event
            and self.is_primary
            and self._api.kernel.WaitForSingleObject(self._event, 0) == WAIT_OBJECT_0
        )

    def bind(self, root: Tk, on_show: Callable[[], None]) -> None:
        """Poll the fixed Show event from Tk's main thread."""
        if self._root is not None or self._closed:
            return
        self._root = root
        self._on_show = on_show
        self._timer = root.after(120, self._poll)

    def _poll(self) -> None:
        self._timer = None
        if self._closed or self._root is None:
            return
        if self.consume_show_request() and self._on_show is not None:
            self._on_show()
        if not self._closed:
            self._timer = self._root.after(120, self._poll)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._timer and self._root is not None:
            self._root.after_cancel(self._timer)
        self._timer = None
        if self._api is not None:
            for handle in (self._mutex, self._event):
                if handle:
                    self._api.kernel.CloseHandle(handle)
        self._mutex = self._event = 0


def acquire_single_instance(title: str = APP_TITLE) -> SingleInstance:
    guard = SingleInstance(title)
    guard.acquire()
    return guard


class _TrayWindow:
    def __init__(self, icon_path: Path, events: queue.Queue[str]) -> None:
        self.icon_path = icon_path
        self.events = events
        self.commands: queue.Queue[tuple[str, bool]] = queue.Queue()
        self.ready = threading.Event()
        self.finished = threading.Event()
        self.hwnd = 0
        self.tooltip = _tooltip("就绪")
        self.running = False
        self.icon_added = False
        self.error = ""
        self._closed = threading.Event()
        self._api: _Win32 | None = None
        self._icon = 0
        self._owned_icon = False
        self._restart_message = 0
        self._thread = threading.Thread(target=self._run, name="ClashAssistantTray", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def update(self, text: str, running: bool) -> None:
        self.commands.put((text, running))
        if self.hwnd and self._api is not None:
            self._api.user.PostMessageW(self.hwnd, WM_STATUS, 0, 0)

    def close(self) -> None:
        self._closed.set()
        if self.hwnd and self._api is not None:
            self._api.user.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    def _data(self) -> _NotifyIconData:
        data = _NotifyIconData()
        data.cbSize = ctypes.sizeof(data)
        data.hWnd = self.hwnd
        data.uID = 1
        data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP
        data.uCallbackMessage = WM_TRAY
        data.hIcon = self._icon
        data.szTip = self.tooltip
        return data

    def _add_icon(self) -> None:
        if self._api is None or self._closed.is_set():
            return
        data = self._data()
        self.icon_added = bool(self._api.shell.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data)))
        if self.icon_added:
            data.uTimeoutOrVersion = 4
            self._api.shell.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(data))
            self.error = ""
        else:
            self.error = "Windows 通知区域暂不可用"

    def _delete_icon(self) -> None:
        if self._api is not None and self.hwnd:
            data = self._data()
            self._api.shell.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(data))
        self.icon_added = False

    def _apply_status(self) -> None:
        latest = None
        while True:
            try:
                latest = self.commands.get_nowait()
            except queue.Empty:
                break
        if latest is None:
            return
        text, self.running = latest
        self.tooltip = _tooltip(text)
        if self._api is not None and self.icon_added:
            data = self._data()
            self._api.shell.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(data))
        elif self.hwnd:
            self._add_icon()

    def _show_menu(self) -> None:
        if self._api is None:
            return
        user = self._api.user
        menu = user.CreatePopupMenu()
        if not menu:
            return
        try:
            for command, text, flags in _menu_entries(self.running):
                user.AppendMenuW(menu, flags, command, text or None)
            point = wintypes.POINT()
            user.GetCursorPos(ctypes.byref(point))
            user.SetForegroundWindow(self.hwnd)
            selected = user.TrackPopupMenu(
                menu,
                TPM_RETURNCMD | TPM_NONOTIFY | TPM_RIGHTBUTTON,
                point.x,
                point.y,
                0,
                self.hwnd,
                None,
            )
            action = {COMMAND_SHOW: "show", COMMAND_START: "start", COMMAND_STOP: "stop", COMMAND_EXIT: "exit"}.get(
                selected
            )
            if action is not None:
                self.events.put(action)
            # Required for the native menu to dismiss on a click elsewhere.
            user.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        finally:
            user.DestroyMenu(menu)

    def _handle_message(self, hwnd: int, message: int, wparam: int, lparam: int) -> int:
        assert self._api is not None
        if self._restart_message and message == self._restart_message:
            self.icon_added = False
            self._add_icon()
            return 0
        if message == WM_STATUS:
            self._apply_status()
            return 0
        if message == WM_TRAY:
            event = lparam & 0xFFFF
            if event in (NIN_SELECT, NIN_KEYSELECT, WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                self.events.put("show")
            elif event in (WM_CONTEXTMENU, WM_RBUTTONUP):
                self._show_menu()
            return 0
        if message == WM_CLOSE:
            self._delete_icon()
            self._api.user.DestroyWindow(hwnd)
            return 0
        if message == WM_DESTROY:
            self._api.user.PostQuitMessage(0)
            return 0
        return int(self._api.user.DefWindowProcW(hwnd, message, wparam, lparam))

    def _window_proc(self, hwnd: int, message: int, wparam: int, lparam: int) -> int:
        try:
            return self._handle_message(hwnd, message, wparam, lparam)
        except Exception as exc:
            # Never let a Python exception unwind through a native callback.
            self.error = str(exc)
            return 0

    def _run(self) -> None:
        registered = False
        module = 0
        class_name = f"ClashAssistantTray.{os.getpid()}.{id(self)}"
        try:
            self._api = _Win32()
            api = self._api
            module = api.kernel.GetModuleHandleW(None)
            callback = api.callback_type(self._window_proc)
            window_class = _WindowClass()
            window_class.lpfnWndProc = ctypes.cast(callback, ctypes.c_void_p).value
            window_class.hInstance = module
            window_class.lpszClassName = class_name
            registered = bool(api.user.RegisterClassW(ctypes.byref(window_class)))
            if not registered:
                raise OSError("无法创建通知区域窗口类")
            self._restart_message = api.user.RegisterWindowMessageW("TaskbarCreated")
            self.hwnd = int(
                api.user.CreateWindowExW(0, class_name, f"{APP_TITLE}通知区域", 0, 0, 0, 0, 0, None, None, module, None)
                or 0
            )
            if not self.hwnd:
                raise OSError("无法创建通知区域消息窗口")
            self._icon, self._owned_icon = api.icon(self.icon_path, max(16, api.user.GetSystemMetrics(49)))
            self._apply_status()
            if not self.icon_added:
                self._add_icon()
            self.ready.set()
            if self._closed.is_set():
                api.user.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
            message = wintypes.MSG()
            while True:
                result = api.user.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result <= 0:
                    if result < 0:
                        self.error = "Windows 通知区域消息循环中断"
                    break
                api.user.TranslateMessage(ctypes.byref(message))
                api.user.DispatchMessageW(ctypes.byref(message))
        except Exception as exc:
            self.error = str(exc)
        finally:
            self._delete_icon()
            if self._api is not None:
                if self.hwnd:
                    self._api.user.DestroyWindow(self.hwnd)
                if self._owned_icon and self._icon:
                    self._api.user.DestroyIcon(self._icon)
                if registered:
                    self._api.user.UnregisterClassW(class_name, module)
            self.hwnd = 0
            self.ready.set()
            self.finished.set()


class DesktopShell:
    """Taskbar icons and native tray actions surrounding the existing Tk app.

    Create and close this object on Tk's main thread. ``set_status`` is safe
    from a worker thread. ``on_show`` remains responsible for any embedded
    emulator restore/detach behavior; the shell never controls game processes.
    """

    def __init__(
        self,
        root: Tk,
        icon_path: str | Path,
        on_show: Callable[[], None],
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        on_exit: Callable[[], None],
        *,
        instance: SingleInstance | None = None,
    ) -> None:
        self.root = root
        self.icon_path = Path(icon_path)
        self.instance = instance
        self._callbacks = {"show": on_show, "start": on_start, "stop": on_stop, "exit": on_exit}
        self._events: queue.Queue[str] = queue.Queue()
        self._closed = False
        self._timer: str | None = None
        self._native_icons: list[int] = []
        self._window_hwnd = 0
        self._api: _Win32 | None = None
        self._tray: _TrayWindow | None = None
        self._identity_set = False
        self._taskbar_icon_set = False
        self._error = ""
        if os.name == "nt":
            try:
                self._api = _Win32()
                self._identity_set = self._api.shell.SetCurrentProcessExplicitAppUserModelID(APP_ID) == 0
                self._set_window_icons()
                self._tray = _TrayWindow(self.icon_path, self._events)
                self._tray.start()
            except (OSError, RuntimeError) as exc:
                self._error = str(exc)
        if instance is not None:
            instance.bind(root, on_show)
        self._timer = root.after(80, self._drain_events)

    def _set_window_icons(self) -> None:
        assert self._api is not None
        self.root.update_idletasks()
        user = self._api.user
        self._window_hwnd = int(user.GetAncestor(self.root.winfo_id(), 2) or self.root.winfo_id())
        for kind, metric in ((ICON_BIG, 11), (ICON_SMALL, 49)):
            icon, owned = self._api.icon(self.icon_path, max(16, user.GetSystemMetrics(metric)))
            if icon:
                user.SendMessageW(self._window_hwnd, WM_SETICON, kind, icon)
                if owned:
                    self._native_icons.append(icon)
        self._taskbar_icon_set = len(self._native_icons) == 2

    def _drain_events(self) -> None:
        self._timer = None
        if self._closed:
            return
        while not self._closed:
            try:
                action = self._events.get_nowait()
            except queue.Empty:
                break
            callback = self._callbacks.get(action)
            if callback is not None:
                callback()
        if not self._closed:
            self._timer = self.root.after(80, self._drain_events)

    def set_status(self, text: str, running: bool = False) -> None:
        if not self._closed and self._tray is not None:
            self._tray.update(text, running)

    def hide(self) -> None:
        """Caller should detach any embedded native child before hiding."""
        if not self._closed:
            self.root.withdraw()

    def show(self) -> None:
        if not self._closed:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()

    def diagnostics(self) -> dict[str, object]:
        tray = self._tray
        return {
            "app_id": APP_ID,
            "identity_set": self._identity_set,
            "taskbar_icon_set": self._taskbar_icon_set,
            "window_hwnd": self._window_hwnd,
            "tray_ready": bool(tray and tray.ready.is_set()),
            "tray_icon_added": bool(tray and tray.icon_added),
            "tray_hwnd": tray.hwnd if tray else 0,
            "tooltip": tray.tooltip if tray else "",
            "running": bool(tray and tray.running),
            "closed": self._closed,
            "error": self._error or (tray.error if tray else ""),
        }

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._timer is not None:
            self.root.after_cancel(self._timer)
            self._timer = None
        if self._tray is not None:
            self._tray.close()
            # Bound the shutdown wait: a native menu can have a nested message
            # loop, and closing the UI must not block on Explorer indefinitely.
            self._tray.finished.wait(0.5)
        if self._api is not None:
            for kind in (ICON_BIG, ICON_SMALL):
                self._api.user.SendMessageW(self._window_hwnd, WM_SETICON, kind, 0)
            for icon in self._native_icons:
                self._api.user.DestroyIcon(icon)
            self._native_icons.clear()
        if self.instance is not None:
            self.instance.close()
