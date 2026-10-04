"""Native Tk surfaces and controls for the Chinese battle console."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

COLORS = {
    "sidebar": "#ffffff",
    "page": "#f3f6fc",
    "surface": "#ffffff",
    "ink": "#1e293b",
    "muted": "#64748b",
    "border": "#e2e8f0",
    "green": "#168264",
    "blue": "#3563e9",
    "accent": "#3563e9",
    "hero": "#ffffff",
    "hero_muted": "#64748b",
    "reward_surface": "#edf4ff",
    "red": "#c34e5b",
    "nav_active": "#edf2ff",
    "nav_muted": "#64748b",
    "cream": "#a8bdfb",
}
FONT = "Microsoft YaHei UI"
NUM_FONT = "Segoe UI"
NUM = NUM_FONT


def _parent_background(parent: tk.Misc) -> str:
    try:
        return str(parent.cget("bg"))
    except tk.TclError:
        return COLORS["page"]


def _rounded_points(width: int, height: int, radius: int, inset: int = 1) -> tuple[int, ...]:
    """Duplicate corner coordinates so Tk's spline preserves straight edges."""
    left = top = inset
    right, bottom = max(inset, width - inset), max(inset, height - inset)
    radius = max(0, min(radius, (right - left) // 2, (bottom - top) // 2))
    return (
        left + radius,
        top,
        right - radius,
        top,
        right,
        top,
        right,
        top + radius,
        right,
        bottom - radius,
        right,
        bottom,
        right - radius,
        bottom,
        left + radius,
        bottom,
        left,
        bottom,
        left,
        bottom - radius,
        left,
        top + radius,
        left,
        top,
    )


class RoundedPanel(tk.Canvas):
    """A soft bordered surface whose children remain normal Tk widgets."""

    def __init__(self, parent, *, fill: str, padding=20, radius=12, **kwargs):
        super().__init__(
            parent,
            bg=_parent_background(parent),
            highlightthickness=0,
            bd=0,
            autostyle=False,
            **kwargs,
        )
        self.fill = fill
        self.padding = padding
        self.radius = radius
        self.body = tk.Frame(self, bg=fill, bd=0, autostyle=False)
        self._body_id = self.create_window(padding, padding, window=self.body, anchor="nw")
        self.bind("<Configure>", self._layout)

    def _layout(self, event):
        self.delete("surface")
        self.create_polygon(
            _rounded_points(event.width, event.height, self.radius),
            smooth=True,
            splinesteps=32,
            fill=self.fill,
            outline=COLORS["border"],
            width=1,
            tags="surface",
        )
        self.tag_lower("surface")
        self.coords(self._body_id, self.padding, self.padding)
        self.itemconfigure(
            self._body_id,
            width=max(1, event.width - 2 * self.padding),
            height=max(1, event.height - 2 * self.padding),
        )


class PanelButton(tk.Canvas):
    """Rounded button with explicit colors, keyboard support and line icons."""

    def __init__(
        self,
        parent,
        *,
        text,
        command=None,
        width=160,
        height=42,
        variant="primary",
        icon=None,
        **kwargs,
    ):
        self._label = text
        self._command = command
        self._variant = variant
        self._icon = icon
        self._hover = False
        self._focused = False
        self._selected = False
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=_parent_background(parent),
            highlightthickness=0,
            bd=0,
            takefocus=1,
            cursor="hand2",
            autostyle=False,
            **kwargs,
        )
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Enter>", lambda _event: self._set_hover(True))
        self.bind("<Leave>", lambda _event: self._set_hover(False))
        self.bind("<FocusIn>", lambda _event: self._set_focus(True))
        self.bind("<FocusOut>", lambda _event: self._set_focus(False))
        self.bind("<Button-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Return>", self._keyboard_invoke)
        self.bind("<space>", self._keyboard_invoke)
        self._draw()

    def _set_hover(self, value):
        self._hover = value
        self._draw()

    def _set_focus(self, value):
        self._focused = value
        self._draw()

    def _press(self, _event):
        if self.cget("state") != "disabled":
            self.focus_set()

    def _release(self, event):
        if 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():
            self.invoke()

    def _keyboard_invoke(self, _event):
        self.invoke()
        return "break"

    def invoke(self):
        if self.cget("state") != "disabled" and self._command is not None:
            return self._command()
        return None

    def set_selected(self, selected: bool):
        self._selected = bool(selected)
        self._draw()

    def configure(self, cnf=None, **kwargs):
        if isinstance(cnf, str):
            return super().configure(cnf, **kwargs)
        options = dict(cnf or {})
        options.update(kwargs)
        if not options:
            return super().configure()
        if "text" in options:
            self._label = options.pop("text")
        if "command" in options:
            self._command = options.pop("command")
        if options:
            super().configure(**options)
        disabled = self.cget("state") == "disabled"
        super().configure(cursor="arrow" if disabled else "hand2", takefocus=0 if disabled else 1)
        self._draw()
        return None

    config = configure

    def _colors(self):
        if self.cget("state") == "disabled":
            return "#eef2f7", "#a0aec0", "#eef2f7"
        if self._variant == "nav":
            active = self._selected or self._hover
            fill = COLORS["nav_active"] if active else COLORS["sidebar"]
            return fill, COLORS["accent"] if active else COLORS["nav_muted"], fill
        if self._variant == "danger":
            return "#fff1f2" if self._hover else COLORS["surface"], COLORS["red"], "#f0cdd2"
        if self._variant == "outline":
            return "#f4f7fc" if self._hover else COLORS["surface"], COLORS["ink"], COLORS["border"]
        return "#2852d3" if self._hover else COLORS["accent"], COLORS["surface"], COLORS["accent"]

    def _draw(self):
        self.delete("button")
        width = max(self.winfo_width(), int(float(self.cget("width"))))
        height = max(self.winfo_height(), int(float(self.cget("height"))))
        fill, foreground, border = self._colors()
        self.create_polygon(
            _rounded_points(width, height, 8),
            smooth=True,
            splinesteps=32,
            fill=fill,
            outline=COLORS["cream"] if self._focused else border,
            width=2 if self._focused else 1,
            tags="button",
        )
        if self._variant == "nav":
            center = 44
            anchor = "w"
            icon_x = 25
        else:
            center = width / 2 + (10 if self._icon else 0)
            anchor = "center"
            icon_x = max(20, width / 2 - len(str(self._label)) * 6 - 13)
        if self._icon:
            self._draw_icon(icon_x, height / 2, foreground)
        self.create_text(
            center,
            height / 2,
            text=self._label,
            fill=foreground,
            font=(FONT, 10, "bold" if self._variant != "nav" or self._selected else "normal"),
            anchor=anchor,
            tags="button",
        )

    def _draw_icon(self, x: float, y: float, color: str):
        if self._icon == "play":
            self.create_polygon(x - 4, y - 6, x + 6, y, x - 4, y + 6, fill=color, outline="", tags="button")
        elif self._icon == "stop":
            self.create_rectangle(x - 4, y - 4, x + 4, y + 4, fill=color, outline="", tags="button")
        elif self._icon == "chart":
            self.create_line([x - 7, y - 7, x - 7, y + 7, x + 8, y + 7], fill=color, width=1.4, tags="button")
            self.create_line([x - 4, y + 3, x, y - 1, x + 3, y + 1, x + 7, y - 5], fill=color, width=1.6, tags="button")
        else:
            self.create_rectangle(x - 6, y - 7, x + 6, y + 7, outline=color, width=1.2, tags="button")
            for offset in (-3, 1, 5):
                self.create_line(x - 3, y + offset, x + 3, y + offset, fill=color, width=1.2, tags="button")


class StateChip(tk.Canvas):
    """Small updateable status marker that retains its own neutral margins."""

    def __init__(self, parent, *, width=22, height=24, bg, fg, text="·", **kwargs):
        self._chip_bg = bg
        self._chip_fg = fg
        self._label = text
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=_parent_background(parent),
            highlightthickness=0,
            bd=0,
            autostyle=False,
            **kwargs,
        )
        self.bind("<Configure>", lambda _event: self._draw())
        self._draw()

    def configure(self, cnf=None, **kwargs):
        if isinstance(cnf, str):
            return super().configure(cnf, **kwargs)
        options = dict(cnf or {})
        options.update(kwargs)
        if not options:
            return super().configure()
        for key, attribute in (("text", "_label"), ("bg", "_chip_bg"), ("fg", "_chip_fg")):
            if key in options:
                setattr(self, attribute, options.pop(key))
        if options:
            super().configure(**options)
        self._draw()
        return None

    config = configure

    def _draw(self):
        self.delete("chip")
        width = max(self.winfo_width(), int(float(self.cget("width"))))
        height = max(self.winfo_height(), int(float(self.cget("height"))))
        self.create_polygon(
            _rounded_points(width, height, 5),
            smooth=True,
            splinesteps=24,
            fill=self._chip_bg,
            outline="",
            tags="chip",
        )
        self.create_text(
            width / 2,
            height / 2,
            text=self._label,
            fill=self._chip_fg,
            font=(FONT, 8, "bold"),
            tags="chip",
        )


