"""Read-only, bounded ADB screen mirroring for the native battle console."""

from __future__ import annotations

import io
import queue
import subprocess
import threading
import time
import tkinter as tk
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageTk

from pyclashbot.interface.cn_console_theme import COLORS, FONT, PanelButton

if TYPE_CHECKING:
    from collections.abc import Callable

SCREEN_BACKGROUND = "#112821"
SCREEN_MUTED = "#92aaa0"
TARGET_FPS = 2.0
CAPTURE_TIMEOUT = 3.0
STALE_AFTER = 2.5


@dataclass(frozen=True)
class _CaptureResult:
    generation: int
    captured_at: float
    captured_wall_time: float
    image: Image.Image | None = None
    error: str | None = None
    duration: float = 0.0


class LiveEmulatorView(tk.Frame):
    """Show the existing emulator without sending input or changing its state.

    A single background thread captures at most two frames per second. Only the
    latest frame is queued, and all Tk calls and PhotoImage creation happen on
    the Tk thread. ``capture`` can return PNG bytes or a PIL image for offline
    inspection; the default runs only ``adb exec-out screencap -p``.
    """

    def __init__(
        self,
        parent: tk.Misc,
        adb_path: Path,
        serial: str,
        cwd: Path,
        autostart: bool = True,
        *,
        capture: Callable[[], bytes | Image.Image] | None = None,
    ) -> None:
        super().__init__(parent, bg=COLORS["surface"], bd=0, autostyle=False)
        self.adb_path = Path(adb_path)
        self.serial = serial
        self.cwd = Path(cwd)
        self._capture_callback = capture
        self._stop = threading.Event()
        self._active = threading.Event()
        self._wake = threading.Event()
        self._process_lock = threading.Lock()
        self._capture_process: subprocess.Popen | None = None
        self._results: queue.Queue[_CaptureResult] = queue.Queue(maxsize=1)
        self._generation = 0
        self._closed = False
        self._after_id: str | None = None
        self._state = "connecting" if autostart else "paused"
        self._last_image: Image.Image | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._frame_count = 0
        self._frame_size: tuple[int, int] | None = None
        self._last_frame_at: float | None = None
        self._last_wall_time: float | None = None
        self._last_capture_duration: float | None = None
        self._frame_times: deque[float] = deque(maxlen=12)
        self._error: str | None = None
        if autostart:
            self._active.set()
        self._build()
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._thread = threading.Thread(target=self._capture_loop, name="emulator-live-view", daemon=True)
        self._thread.start()
        self._poll()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        header = tk.Frame(self, bg=COLORS["surface"], autostyle=False)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        header.columnconfigure(0, weight=1)
        tk.Label(
            header,
            text="实时对战",
            font=(FONT, 13, "bold"),
            bg=COLORS["surface"],
            fg=COLORS["ink"],
            autostyle=False,
        ).grid(row=0, column=0, sticky="w")
        self._status_label = tk.Label(
            header,
            text="连接中",
            font=(FONT, 9),
            padx=9,
            pady=4,
            bg=COLORS["reward_surface"],
            fg=COLORS["green"],
            autostyle=False,
        )
        self._status_label.grid(row=0, column=1, sticky="e")
        tk.Label(
            self,
            text="模拟器画面 · 实时同步",
            anchor="w",
            font=(FONT, 9),
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            autostyle=False,
        ).grid(row=1, column=0, sticky="ew", pady=(0, 12))
        self.canvas = tk.Canvas(
            self,
            bg=SCREEN_BACKGROUND,
            highlightthickness=0,
            bd=0,
            width=320,
            height=483,
            autostyle=False,
        )
        self.canvas.grid(row=2, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda _event: self._render())
        stats = tk.Frame(self, bg=COLORS["surface"], autostyle=False)
        stats.grid(row=3, column=0, sticky="ew", pady=(11, 10))
        stats.columnconfigure(1, weight=1)
        self._fps_label = tk.Label(
            stats,
            text="— FPS",
            anchor="w",
            font=(FONT, 9, "bold"),
            bg=COLORS["surface"],
            fg=COLORS["ink"],
            autostyle=False,
        )
        self._fps_label.grid(row=0, column=0, sticky="w")
        self._updated_label = tk.Label(
            stats,
            text="等待首帧",
            anchor="e",
            font=(FONT, 9),
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            autostyle=False,
        )
        self._updated_label.grid(row=0, column=1, sticky="e")
        actions = tk.Frame(self, bg=COLORS["surface"], autostyle=False)
        actions.grid(row=4, column=0, sticky="ew")
        actions.columnconfigure((0, 1), weight=1, uniform="live-actions")
        self.pause_button = PanelButton(
            actions,
            text="暂停画面" if self._active.is_set() else "恢复画面",
            command=self.toggle_pause,
            width=120,
            height=36,
            variant="outline",
        )
        self.pause_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.reconnect_button = PanelButton(
            actions,
            text="重新连接",
            command=self.reconnect,
            width=120,
            height=36,
            variant="outline",
        )
        self.reconnect_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        tk.Label(
            self,
            text="暂停画面不影响机器人对战",
            anchor="w",
            font=(FONT, 8),
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            autostyle=False,
        ).grid(row=5, column=0, sticky="ew", pady=(9, 0))

    def _capture_png(self) -> bytes:
        """Own only this capture subprocess; never manage the ADB server."""
        command = [str(self.adb_path), "-s", self.serial, "exec-out", "screencap", "-p"]
        with self._process_lock:
            if self._stop.is_set():
                raise RuntimeError("画面窗口已关闭")
            process = subprocess.Popen(
                command,
                cwd=self.cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._capture_process = process
        try:
            output, _error = process.communicate(timeout=CAPTURE_TIMEOUT)
            if process.returncode != 0 or not output:
                raise RuntimeError("模拟器未连接 · 正在等待画面")
            return output
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise RuntimeError("画面读取超时 · 正在重试") from None
        finally:
            with self._process_lock:
                self._capture_process = None

    @staticmethod
    def _decode(data: bytes | Image.Image) -> Image.Image:
        if isinstance(data, Image.Image):
            return data.convert("RGB").copy()
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            return image.convert("RGB")

    def _offer(self, result: _CaptureResult) -> None:
        try:
            self._results.get_nowait()
        except queue.Empty:
            pass
        self._results.put_nowait(result)

    def _capture_loop(self) -> None:
        while not self._stop.is_set():
            if not self._active.is_set():
                self._wake.wait(0.5)
                self._wake.clear()
                continue
            generation = self._generation
            started = time.monotonic()
            try:
                data = self._capture_callback() if self._capture_callback is not None else self._capture_png()
                image = self._decode(data)
                result = _CaptureResult(
                    generation,
                    time.monotonic(),
                    time.time(),
                    image=image,
                    duration=time.monotonic() - started,
                )
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
                result = _CaptureResult(
                    generation,
                    time.monotonic(),
                    time.time(),
                    error=str(error),
                    duration=time.monotonic() - started,
                )
            if not self._stop.is_set() and self._active.is_set() and generation == self._generation:
                self._offer(result)
            interval = 2.0 if result.error else 1.0 / TARGET_FPS
            self._wake.wait(max(0.01, interval - (time.monotonic() - started)))
            self._wake.clear()

    def _poll(self) -> None:
        if self._closed:
            return
        self._after_id = None
        try:
            result = self._results.get_nowait()
        except queue.Empty:
            result = None
        if result is not None and self._active.is_set() and result.generation == self._generation:
            self._last_capture_duration = result.duration
            if result.image is not None:
                self._last_image = result.image
                self._last_frame_at = result.captured_at
                self._last_wall_time = result.captured_wall_time
                self._frame_size = result.image.size
                self._frame_count += 1
                self._frame_times.append(result.captured_at)
                self._error = None
                self._state = "live"
            else:
                self._state = "offline"
                self._error = result.error
                self._last_image = None
                self._photo = None
                self._frame_times.clear()
            self._render()
        if self._state == "live" and self._frame_age() > STALE_AFTER:
            self._state = "stale"
            self._render()
        self._update_labels()
        self._after_id = self.after(100, self._poll)

    def _frame_age(self) -> float:
        return time.monotonic() - self._last_frame_at if self._last_frame_at is not None else float("inf")

    def _fps(self) -> float:
        if self._state != "live" or len(self._frame_times) < 2:
            return 0.0
        span = self._frame_times[-1] - self._frame_times[0]
        return (len(self._frame_times) - 1) / span if span > 0 else 0.0

    def _update_labels(self) -> None:
        status, foreground, background = {
            "connecting": ("连接中", COLORS["green"], COLORS["reward_surface"]),
            "live": ("● 实时", COLORS["green"], COLORS["reward_surface"]),
            "paused": ("画面已暂停", "#8a7546", "#f5efdf"),
            "offline": ("等待连接", COLORS["red"], "#f8ece8"),
            "stale": ("画面已中断", COLORS["red"], "#f8ece8"),
            "closed": ("已关闭", COLORS["muted"], COLORS["page"]),
        }[self._state]
        self._status_label.configure(text=status, fg=foreground, bg=background)
        self._fps_label.configure(text=f"{self._fps():.1f} FPS" if self._frame_count else "— FPS")
        if self._last_wall_time is None:
            updated = "等待首帧"
        elif self._state == "live":
            updated = f"更新于 {time.strftime('%H:%M:%S', time.localtime(self._last_wall_time))}"
        else:
            updated = f"最后画面 {time.strftime('%H:%M:%S', time.localtime(self._last_wall_time))}"
        self._updated_label.configure(text=updated)

    def _render(self) -> None:
        if self._closed:
            return
        width, height = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        self.canvas.delete("all")
        if self._last_image is not None:
            source_width, source_height = self._last_image.size
            scale = min(width / source_width, height / source_height)
            image = self._last_image.resize(
                (max(1, round(source_width * scale)), max(1, round(source_height * scale))),
                Image.Resampling.LANCZOS,
            )
            self._photo = ImageTk.PhotoImage(image, master=self.canvas)
            self.canvas.create_image(width / 2, height / 2, image=self._photo, anchor="center")
        if self._state != "live":
            message, detail = {
                "paused": ("画面已暂停", "机器人继续按原状态运行"),
                "connecting": ("正在连接模拟器", "等待实时画面"),
                "offline": ("等待模拟器画面", "连接恢复后自动显示"),
                "stale": ("画面更新已中断", "当前显示的是最后一帧"),
            }.get(self._state, ("", ""))
            box_width = min(282, max(1, width - 24))
            center_x, center_y = width / 2, height / 2
            self.canvas.create_rectangle(
                center_x - box_width / 2,
                center_y - 48,
                center_x + box_width / 2,
                center_y + 48,
                fill=SCREEN_BACKGROUND,
                outline="#345248",
                width=1,
            )
            self.canvas.create_text(
                center_x,
                center_y - 14,
                text=message,
                fill="#f4f6f2",
                font=(FONT, 12, "bold"),
                width=max(1, box_width - 18),
            )
            self.canvas.create_text(
                center_x,
                center_y + 16,
                text=detail,
                fill=SCREEN_MUTED,
                font=(FONT, 9),
                width=max(1, box_width - 18),
            )

    def pause(self) -> None:
        """Pause only this view; invalidate any in-flight capture result."""
        if self._closed:
            return
        self._active.clear()
        self._generation += 1
        self._state = "paused"
        self._frame_times.clear()
        self.pause_button.configure(text="恢复画面")
        self._wake.set()
        self._update_labels()
        self._render()

    def resume(self) -> None:
        """Resume screenshot reads without starting or reconnecting a device."""
        if self._closed:
            return
        self._generation += 1
        self._state = "connecting"
        self._error = None
        self._last_image = None
        self._photo = None
        self._frame_times.clear()
        self.pause_button.configure(text="暂停画面")
        self._active.set()
        self._wake.set()
        self._update_labels()
        self._render()

    def toggle_pause(self) -> None:
        """Toggle this view's refresh independently of the bot controls."""
        if self._active.is_set():
            self.pause()
        else:
            self.resume()

    def reconnect(self) -> None:
        """Retry screen reads immediately; do not run ``adb connect``."""
        self.resume()

    def diagnostics(self) -> dict:
        """Return observed view state without exposing or modifying a device."""
        age = self._frame_age()
        return {
            "serial": self.serial,
            "source": "injected_capture" if self._capture_callback is not None else "adb_screencap",
            "state": self._state,
            "frame_count": self._frame_count,
            "frame_size": self._frame_size,
            "fps": round(self._fps(), 2),
            "target_fps": TARGET_FPS,
            "frame_age_seconds": round(age, 3) if self._last_frame_at is not None else None,
            "last_update_epoch": self._last_wall_time,
            "capture_duration_seconds": self._last_capture_duration,
            "capture_thread_alive": self._thread.is_alive(),
            "paused": not self._active.is_set(),
            "closed": self._closed,
            "queue_size": self._results.qsize(),
            "error": self._error,
            "read_only": True,
        }

    def close(self) -> None:
        """Cancel UI updates and this view's capture, leaving the bot untouched."""
        if self._closed:
            return
        self._closed = True
        self._state = "closed"
        self._generation += 1
        self._stop.set()
        self._active.clear()
        self._wake.set()
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        with self._process_lock:
            process = self._capture_process
            if process is not None and process.poll() is None:
                try:
                    process.terminate()
                except OSError:
                    pass

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is self:
            self.close()
