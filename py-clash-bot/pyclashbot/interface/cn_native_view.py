"""Embed MEmu's actual native window tree without capturing frames."""

# UI copy deliberately uses Chinese fullwidth punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import math
import os
import tkinter as tk
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path

import psutil

from pyclashbot.interface.cn_console_theme import COLORS, FONT, PanelButton
from pyclashbot.interface.cn_native_window_api import (
    Win32WindowAPI,
    WindowSnapshot,
    enable_native_embedding_dpi,
)
from pyclashbot.utils.persistence import atomic_write_json, read_validated_json
from pyclashbot.utils.process_ownership import ExclusiveFileLock, OwnershipError

__all__ = ["NativeEmulatorView", "NativeWindowHost", "Win32WindowAPI", "WindowSnapshot", "enable_native_embedding_dpi"]

WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WINDOW_CHROME = 0x00C00000 | 0x00040000 | 0x00080000 | 0x00020000 | 0x00010000
WS_EX_APPWINDOW = 0x00040000


class NativeWindowHost:
    """Keep the original state until restore succeeds, including after failures."""

    def __init__(self, api, executable: Path, recovery_path=None) -> None:
        self.api = api
        self.executable = executable
        self.snapshot_state: WindowSnapshot | None = None
        self.parent = 0
        self.embedded = False
        self.last_layout: tuple[int, int, int, int] | None = None
        self.recovery_path = recovery_path
        self._window_created_at = None
        self._ownership_lock = (
            ExclusiveFileLock(recovery_path.with_suffix(".owner.lock")) if recovery_path is not None else None
        )
        self._lock_owned = False

    def _recover_abandoned_host(self):
        path = self.recovery_path
        if path is None or not path.exists():
            return
        try:
            row = read_validated_json(
                path,
                lambda value: (
                    isinstance(value, dict)
                    and type(value.get("schema")) is int
                    and value["schema"] == 1
                    and isinstance(value.get("restored"), bool)
                ),
            )
        except ValueError as error:
            raise RuntimeError("窗口恢复记录无效; 已保留原文件") from error
        if row.get("restored"):
            return
        if (
            not isinstance(row.get("owner_pid"), int)
            or isinstance(row["owner_pid"], bool)
            or row["owner_pid"] < 1
            or not isinstance(row.get("owner_created_at"), (int, float))
            or not isinstance(row.get("window_created_at"), (int, float))
            or any(
                isinstance(row[name], bool) or not math.isfinite(row[name]) or row[name] <= 0
                for name in ("owner_created_at", "window_created_at")
            )
        ):
            raise RuntimeError("窗口恢复身份信息不完整; 已保留原文件")
        try:
            owner = psutil.Process(row["owner_pid"])
            if abs(owner.create_time() - row["owner_created_at"]) < 0.01:
                raise RuntimeError("模拟器已由另一控制台托管; 请先关闭原控制台")
        except psutil.NoSuchProcess:
            pass
        except psutil.Error as error:
            raise RuntimeError("无法核实旧控制台进程; 已保留恢复记录") from error
        try:
            if Path(row["executable"]).resolve() != self.executable.resolve():
                raise ValueError("executable mismatch")
            saved = WindowSnapshot(**row["snapshot"])
            if not all(
                isinstance(value, int) and not isinstance(value, bool)
                for value in (saved.hwnd, saved.pid, saved.parent, saved.style, saved.ex_style)
            ):
                raise ValueError("invalid window identity")
            rects = [(saved.rect, 4), (saved.content_rect, 4)]
            if any(
                value is not None
                and (
                    not isinstance(value, (tuple, list))
                    or len(value) != count
                    or not all(isinstance(item, int) and not isinstance(item, bool) for item in value)
                )
                for value, count in rects
            ):
                raise ValueError("invalid geometry")
            if saved.rect[2] <= saved.rect[0] or saved.rect[3] <= saved.rect[1]:
                raise ValueError("empty geometry")
            if saved.content_rect is not None and (saved.content_rect[2] <= 0 or saved.content_rect[3] <= 0):
                raise ValueError("empty renderer")
            placement = saved.placement
            if (
                not isinstance(placement, dict)
                or any(
                    not isinstance(placement.get(name), int) or isinstance(placement[name], bool)
                    for name in ("flags", "showCmd")
                )
                or any(
                    not isinstance(placement.get(name), (tuple, list))
                    or len(placement[name]) != count
                    or not all(isinstance(value, int) and not isinstance(value, bool) for value in placement[name])
                    for name, count in (("ptMinPosition", 2), ("ptMaxPosition", 2), ("rcNormalPosition", 4))
                )
            ):
                raise ValueError("invalid placement")
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError("窗口恢复记录无效; 已保留原文件") from error
        if self.api.is_window(saved.hwnd, saved.pid):
            try:
                same_process = abs(psutil.Process(saved.pid).create_time() - row["window_created_at"]) < 0.01
            except psutil.Error:
                same_process = False
            if not same_process:
                raise RuntimeError("无法核实旧模拟器窗口身份; 保留恢复记录")
            if self.api.window_executable(saved.hwnd) != self.executable.resolve():
                raise RuntimeError("旧窗口不属于本模拟器; 已拒绝还原")
            self.api.restore(saved.hwnd, saved)
        atomic_write_json(path, {"schema": 1, "restored": True})

    def _persist_original_window(self, saved):
        try:
            self._window_created_at = psutil.Process(saved.pid).create_time()
        except psutil.Error as error:
            raise RuntimeError("无法确认模拟器进程身份; 已停止嵌入") from error
        if self.recovery_path is None:
            return
        atomic_write_json(
            self.recovery_path,
            {
                "schema": 1,
                "restored": False,
                "owner_pid": os.getpid(),
                "owner_created_at": psutil.Process().create_time(),
                "window_created_at": self._window_created_at,
                "executable": str(self.executable.resolve()),
                "snapshot": asdict(saved),
            },
        )

    def _mark_restored(self):
        if self.recovery_path is not None:
            atomic_write_json(self.recovery_path, {"schema": 1, "restored": True}, backup=True)

    def _release_ownership(self):
        if self._ownership_lock is not None and self._lock_owned:
            self._ownership_lock.release()
            self._lock_owned = False

    def _identity_matches(self, saved):
        try:
            return (
                self._window_created_at is not None
                and abs(psutil.Process(saved.pid).create_time() - self._window_created_at) < 0.01
                and self.api.window_executable(saved.hwnd) == self.executable.resolve()
            )
        except psutil.Error:
            return False

    def attach(self, parent: int, width: int, height: int) -> None:
        if self._ownership_lock is not None and not self._lock_owned:
            try:
                self._ownership_lock.acquire()
                self._lock_owned = True
            except OwnershipError as error:
                raise RuntimeError("模拟器已由另一控制台托管; 请先关闭原控制台") from error
        try:
            self._attach_owned(parent, width, height)
        except BaseException:
            if self.snapshot_state is None:
                self._release_ownership()
            raise

    def _attach_owned(self, parent: int, width: int, height: int) -> None:
        saved = self.snapshot_state
        if saved is None:
            self._recover_abandoned_host()
        if saved is not None:
            if self.api.is_window(saved.hwnd, saved.pid):
                if self.embedded and self.parent == parent:
                    self.resize(width, height)
                    return
                self.detach(keep_ownership=True)
            else:
                self.snapshot_state = None
                self.embedded = False
                self.last_layout = None
        hwnd = self.api.find_window(self.executable)
        if hwnd is None:
            raise RuntimeError("模拟器窗口尚未打开")
        original = self.api.snapshot(hwnd)
        self.snapshot_state = saved = replace(original, placement=deepcopy(original.placement))
        self._persist_original_window(saved)
        self.parent = parent
        try:
            self.api.set_style(hwnd, (saved.style & ~(WS_POPUP | WINDOW_CHROME)) | WS_CHILD)
            self.api.set_ex_style(hwnd, saved.ex_style & ~WS_EX_APPWINDOW)
            self.api.set_parent(hwnd, parent)
            self.embedded = True
            self.resize(width, height)
        except (OSError, RuntimeError):
            self.embedded = False
            # A failed rollback retains saved state so close can retry safely.
            self.detach()
            raise

    def resize(self, width: int, height: int) -> None:
        saved = self.snapshot_state
        if not self.embedded or saved is None:
            return
        if not self.api.is_window(saved.hwnd, saved.pid):
            self._mark_restored()
            self.snapshot_state = None
            self.embedded = False
            self.parent = 0
            self.last_layout = None
            raise RuntimeError("模拟器窗口已关闭，等待重新嵌入")
        if not self._identity_matches(saved):
            raise RuntimeError("模拟器窗口身份已变化; 已停止尺寸调整")
        left, top, right, bottom = saved.rect
        outer_width, outer_height = right - left, bottom - top
        content_x, content_y, source_width, source_height = saved.content_rect or (0, 0, outer_width, outer_height)
        scale = min(max(1, width) / source_width, max(1, height) / source_height)
        game_width = max(1, round(source_width * scale))
        game_height = max(1, round(source_height * scale))
        # Keep the whole Qt/headless tree. Parent clipping hides window chrome.
        layout = (
            -content_x,
            -content_y,
            game_width + outer_width - source_width,
            game_height + outer_height - source_height,
        )
        if layout != self.last_layout:
            self.api.move_window(saved.hwnd, *layout)
            resize_surfaces = getattr(self.api, "resize_render_surfaces", None)
            if resize_surfaces is not None:
                resize_surfaces(saved.hwnd)
            self.last_layout = layout

    def detach(self, *, keep_ownership=False) -> None:
        saved = self.snapshot_state
        if saved is None:
            if not keep_ownership:
                self._release_ownership()
            return
        if self.api.is_window(saved.hwnd, saved.pid):
            if not self._identity_matches(saved):
                raise RuntimeError("模拟器窗口身份已变化; 已拒绝还原并保留恢复记录")
            self.api.restore(saved.hwnd, saved)
        self._mark_restored()
        self.snapshot_state = None
        self.embedded = False
        self.parent = 0
        self.last_layout = None
        if not keep_ownership:
            self._release_ownership()

    def diagnostics(self) -> dict:
        saved = self.snapshot_state
        return {
            "source": "native_window",
            "embedded": self.embedded,
            "window_handle": saved.hwnd if saved else None,
            "window_pid": saved.pid if saved else None,
            "host_handle": self.parent or None,
            "native_layout": self.last_layout,
            "original_rect": saved.rect if saved else None,
            "original_content_rect": saved.content_rect if saved else None,
            "frame_capture": False,
            "captures_per_second": 0,
            "game_input_sent": False,
        }