class ResultTree(ttk.Treeview):
    """Treeview with result-only badges; original column values remain intact."""

    def __init__(self, parent, **kwargs):
        self._badge_pool = []
        self._refresh_pending = None
        super().__init__(parent, **kwargs)
        for event in (
            "<Configure>",
            "<Expose>",
            "<MouseWheel>",
            "<ButtonRelease-1>",
            "<<TreeviewSelect>>",
            "<KeyRelease>",
        ):
            self.bind(event, self._queue_refresh, add="+")

    def _queue_refresh(self, _event=None):
        if self._refresh_pending is None:
            self._refresh_pending = self.after_idle(self.refresh_badges)

    def insert(self, *args, **kwargs):
        iid = super().insert(*args, **kwargs)
        self._queue_refresh()
        return iid

    def delete(self, *items):
        super().delete(*items)
        self._queue_refresh()

    def yview(self, *args):
        result = super().yview(*args)
        if args:
            self._queue_refresh()
        return result

    def xview(self, *args):
        result = super().xview(*args)
        if args:
            self._queue_refresh()
        return result

    def yview_moveto(self, fraction):
        super().yview_moveto(fraction)
        self._queue_refresh()

    def yview_scroll(self, number, what):
        super().yview_scroll(number, what)
        self._queue_refresh()

    def xview_moveto(self, fraction):
        super().xview_moveto(fraction)
        self._queue_refresh()

    def xview_scroll(self, number, what):
        super().xview_scroll(number, what)
        self._queue_refresh()

    def _select_badge(self, canvas, *, open_result=False):
        iid = getattr(canvas, "_row_id", None)
        if iid and self.exists(iid):
            self.selection_set(iid)
            self.focus(iid)
            self.focus_set()
            if open_result:
                self.event_generate("<<ResultOpen>>")

    def _new_badge(self):
        canvas = tk.Canvas(self, highlightthickness=0, bd=0, autostyle=False)
        canvas.bind("<Button-1>", lambda _event: self._select_badge(canvas))
        canvas.bind("<Double-Button-1>", lambda _event: self._select_badge(canvas, open_result=True))
        canvas.bind("<MouseWheel>", self._forward_badge_scroll)
        self._badge_pool.append(canvas)
        return canvas

    def _forward_badge_scroll(self, event):
        self.event_generate("<MouseWheel>", delta=event.delta)
        return "break"

    def refresh_badges(self):
        """Reuse at most sixty overlays, showing badges only for visible rows."""
        self._refresh_pending = None
        if not self.winfo_exists():
            return
        visible = []
        for iid in self.get_children():
            try:
                box = self.bbox(iid, "result")
            except tk.TclError:
                box = ()
            if box and box[2] > 4 and box[1] >= 0 and box[1] + box[3] <= self.winfo_height():
                visible.append((iid, box))
            if len(visible) >= 60:
                break
        selected = set(self.selection())
        for index, (iid, (x, y, width, height)) in enumerate(visible):
            canvas = self._badge_pool[index] if index < len(self._badge_pool) else self._new_badge()
            canvas._row_id = iid
            background = "#edf3ed" if iid in selected else COLORS["surface"]
            canvas.configure(bg=background, width=width, height=height)
            canvas.place(x=x, y=y, width=width, height=height)
            canvas.delete("all")
            result = str(self.set(iid, "result"))
            fill, foreground = {
                "胜利": ("#e9f3eb", COLORS["green"]),
                "失败": ("#f8ece8", COLORS["red"]),
                "未知": ("#eef0ec", COLORS["muted"]),
                "平局": ("#f5efdf", "#8a7546"),
            }.get(result, ("#eef0ec", COLORS["muted"]))
            badge_width = min(54, width - 8)
            left, top = (width - badge_width) / 2, max(2, (height - 24) / 2)
            points = _rounded_points(badge_width, min(24, height - 4), 6)
            shifted = [coordinate + (left if index % 2 == 0 else top) for index, coordinate in enumerate(points)]
            canvas.create_polygon(shifted, smooth=True, splinesteps=24, fill=fill, outline="")
            canvas.create_text(width / 2, height / 2, text=result, fill=foreground, font=(FONT, 9))
            tk.Misc.lift(canvas)
        for canvas in self._badge_pool[len(visible) :]:
            canvas.place_forget()