class NativeEmulatorView(tk.Frame):
    """A Tk viewport hosting the original MEmu window instead of a video copy."""

    def __init__(
        self, parent, emulator_path: Path, serial: str, cwd: Path, *, api=None, autostart=True, recovery_path=None
    ):
        super().__init__(parent, bg=COLORS["surface"], bd=0, autostyle=False)
        self.serial = serial
        self.cwd = cwd
        self.host = NativeWindowHost(api or Win32WindowAPI(), emulator_path, recovery_path)
        self._closed = False
        self._state = "connecting" if autostart else "detached"
        self._error = None
        self._resize_id = None
        self._poll_id = None
        self._build()
        self.viewport.bind("<Configure>", self._schedule_resize)
        self._poll_id = self.after(150, self._poll)

    def _label(self, parent, text, *, size=9, bold=False, color=None):
        return tk.Label(
            parent,
            text=text,
            anchor="w",
            bg=COLORS["surface"],
            autostyle=False,
            fg=color or COLORS["muted"],
            font=(FONT, size, "bold" if bold else "normal"),
        )

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        header = tk.Frame(self, bg=COLORS["surface"], autostyle=False)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self._label(header, "实时对战", size=13, bold=True, color=COLORS["ink"]).pack(side="left")
        self.status_label = self._label(header, "正在嵌入", color=COLORS["green"])
        self.status_label.pack(side="right")
        self._label(self, "游戏画面与操作实时同步").grid(row=1, column=0, sticky="ew", pady=(0, 12))
        self.viewport = tk.Frame(self, width=320, height=483, bg="#13213b", bd=0, autostyle=False)
        self.viewport.grid(row=2, column=0, sticky="nsew")
        self.native_surface = tk.Frame(self.viewport, bg="#13213b", bd=0, autostyle=False)
        self.native_surface.place(x=0, y=0, width=1, height=1)
        self.placeholder = tk.Label(
            self.viewport,
            text="正在嵌入模拟器窗口…",
            bg="#13213b",
            fg="#dfeae3",
            font=(FONT, 10),
            autostyle=False,
            wraplength=250,
        )
        self.placeholder.place(relx=0.5, rely=0.5, anchor="center")
        self._label(self, "游戏窗口", bold=True, color=COLORS["ink"]).grid(row=3, column=0, sticky="w", pady=(11, 10))
        actions = tk.Frame(self, bg=COLORS["surface"], autostyle=False)
        actions.grid(row=4, column=0, sticky="ew")
        actions.columnconfigure((0, 1), weight=1, uniform="native-actions")
        self.popout_button = PanelButton(
            actions, text="弹出模拟器", command=self.detach, width=120, height=36, variant="outline"
        )
        self.popout_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.embed_button = PanelButton(
            actions, text="重新嵌入", command=self.attach, width=120, height=36, variant="outline"
        )
        self.embed_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        self._label(self, "收进托盘后，游戏回到独立窗口", size=9).grid(row=5, column=0, sticky="ew", pady=(9, 0))

    def _show_state(self):
        embedded = self.host.embedded
        self.status_label.configure(
            text="● 已嵌入" if embedded else "独立窗口" if self._state == "detached" else "等待嵌入",
            fg=COLORS["green"] if embedded else COLORS["muted"],
        )
        self.popout_button.configure(state="normal" if embedded else "disabled")
        if embedded:
            self.placeholder.place_forget()
        else:
            self.placeholder.configure(text=self._error or "模拟器已弹出\n点击重新嵌入可放回右侧")
            self.placeholder.place(relx=0.5, rely=0.5, anchor="center")

    def attach(self):
        if self._closed:
            return
        try:
            self.host.attach(self.native_surface.winfo_id(), self.viewport.winfo_width(), self.viewport.winfo_height())
            self._resize()
        except (OSError, RuntimeError) as error:
            self._error = str(error)
            self._state = "offline"
        else:
            self._error = None
            self._state = "embedded"
        self._show_state()

    def detach(self):
        try:
            self.host.detach()
        except (OSError, RuntimeError) as error:
            self._error = f"还原失败，请重试：{error}"
        else:
            self._error = None
            self._state = "detached"
        self._show_state()

    def _schedule_resize(self, _event=None):
        if self._closed:
            return
        if self._resize_id:
            self.after_cancel(self._resize_id)
        self._resize_id = self.after(50, self._resize)

    def _resize(self):
        self._resize_id = None
        try:
            width, height = self.viewport.winfo_width(), self.viewport.winfo_height()
            saved = self.host.snapshot_state
            if saved is not None:
                source_width, source_height = (
                    saved.content_rect[2:]
                    if saved.content_rect is not None
                    else (saved.rect[2] - saved.rect[0], saved.rect[3] - saved.rect[1])
                )
                scale = min(max(1, width) / source_width, max(1, height) / source_height)
                surface_width = max(1, round(source_width * scale))
                surface_height = max(1, round(source_height * scale))
                self.native_surface.place(
                    x=(width - surface_width) // 2,
                    y=(height - surface_height) // 2,
                    width=surface_width,
                    height=surface_height,
                )
                self.host.resize(surface_width, surface_height)
        except (OSError, RuntimeError) as error:
            self._error = str(error)
            self._state = "offline"
        self._show_state()

    def _poll(self):
        self._poll_id = None
        if self._closed:
            return
        saved = self.host.snapshot_state
        if saved is not None and not self.host.api.is_window(saved.hwnd, saved.pid):
            try:
                self.host.detach()
            except (OSError, RuntimeError) as error:
                self._error = str(error)
            self._state = "offline"
        if self._state in ("connecting", "offline"):
            self.attach()
        elif self.host.embedded and saved is not None:
            resize_surfaces = getattr(self.host.api, "resize_render_surfaces", None)
            if resize_surfaces is not None:
                try:
                    resize_surfaces(saved.hwnd)
                except (OSError, RuntimeError) as error:
                    self._error = str(error)
        self._poll_id = self.after(1000, self._poll)

    def diagnostics(self):
        return {
            **self.host.diagnostics(),
            "state": self._state,
            "serial": self.serial,
            "closed": self._closed,
            "error": self._error,
            "viewport_size": [self.viewport.winfo_width(), self.viewport.winfo_height()],
            "native_surface_size": [self.native_surface.winfo_width(), self.native_surface.winfo_height()],
        }

    def close(self):
        if self._closed:
            return
        # A failed restore must propagate; the owner must keep its Tk host alive.
        self.host.detach()
        self._closed = True
        self._state = "closed"
        for callback in (self._poll_id, self._resize_id):
            if callback is not None:
                self.after_cancel(callback)
        self._poll_id = self._resize_id = None
