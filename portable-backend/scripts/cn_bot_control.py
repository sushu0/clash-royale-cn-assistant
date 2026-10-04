"""Small Windows control window for the Tencent Clash Royale battle loop."""

# Chinese UI copy deliberately uses fullwidth punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import sqlite3
import subprocess
import sys
import threading
import time
import tkinter as tk
from contextlib import nullcontext
from pathlib import Path
from time import time_ns
from tkinter import font as tkfont
from tkinter import messagebox

import psutil
import ttkbootstrap as ttk

from pyclashbot.interface.cn_console_theme import (
    COLORS,
    FONT,
    PanelButton,
    ResultTree,
    RoundedPanel,
    StateChip,
)
from pyclashbot.interface.cn_desktop_shell import DesktopShell, acquire_single_instance, set_app_identity
from pyclashbot.interface.cn_native_view import NativeEmulatorView, enable_native_embedding_dpi
from pyclashbot.utils.battle_history import BattleHistory
from pyclashbot.utils.cn_error_report import ErrorReporter, list_error_reports
from pyclashbot.utils.persistence import atomic_write_json
from pyclashbot.utils.process_ownership import verified_process
from pyclashbot.utils.runtime_config import RESOURCE_ROOT, component_command, load_runtime_config

REPO = RESOURCE_ROOT
RUNTIME = load_runtime_config()
TASK_ROOT = RUNTIME.data_root
WORK = TASK_ROOT / "work"
OUTPUTS = TASK_ROOT / "outputs"
PYTHON = RUNTIME.python
ADB = RUNTIME.adb
MEMUC = RUNTIME.memuc
WATCHDOG = REPO / "scripts" / "watch_cn_1v1.py"
STOP = REPO / "scripts" / "stop_cn_1v1.py"
PID_FILE = WORK / "bot-processes.json"
BATTLE_LOG = OUTPUTS / "cn-battles-live.log"
WATCHDOG_LOG = OUTPUTS / "cn-watchdog.log"
SERIAL = RUNTIME.serial
PACKAGE = "com.tencent.tmgp.supercell.clashroyale"
HISTORY_DB = OUTPUTS / "cn-battle-history.sqlite3"
SCOPES = {"随机卡组": "random", "567 历史": "567", "野猪历史": "hog", "全部历史": "all"}
RANDOM_STATUS = OUTPUTS / "random-mastery-live-status.json"
RANDOM_TRACE = OUTPUTS / "cn-random-mastery.jsonl"
REWARDS_TRACE = OUTPUTS / "cn-mastery-rewards.jsonl"
STRATEGY_SELECTION = WORK / "bot-selected-strategy.txt"
FRONTEND_STATE = WORK / "random-frontend-state.json"
RANDOM_PHASES = {
    "starting": "准备随机卡组循环",
    "generating_deck": "正在生成新卡组",
    "matching": "正在匹配经典 1V1",
    "battle": "随机卡组对战中",
    "returning": "正在退出结算与奖励",
    "mastery": "正在检查领取全部",
    "paused": "异常已暂停",
    "stopped": "已停止",
}
CARD_NAMES = {
    "pekka": "皮卡超人",
    "goblin_giant": "哥布林巨人",
    "goblin_machine": "哥布林机甲",
    "baby_dragon": "飞龙宝宝",
    "mega_minion": "重甲亡灵",
    "bomber": "炸弹兵",
    "arrows": "万箭齐发",
    "zap": "电击法术",
}
CATEGORY_NAMES = {
    "defense": "防守",
    "defense_cycle": "救急换牌",
    "defense_support": "防守支援",
    "attack": "主动进攻",
    "counterpush": "防守反打",
    "support": "跟进支援",
    "prepare": "后场组织",
    "building": "建筑拉扯",
    "cycle": "低费轮转",
    "siege": "建筑推进",
    "remote": "定点进攻",
    "spell": "法术处理",
    "buff": "增益支援",
}
ACTION_PHASES = {
    "selecting": "正在选牌",
    "deploying": "正在下牌",
    "confirmed": "下牌已确认",
    "unconfirmed": "继续观察",
    "battle_ended": "对局已结束",
}
STATUS_COLORS = {
    "running": ("运行中", "#e4f6e9", "#166534"),
    "starting": ("启动／恢复中", "#fff4d6", "#925f00"),
    "stopped": ("已停止", "#eef0f3", "#53606d"),
    "paused": ("异常暂停", "#fff4d6", "#925f00"),
}


def rate_text(summary):
    return "—" if summary["win_rate"] is None else f"{summary['win_rate']:.1%}"


def policy_text(policy):
    if policy.startswith("random-mastery"):
        version = re.search(r"-v(\d+)-", policy)
        return "随机卡组 · 领取全部" + (f" · v{version.group(1)}" if version else "")
    version = re.search(r"double-air-567-(v[\d.]+)", policy)
    return f"567 双空军 · {version.group(1).rstrip('.')}" if version else policy


def display_event(line: str) -> tuple[str, str, str] | None:
    """Format existing events for people without changing the on-disk log."""
    stamp = line[11:19] if re.match(r"\d{4}-\d{2}-\d{2} ", line) else ""
    message = re.split(r" (?:INFO|WARNING|ERROR) ", line, maxsplit=1)[-1]
    if "对战开始" in message:
        match = re.search(r"场次=(\d+)", message)
        return stamp, "对战", f"第 {match.group(1)} 场对战开始" if match else message
    if "对战结束" in message:
        result = re.search(r"结果=(\S+)", message)
        count = re.search(r"已完成=(\d+)", message)
        confirmation = re.search(r"出牌确认=(\S+)", message)
        label = result.group(1) if result else "结束"
        details = f"第 {count.group(1)} 场已完成" if count else "本场已完成"
        if confirmation:
            details += f"  ·  出牌确认 {confirmation.group(1)}"
        return stamp, label, details
    if "恢复/重启" in message or " ERROR " in line or " WARNING " in line:
        return stamp, "恢复" if "恢复/重启" in message else "提醒", message
    if "国服 1v1 连续对战已启动" in message:
        return stamp, "启动", "机器人已启动，正在准备对战"
    if "限量验收完成" in message:
        return stamp, "完成", "本轮对战已完成，回到大厅后正常停止"
    if "里程碑" in message or "奖励" in message:
        return stamp, "记录", message
    return None


def _is_our_process(pid: int, script_name: str, created_at=None) -> bool:
    return verified_process(pid, REPO / "scripts" / script_name, created_at) is not None


def bot_state() -> str:
    try:
        state = json.loads(PID_FILE.read_text(encoding="utf-8"))
        watchdog = _is_our_process(int(state["watchdog_pid"]), "watch_cn_1v1.py", state.get("watchdog_created_at"))
        runner = _is_our_process(int(state["runner_pid"]), "run_cn_1v1.py", state.get("runner_created_at"))
    except (OSError, ValueError, KeyError, TypeError):
        return "stopped"
    if runner:
        return "running"
    if not watchdog and state.get("exit_reason") == "user_stopped":
        return "stopped"
    if not watchdog and state.get("phase") == "paused":
        return "paused"
    if not watchdog and selected_strategy() == "random" and read_random_status().get("state") == "paused":
        return "paused"
    return "starting" if watchdog else "stopped"


def read_random_status():
    try:
        data = json.loads(RANDOM_STATUS.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def selected_strategy():
    try:
        state = json.loads(PID_FILE.read_text(encoding="utf-8"))
        process = verified_process(
            int(state["runner_pid"]), REPO / "scripts" / "run_cn_1v1.py", state.get("runner_created_at")
        )
        command = process.cmdline() if process is not None else []
        if "--strategy" in command:
            return command[command.index("--strategy") + 1]
    except (OSError, ValueError, TypeError, KeyError, IndexError, psutil.Error):
        pass
    try:
        value = STRATEGY_SELECTION.read_text(encoding="utf-8").strip()
        return value if value in ("random", "567", "hog") else "567"
    except OSError:
        return "567"


def random_reward_text(events):
    for event in reversed(events):
        if event.get("event") == "claim_all_confirmed":
            return "领取全部已确认"
        if event.get("event") == "claim_all_unverified":
            return "领取结果待确认，已暂停"
        if event.get("event") == "mastery_footer_checked":
            return {
                "none": "没有领取全部按钮，无可领奖励",
                "claim_all": "发现领取全部按钮",
                "unknown": "底部状态待识别",
            }.get(event.get("footer_state"), "奖励状态待识别")
    return None


def tail_log(path: Path, max_lines: int = 18) -> list[str]:
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - 12_000))
            data = stream.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = data.splitlines()
    if size > 12_000 and lines:
        lines = lines[1:]  # first line may have begun before the bounded read
    return lines[-max_lines:]


def _run(command: list[str], timeout: float = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _check_start_cancelled(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("启动已取消：用户已停止任务")


def _run_cancellable(command, timeout, cancel_event):
    """Interrupt this startup command promptly without touching the emulator."""
    _check_start_cancelled(cancel_event)
    process = subprocess.Popen(
        command,
        cwd=REPO,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    deadline = time.monotonic() + timeout
    try:
        while True:
            _check_start_cancelled(cancel_event)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                stdout, stderr = process.communicate(timeout=min(0.1, remaining))
                _check_start_cancelled(cancel_event)
                return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                continue
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=2)


class ControlWindow:
    def __init__(self, instance=None) -> None:
        enable_native_embedding_dpi()
        set_app_identity()
        self.root = ttk.Window(themename="flatly")
        self.root.title("皇室战争助手")
        self.root.configure(bg=COLORS["page"])
        width = min(1660, self.root.winfo_screenwidth() - 80)
        height = min(940, self.root.winfo_screenheight() - 100)
        self.root.geometry(f"{width}x{height}+{(self.root.winfo_screenwidth() - width) // 2}+40")
        self.root.minsize(min(1360, width), min(820, height))
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        icon = REPO / "assets" / "clash-desktop.ico"
        if icon.is_file():
            try:
                self.root.iconbitmap(str(icon))
            except tk.TclError:
                pass

        self.events: queue.Queue[tuple[str, str]] = queue.Queue()
        self.busy: str | None = None
        self.shell = None
        self._exit_requested = False
        self._hidden = False
        self._restore_embedding = False
        self._attach_after_id = None
        self._details_expanded = False
        self._report_signature = None
        self._error_catalog_signature = None
        self._selected_error_report = None
        self._selected_report_path = None
        self._error_catalog = {}
        self._error_image = None
        self._error_history_next_refresh = 0.0
        self._pause_report_key = None
        self._report_future = None
        self._report_retry_at = 0.0
        self.error_reporter = ErrorReporter(
            output_dir=OUTPUTS / "error-reports",
            adb=ADB,
            serial=SERIAL,
            pid_file=PID_FILE,
            state_path=RANDOM_STATUS,
            log_paths=(BATTLE_LOG, WATCHDOG_LOG, RANDOM_TRACE),
        )
        self.last_log_text = ""
        self.notice = tk.StringVar(value="就绪 · 点击开始运行；关闭窗口会收进系统托盘。")
        self.metrics = {
            key: tk.StringVar(value="—") for key in ("total", "wins", "losses", "rate", "recent", "rewards", "coins")
        }
        self.metric_notes = {key: tk.StringVar(value="正在读取历史…") for key in self.metrics}
        self.metric_values = {}
        self.scope = tk.StringVar(value="随机卡组" if selected_strategy() == "random" else "567 历史")
        self.session_detail = tk.StringVar(value="正在汇总持久化战绩…")
        self.run_detail = tk.StringVar(value="正在读取运行策略…")
        self.flow_detail = tk.StringVar(value="每局换卡组 → 经典1V1 → 领取全部检查 → 下一局")
        self.reward_detail = tk.StringVar(value="奖励检查：等待下一次底部按钮检查")
        self.streak_detail = tk.StringVar(value="")
        self.history_info = tk.StringVar(value="历史统计以结算记录为准；未识别结果保留为未知。")
        self.history_events = queue.Queue(maxsize=1)
        self.history_stop = threading.Event()
        self.history_snapshots = {}
        self.history_key = None
        self.latest = tk.StringVar(value="正在读取对战状态…")
        self.hero_title = tk.StringVar(value="正在读取运行状态")
        self.hero_detail = tk.StringVar(value="连接到本机机器人")
        self.raw_log = tk.BooleanVar(value=False)
        self.auto_scroll = tk.BooleanVar(value=True)
        self.updated = tk.StringVar(value="")
        self._setup_styles()
        self._build_app_menu()

        self.fixed_panels = []
        self._build_sidebar()
        self.workspace = tk.Frame(self.root, autostyle=False, bg=COLORS["page"])
        self.workspace.columnconfigure(0, weight=1)
        self.workspace.rowconfigure(0, weight=1)
        self.page = tk.Frame(self.workspace, autostyle=False, bg=COLORS["page"])
        self.page.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        self.page.columnconfigure(0, weight=1)
        self.page.rowconfigure(4, weight=1)
        self._build_header()
        self._build_running_panel()
        self._build_metrics()
        self._build_insights()
        self._build_details()
        self._build_footer()
        self._build_live_view()
        for panel in self.fixed_panels:
            panel.default_padding = panel.padding
        self.root.bind("<Configure>", self._resize)
        for index in range(4):
            self.root.bind(f"<Control-Key-{index + 1}>", lambda _event, view=index: self._select_view(view))
        self._select_view(0)
        self.root.update_idletasks()
        self._resize(
            type(
                "Size", (), {"widget": self.root, "width": self.root.winfo_width(), "height": self.root.winfo_height()}
            )()
        )
        self._fit_metrics()
        self.shell = DesktopShell(
            self.root, icon, self._show_window, self._start, self._stop, self._request_exit, instance=instance
        )
        self._refresh()
        threading.Thread(target=self._history_worker, daemon=True).start()
        self.root.after(2000, self._tick)

    def _build_sidebar(self):
        self.sidebar = tk.Frame(self.root, autostyle=False, bg=COLORS["sidebar"])
        brand = tk.Frame(self.sidebar, autostyle=False, bg=COLORS["sidebar"])
        brand.pack(fill="x", padx=20, pady=(26, 30))
        icon = REPO / "assets" / "clash-desktop.png"
        if icon.is_file():
            self.brand_icon = tk.PhotoImage(file=str(icon))
            scale = max(1, self.brand_icon.width() // 36)
            self.brand_icon = self.brand_icon.subsample(scale, scale)
            tk.Label(brand, image=self.brand_icon, bg=COLORS["sidebar"], autostyle=False).pack(
                side="left", padx=(0, 10)
            )
        else:
            mark = tk.Canvas(brand, autostyle=False, width=32, height=36, bg=COLORS["sidebar"], highlightthickness=0)
            mark.pack(side="left", padx=(0, 10))
            mark.create_polygon(3, 10, 10, 16, 16, 5, 22, 16, 29, 10, 25, 27, 7, 27, fill=COLORS["accent"], outline="")
        words = tk.Frame(brand, autostyle=False, bg=COLORS["sidebar"])
        words.pack(side="left")
        self._label(words, "皇室战争助手", size=12, bold=True).pack(anchor="w")
        self._label(words, "CLASH ASSISTANT", size=8, fg=COLORS["nav_muted"], family="Segoe UI").pack(
            anchor="w", pady=(4, 0)
        )
        self._label(self.sidebar, "工作空间", size=9, fg=COLORS["muted"]).pack(anchor="w", padx=24, pady=(0, 12))
        self.nav_buttons = []
        for index, (title, icon) in enumerate(
            (("对战总览", "records"), ("策略统计", "chart"), ("运行日志", "log"), ("错误报告", "log"))
        ):
            button = PanelButton(
                self.sidebar,
                text=title,
                icon=icon,
                variant="nav",
                height=46,
                command=lambda view=index: self._select_view(view),
            )
            button.pack(fill="x", padx=14, pady=(0, 6))
            self.nav_buttons.append(button)
        foot = tk.Frame(self.sidebar, autostyle=False, bg=COLORS["sidebar"])
        foot.pack(side="bottom", fill="x", padx=20, pady=24)
        PanelButton(foot, text="收进系统托盘", variant="outline", height=36, command=self._on_close).pack(
            fill="x", pady=(0, 16)
        )
        tk.Frame(foot, autostyle=False, bg=COLORS["border"], height=1).pack(fill="x", pady=(0, 16))
        self._label(foot, "●  本机运行", size=9, fg=COLORS["green"]).pack(anchor="w")
        self._label(foot, "腾讯国服 · 经典 1V1", size=9, fg=COLORS["nav_muted"]).pack(anchor="w", pady=(6, 0))

    def _build_app_menu(self):
        menu = tk.Menu(self.root)
        app = tk.Menu(menu, tearoff=False)
        app.add_command(label="开始运行", command=self._start)
        app.add_command(label="停止任务", command=self._stop)
        app.add_separator()
        app.add_command(label="收进系统托盘", command=self._on_close)
        app.add_command(label="退出软件（停止任务）", command=self._request_exit)
        menu.add_cascade(label="应用", menu=app)
        view = tk.Menu(menu, tearoff=False)
        for index, title in enumerate(("对战总览", "策略统计", "运行日志", "错误报告")):
            view.add_command(
                label=title, command=lambda number=index: self._select_view(number), accelerator=f"Ctrl+{index + 1}"
            )
        menu.add_cascade(label="查看", menu=view)
        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="关于皇室战争助手", command=self._about)
        menu.add_cascade(label="帮助", menu=help_menu)
        self.root.configure(menu=menu)

    def _about(self):
        messagebox.showinfo(
            "皇室战争助手",
            "皇室战争助手\n\n本机自动对战 · 战绩统计 · 暂停错误报告\n\n"
            "打开软件后点击开始运行。关闭窗口会收进系统托盘；\n从应用菜单或托盘选择退出软件，会停止任务并退出。",
            parent=self.root,
        )

    def _build_header(self):
        header = tk.Frame(self.page, autostyle=False, bg=COLORS["page"])
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        heading = tk.Frame(header, autostyle=False, bg=COLORS["page"])
        heading.pack(side="left")
        self._label(heading, "对战工作台", size=22, bold=True).pack(anchor="w")
        self._label(heading, "管理自动对战，查看每一场进展", size=10, fg=COLORS["muted"]).pack(anchor="w", pady=(5, 0))
        self.status = self._label(header, "●  检查中", size=9, fg=COLORS["muted"])
        self.status.pack(side="right", padx=(12, 0))
        self.scope_combo = ttk.Combobox(
            header,
            textvariable=self.scope,
            values=list(SCOPES),
            state="readonly",
            width=10,
            style="Scope.TCombobox",
            font=(FONT, 9),
        )
        self.scope_combo.pack(side="right", ipady=4)
        self._label(header, "战绩范围", size=9, fg=COLORS["muted"]).pack(side="right", padx=(12, 10))
        self.scope_combo.bind("<<ComboboxSelected>>", lambda _event: self._render_history())

    def _build_running_panel(self):
        hero = RoundedPanel(self.page, fill=COLORS["surface"], padding=20, height=160)
        self.hero_panel = hero
        hero.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        self.fixed_panels.append(hero)
        hero.body.columnconfigure(0, weight=1)
        hero_left = tk.Frame(hero.body, autostyle=False, bg=COLORS["surface"])
        hero_left.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        title_row = tk.Frame(hero_left, autostyle=False, bg=COLORS["surface"])
        title_row.pack(anchor="w")
        self.phase_dot = self._label(title_row, "●", size=16, fg=COLORS["green"])
        self.phase_dot.pack(side="left", padx=(0, 10))
        self._label(title_row, variable=self.hero_title, size=17, bold=True).pack(side="left")
        self.hero_detail_label = self._label(hero_left, variable=self.hero_detail, size=10, fg=COLORS["muted"])
        self.hero_detail_label.pack(anchor="w", pady=(8, 0))
        actions = tk.Frame(hero.body, autostyle=False, bg=COLORS["surface"])
        actions.grid(row=0, column=1, sticky="ne", pady=4)
        self.start_button = PanelButton(
            actions, text="开始运行", icon="play", width=118, height=42, command=self._start
        )
        self.start_button.pack(side="left", padx=(0, 8))
        self.stop_button = PanelButton(
            actions, text="停止任务", icon="stop", width=118, height=42, variant="danger", command=self._stop
        )
        self.stop_button.pack(side="left")
        summary = tk.Frame(hero.body, autostyle=False, bg=COLORS["surface"])
        summary.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        self._label(summary, "随机卡组  ·  连续 1V1  ·  自动检查奖励", size=10, fg=COLORS["muted"]).pack(side="left")
        self.details_button = PanelButton(
            summary, text="运行详情", variant="outline", width=100, height=30, command=self._toggle_details
        )
        self.details_button.pack(side="right")
        details = self.runtime_details = tk.Frame(hero.body, autostyle=False, bg=COLORS["surface"])
        self.run_detail_label = self._label(details, variable=self.run_detail, size=9, fg=COLORS["muted"])
        self.run_detail_label.pack(anchor="w", pady=(0, 3))
        self.flow_detail_label = self._label(details, variable=self.flow_detail, size=9, fg=COLORS["muted"])
        self.flow_detail_label.pack(anchor="w", pady=(0, 3))
        self.reward_detail_label = self._label(details, variable=self.reward_detail, size=9, fg=COLORS["muted"])
        self.reward_detail_label.pack(anchor="w")

    def _toggle_details(self):
        self._details_expanded = not self._details_expanded
        if self._details_expanded:
            self.runtime_details.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        else:
            self.runtime_details.grid_remove()
        self.details_button.configure(text="收起详情" if self._details_expanded else "运行详情")
        self.root.after_idle(self._fit_metrics)

    def _build_metrics(self):
        stats = RoundedPanel(self.page, fill=COLORS["surface"], padding=16, height=123)
        self.stats_panel = stats
        stats.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        self.fixed_panels.append(stats)
        cards = (
            ("累计已结算", "total", COLORS["ink"]),
            ("累计胜利", "wins", COLORS["green"]),
            ("累计失败", "losses", COLORS["red"]),
            ("累计胜率", "rate", COLORS["ink"]),
            ("近 20 局胜率", "recent", COLORS["ink"]),
        )
        for column, (title, key, color) in enumerate(cards):
            stats.body.columnconfigure(column * 2, weight=1, uniform="metric")
            group = tk.Frame(stats.body, autostyle=False, bg=COLORS["surface"])
            group.grid(row=0, column=column * 2, sticky="ew", padx=(8, 8))
            self._label(group, title, size=9, fg=COLORS["muted"]).pack(anchor="center")
            value = self._label(group, variable=self.metrics[key], size=26, bold=True, fg=color, family="Segoe UI")
            value.pack(anchor="center", pady=(1, 1))
            self.metric_values[key] = value
            self._label(group, variable=self.metric_notes[key], size=8, fg=COLORS["muted"]).pack(anchor="center")
            if column != len(cards) - 1:
                tk.Frame(stats.body, autostyle=False, bg=COLORS["border"], width=1).grid(
                    row=0, column=column * 2 + 1, sticky="ns", pady=2
                )

    def _build_insights(self):
        row = tk.Frame(self.page, autostyle=False, bg=COLORS["page"])
        row.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        row.columnconfigure(0, weight=65, uniform="insight")
        row.columnconfigure(1, weight=35, uniform="insight")
        insight = RoundedPanel(row, fill=COLORS["surface"], padding=16, height=126)
        self.insight_panel = insight
        insight.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.fixed_panels.append(insight)
        top = tk.Frame(insight.body, autostyle=False, bg=COLORS["surface"])
        top.pack(fill="x")
        self._label(top, "最近运行", size=11, bold=True).pack(side="left")
        self._label(top, variable=self.streak_detail, size=8, fg=COLORS["muted"]).pack(side="right")
        self.session_label = self._label(insight.body, variable=self.session_detail, size=9)
        self.session_label.pack(anchor="w", pady=(5, 9))
        strip = tk.Frame(insight.body, autostyle=False, bg=COLORS["surface"])
        strip.pack(fill="x")
        self.result_chips = []
        for _index in range(20):
            chip = StateChip(strip, text="·", width=22, height=24, bg="#eef2ee", fg=COLORS["muted"])
            chip.pack(side="left", padx=(0, 3))
            self.result_chips.append(chip)
        self._label(strip, "旧 → 新", size=8, fg=COLORS["muted"]).pack(side="right")
        reward = RoundedPanel(row, fill=COLORS["reward_surface"], padding=16, height=126)
        reward.grid(row=0, column=1, sticky="nsew")
        self.fixed_panels.append(reward)
        self._label(reward.body, "奖励累计", size=11, bold=True).pack(anchor="w", pady=(0, 3))
        groups = tk.Frame(reward.body, autostyle=False, bg=COLORS["reward_surface"])
        groups.pack(fill="x")
        groups.columnconfigure(0, weight=40)
        groups.columnconfigure(2, weight=60)
        for column, (key, title) in enumerate((("rewards", "累计领取奖励数"), ("coins", "累计领取金币数"))):
            group = tk.Frame(groups, autostyle=False, bg=COLORS["reward_surface"])
            group.grid(row=0, column=column * 2, sticky="ew", padx=(0, 8) if column == 0 else (12, 0))
            value = self._label(group, variable=self.metrics[key], size=22, bold=True, family="Segoe UI")
            value.pack(anchor="center")
            self.metric_values[key] = value
            self._label(group, title, size=8, fg=COLORS["muted"]).pack(anchor="center", pady=(3, 0))
        tk.Frame(groups, autostyle=False, bg="#dce6dd", width=1).grid(row=0, column=1, sticky="ns", pady=4)
        self.reward_coin_note = self._label(
            reward.body, variable=self.metric_notes["coins"], size=8, fg=COLORS["muted"]
        )

    def _build_details(self):
        self.detail_panel = RoundedPanel(self.page, fill=COLORS["surface"], padding=14)
        self.detail_panel.grid(row=4, column=0, sticky="nsew")
        self.notebook = ttk.Notebook(self.detail_panel.body, style="Console.TNotebook")
        self.notebook.pack(fill="both", expand=True)
        history_tab = tk.Frame(self.notebook, autostyle=False, bg=COLORS["surface"])
        version_tab = tk.Frame(self.notebook, autostyle=False, bg=COLORS["surface"])
        log_tab = tk.Frame(self.notebook, autostyle=False, bg=COLORS["surface"])
        self.notebook.add(history_tab, text="对局记录")
        self.notebook.add(version_tab, text="策略对比")
        self.notebook.add(log_tab, text="运行日志")
        error_tab = tk.Frame(self.notebook, autostyle=False, bg=COLORS["surface"])
        self.notebook.add(error_tab, text="错误报告")
        error_toolbar = tk.Frame(error_tab, autostyle=False, bg=COLORS["surface"])
        error_toolbar.pack(fill="x", pady=(4, 12))
        self.error_history_info = tk.StringVar(value="暂停错误报告")
        self._label(error_toolbar, variable=self.error_history_info, size=12, bold=True).pack(side="left")
        self.open_report_button = PanelButton(
            error_toolbar, text="打开所选报告", variant="outline", width=140, height=32, command=self._open_error_report
        )
        self.open_report_button.pack(side="right")
        self.open_error_image_button = PanelButton(
            error_toolbar, text="查看截图", variant="outline", width=100, height=32, command=self._open_error_image
        )
        self.open_error_image_button.pack(side="right", padx=(0, 8))
        PanelButton(
            error_toolbar, text="报告文件夹", variant="outline", width=115, height=32, command=self._open_error_folder
        ).pack(side="right", padx=(0, 8))
        self._label(
            error_tab,
            "每次暂停单独留档；在左侧选择历史记录，右侧查看当次原因和报告。",
            size=10,
            fg=COLORS["muted"],
        ).pack(anchor="w", pady=(0, 14))
        error_panes = ttk.Panedwindow(error_tab, orient="horizontal")
        error_panes.pack(fill="both", expand=True)
        report_list = tk.Frame(error_panes, autostyle=False, bg=COLORS["surface"])
        report_detail = tk.Frame(error_panes, autostyle=False, bg=COLORS["surface"])
        error_panes.add(report_list, weight=1)
        error_panes.add(report_detail, weight=1)
        self.error_history_tree = ttk.Treeview(
            report_list,
            columns=("time", "reason", "screenshot"),
            show="headings",
            height=4,
            selectmode="browse",
            style="Battle.Treeview",
        )
        for name, title, width in (("time", "暂停时间", 180), ("reason", "暂停原因", 190), ("screenshot", "截图", 65)):
            self.error_history_tree.heading(name, text=title, anchor="w")
            self.error_history_tree.column(name, width=width, minwidth=55, anchor="w", stretch=name == "reason")
        self.error_history_tree.grid(row=0, column=0, sticky="nsew")
        report_list.rowconfigure(0, weight=1)
        report_list.columnconfigure(0, weight=1)
        error_list_scroll = ttk.Scrollbar(report_list, orient="vertical", command=self.error_history_tree.yview)
        error_list_scroll.grid(row=0, column=1, sticky="ns")
        self.error_history_tree.configure(yscrollcommand=error_list_scroll.set)
        self.error_history_tree.bind("<<TreeviewSelect>>", self._select_error_report)
        self.error_history_tree.bind("<Double-1>", lambda _event: self._open_error_report())
        self.error_text = tk.Text(
            report_detail,
            autostyle=False,
            wrap="word",
            bg=COLORS["surface"],
            fg=COLORS["ink"],
            font=(FONT, 9),
            width=36,
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=8,
            pady=8,
            spacing3=6,
            state="disabled",
        )
        self.error_text.pack(side="left", fill="both", expand=True)
        error_detail_scroll = ttk.Scrollbar(report_detail, orient="vertical", command=self.error_text.yview)
        error_detail_scroll.pack(side="right", fill="y")
        self.error_text.configure(yscrollcommand=error_detail_scroll.set)
        toolbar = tk.Frame(history_tab, autostyle=False, bg=COLORS["surface"])
        toolbar.pack(fill="x", pady=(0, 8))
        self._label(toolbar, "对局记录", size=11, bold=True).pack(side="left", padx=(0, 12))
        self._label(toolbar, "最近 60 场 · 双击查看结算图", size=8, fg=COLORS["muted"]).pack(side="left")
        self.open_result_button = PanelButton(
            toolbar, text="查看结算图", command=self._open_result, variant="outline", width=130, height=30
        )
        self.open_result_button.pack(side="right")
        self.history_source_label = self._label(history_tab, variable=self.history_info, size=8, fg=COLORS["muted"])
        self.history_source_label.pack(side="bottom", anchor="w", fill="x", pady=(10, 0))
        self.history_tree = self._tree(
            history_tab,
            (
                ("time", "结算时间", 128),
                ("result", "胜负", 72),
                ("battle", "场次", 52),
                ("deployment", "出牌确认", 84),
                ("policy", "策略版本", 180),
                ("session", "运行批次", 134),
                ("evidence", "结算证据", 90),
            ),
        )
        self.history_tree.bind("<Double-1>", lambda _event: self._open_result())
        self.history_tree.bind("<<ResultOpen>>", lambda _event: self._open_result())
        self.history_tree.bind("<<TreeviewSelect>>", lambda _event: self._update_result_button(), add="+")
        self._label(version_tab, "策略对比", size=11, bold=True).pack(anchor="w", pady=(3, 8))
        self._label(
            version_tab, "按实际运行版本独立统计；不同对手和样本量的胜率仅供观察。", size=9, fg=COLORS["muted"]
        ).pack(anchor="w", pady=(0, 12))
        self.version_tree = self._tree(
            version_tab,
            (
                ("policy", "策略版本", 240),
                ("total", "局数", 64),
                ("wins", "胜", 52),
                ("losses", "负", 52),
                ("unknown", "平 / 未知", 84),
                ("rate", "胜率", 74),
            ),
        )
        log_tab.columnconfigure(0, weight=1)
        log_tab.rowconfigure(2, weight=1)
        journal_head = tk.Frame(log_tab, autostyle=False, bg=COLORS["surface"])
        journal_head.grid(row=0, column=0, sticky="ew", pady=(3, 0))
        self._label(journal_head, "运行日志", size=11, bold=True).pack(side="left")
        self._label(journal_head, "每秒同步", size=8, fg=COLORS["muted"]).pack(side="left", padx=12)
        ttk.Checkbutton(
            journal_head, text="原始日志", variable=self.raw_log, command=self._refresh, style="Journal.TCheckbutton"
        ).pack(side="right")
        ttk.Checkbutton(
            journal_head,
            text="自动滚动",
            variable=self.auto_scroll,
            command=lambda: self.log_text.see("end") if self.auto_scroll.get() else None,
            style="Journal.TCheckbutton",
        ).pack(side="right", padx=(0, 14))
        self.latest_label = self._label(log_tab, variable=self.latest, size=9, fg=COLORS["muted"])
        self.latest_label.grid(row=1, column=0, sticky="w", pady=(8, 12))
        log_frame = tk.Frame(log_tab, autostyle=False, bg=COLORS["surface"])
        log_frame.grid(row=2, column=0, sticky="nsew")
        self.log_text = tk.Text(
            log_frame,
            autostyle=False,
            wrap="word",
            height=4,
            font=(FONT, 9),
            bg=COLORS["surface"],
            fg=COLORS["ink"],
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=0,
            pady=2,
            spacing1=5,
            spacing3=5,
            selectbackground="#dce9de",
            selectforeground=COLORS["ink"],
            state="disabled",
        )
        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(
            log_frame, orient="vertical", command=self.log_text.yview, style="Console.Vertical.TScrollbar"
        )
        scrollbar.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.tag_configure("time", foreground=COLORS["muted"], font=("Consolas", 9))
        self.log_text.tag_configure("body", foreground=COLORS["ink"])
        for tag, color in {
            "对战": COLORS["green"],
            "胜利": COLORS["green"],
            "失败": COLORS["red"],
            "恢复": "#947441",
            "提醒": "#947441",
            "启动": COLORS["green"],
            "完成": COLORS["green"],
            "记录": COLORS["muted"],
        }.items():
            self.log_text.tag_configure(tag, foreground=color, font=(FONT, 9, "bold"))
        self._update_result_button()

    def _build_footer(self):
        footer = tk.Frame(
            self.root, autostyle=False, bg=COLORS["surface"], highlightbackground=COLORS["border"], highlightthickness=1
        )
        self.footer = footer
        self.notice_label = self._label(footer, variable=self.notice, size=9, fg=COLORS["muted"])
        self.notice_label.pack(side="left", fill="x", expand=True, padx=18, pady=8)
        self._label(footer, variable=self.updated, size=9, fg=COLORS["muted"]).pack(side="right", padx=18)

    def _refresh_error_report(self, *, force=False):
        now = time.monotonic()
        if force or now >= self._error_history_next_refresh:
            self._error_history_next_refresh = now + 3
            records = list_error_reports(OUTPUTS / "error-reports")
            signature = json.dumps(records, sort_keys=True, ensure_ascii=False)
            if signature != self._error_catalog_signature:
                self._error_catalog_signature = signature
                self._error_catalog = {row["report_dir"]: row for row in records}
                previous = self._selected_error_report
                if previous not in self._error_catalog:
                    previous = records[0]["report_dir"] if records else None
                self._selected_error_report = previous
                self.error_history_tree.delete(*self.error_history_tree.get_children())
                for row in records:
                    status = {"captured": "已保存", "failed": "失败", "pending": "采集中"}.get(
                        row["screenshot_status"], "缺失"
                    )
                    self.error_history_tree.insert(
                        "",
                        "end",
                        iid=row["report_dir"],
                        values=(row["occurred_at"].replace("T", " ")[:19], row["reason"], status),
                    )
                self.error_history_info.set(f"暂停错误报告 · 共 {len(records)} 份")
                if previous:
                    self.error_history_tree.selection_set(previous)
                    self.error_history_tree.see(previous)
        self._render_selected_error_report()

    def _select_error_report(self, _event=None):
        selected = self.error_history_tree.selection()
        if selected and selected[0] in self._error_catalog:
            self._selected_error_report = selected[0]
        self._render_selected_error_report()

    def _render_selected_error_report(self):
        index = self._error_catalog.get(self._selected_error_report, {})
        report_root = (OUTPUTS / "error-reports").resolve()
        report = None
        screenshot = None
        signature = (self._selected_error_report, None)
        content = "目前没有暂停错误报告。\n\n每次异常暂停会独立留档，重启软件后仍可查看历史。"
        if index:
            try:
                if index.get("report_md"):
                    candidate = Path(index["report_md"])
                    resolved = candidate.resolve()
                    if not candidate.is_symlink() and resolved.is_relative_to(report_root) and resolved.is_file():
                        report = resolved
                        signature = (str(report), report.stat().st_mtime_ns)
                        content = report.read_text(encoding="utf-8")[:24000]
                if report is None:
                    content = f"暂停时间：{index['occurred_at']}\n暂停原因：{index['reason']}\n\n报告尚未完整写入，已保留此历史记录。"
                if index.get("game_png"):
                    candidate = Path(index["game_png"])
                    resolved = candidate.resolve()
                    if not candidate.is_symlink() and resolved.is_relative_to(report_root) and resolved.is_file():
                        screenshot = resolved
            except (OSError, ValueError, KeyError, TypeError) as error:
                content = f"历史报告读取失败：{error}\n\n已保留原报告，请使用报告文件夹查看。"
        self._selected_report_path = report
        self._error_image = screenshot
        self.open_report_button.configure(state="normal" if report else "disabled")
        self.open_error_image_button.configure(state="normal" if screenshot else "disabled")
        if signature == self._report_signature and getattr(self, "_report_loaded", False):
            return
        self._report_signature = signature
        self._report_loaded = True
        self.error_text.configure(state="normal")
        self.error_text.delete("1.0", "end")
        self.error_text.insert("end", content)
        self.error_text.configure(state="disabled")

    def _open_error_report(self):
        self._refresh_error_report(force=True)
        if self._selected_report_path:
            os.startfile(self._selected_report_path)

    def _open_error_image(self):
        self._refresh_error_report(force=True)
        if self._error_image:
            os.startfile(self._error_image)

    @staticmethod
    def _open_error_folder():
        path = OUTPUTS / "error-reports"
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(path)

    def _build_live_view(self):
        self.live_panel = RoundedPanel(self.workspace, fill=COLORS["surface"], padding=16, width=408)
        self.live_panel.grid(row=0, column=1, sticky="nsew")
        self.live_view = NativeEmulatorView(
            self.live_panel.body,
            emulator_path=MEMUC.with_name("MEmu.exe"),
            serial=SERIAL,
            cwd=REPO,
            recovery_path=WORK / "native-window-recovery.json",
        )
        self.live_view.pack(fill="both", expand=True)

    def _select_view(self, index):
        self.notebook.select(index)
        for position, button in enumerate(self.nav_buttons):
            button.set_selected(position == index)
        if index == 3:
            self._refresh_error_report(force=True)

    def _update_result_button(self):
        self.open_result_button.configure(state="normal" if self.history_tree.selection() else "disabled")

    def _label(self, parent, text="", *, variable=None, size=10, bold=False, fg=None, family=FONT):
        try:
            background = parent.cget("bg")
        except tk.TclError:
            background = COLORS["surface"]
        options = {"textvariable": variable} if variable is not None else {}
        return tk.Label(
            parent,
            autostyle=False,
            text=text,
            **options,
            bg=background,
            fg=fg or COLORS["ink"],
            font=(family, size, "bold" if bold else "normal"),
            bd=0,
            padx=0,
            pady=0,
            anchor="w",
            justify="left",
        )

    @staticmethod
    def _tree(parent, columns):
        holder = ttk.Frame(parent)
        holder.pack(fill="both", expand=True)
        tree = ResultTree(
            holder,
            columns=[c[0] for c in columns],
            show="headings",
            height=5,
            selectmode="browse",
            style="Battle.Treeview",
        )
        for name, title, width in columns:
            tree.heading(name, text=title, anchor="w")
            tree.column(name, width=width, minwidth=50, anchor="w", stretch=True)
        tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(holder, orient="vertical", command=tree.yview, style="Console.Vertical.TScrollbar")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(
            holder, orient="horizontal", command=tree.xview, style="Console.Horizontal.TScrollbar"
        )
        horizontal.grid(row=1, column=0, sticky="ew")
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        for tag in ("胜利", "失败", "未知", "平局"):
            tree.tag_configure(tag, foreground=COLORS["ink"])
        return tree

    def _history_worker(self):
        history = None
        try:
            history = BattleHistory(HISTORY_DB)
            while not self.history_stop.is_set():
                backlog = False
                for strategy in ("567", "hog"):
                    backlog |= history.ingest(OUTPUTS / f"cn-{strategy}-strategy.jsonl", strategy)
                backlog |= history.ingest(RANDOM_TRACE, "random")
                backlog |= history.ingest(REWARDS_TRACE, "rewards")
                if not backlog:
                    snapshots = {scope: history.snapshot(scope) for scope in SCOPES.values()}
                    snapshots["reward_totals"] = history.reward_snapshot()
                    try:
                        self.history_events.get_nowait()
                    except queue.Empty:
                        pass
                    self.history_events.put_nowait(("ok", snapshots))
                if self.history_stop.wait(0.01 if backlog else 2):
                    break
        except (OSError, ValueError, sqlite3.Error, TypeError, AttributeError) as error:
            try:
                self.history_events.get_nowait()
            except queue.Empty:
                pass
            self.history_events.put_nowait(("error", str(error)))
        finally:
            if history is not None:
                history.close()

    def _render_history(self):
        rewards = self.history_snapshots.get("reward_totals", {})
        self._render_rewards(rewards)
        data = self.history_snapshots.get(SCOPES[self.scope.get()])
        if not data:
            return
        total, recent = data["total"], data["recent"]
        for key in ("total", "wins", "losses"):
            self.metrics[key].set(str(total[key]))
        self.metrics["rate"].set(rate_text(total))
        self.metrics["recent"].set(rate_text(recent))
        self.metric_notes["total"].set(f"未知 {total['unknown']} · 平局 {total['draws']}")
        self.metric_notes["wins"].set("结算识别为胜利")
        self.metric_notes["losses"].set("结算识别为失败")
        self.metric_notes["rate"].set("胜场 ÷ 全部已结算")
        self.metric_notes["recent"].set(f"{recent['wins']} 胜 / {recent['total']} 局")
        self._render_battle_details(data)

    def _render_rewards(self, rewards):
        self.metrics["rewards"].set(f"{rewards.get('rewards', 0):,}")
        unknown = rewards.get("unknown_coin_items", 0)
        self.metrics["coins"].set(f"{rewards.get('coins', 0):,}" + ("+" if unknown else ""))
        self.metric_notes["rewards"].set("卡牌大师领奖累计")
        self.metric_notes["coins"].set(f"{unknown} 项金额待核实" if unknown else "已确认领奖金币")
        if unknown:
            self.reward_coin_note.pack(anchor="w", pady=(4, 0))
        else:
            self.reward_coin_note.pack_forget()

    def _render_battle_details(self, data):
        total, session = data["total"], data["session"]
        self.session_detail.set(
            f"{session['total']} 局 · {session['wins']} 胜 {session['losses']} 负"
            f" · 未知 {session['unknown']} · 胜率 {rate_text(session)}"
        )
        streak = (
            f"{total['streak']} 连胜"
            if total["streak_result"] == "胜利"
            else (f"{total['streak']} 连败" if total["streak_result"] == "失败" else "暂无连胜负")
        )
        self.streak_detail.set(f"{streak}  /  最长连胜 {total['best_win_streak']}")
        results = [None] * (20 - len(data["recent_results"])) + data["recent_results"]
        for chip, result in zip(self.result_chips, results, strict=True):
            bg, fg = {"胜利": ("#e3f3eb", "#167359"), "失败": ("#faeae7", "#a8463c")}.get(
                result, ("#eef2ee", COLORS["muted"])
            )
            chip.configure(text={"胜利": "胜", "失败": "负", "未知": "?", "平局": "平"}.get(result, "·"), bg=bg, fg=fg)
        source_note = f"{(data['first_at'] or '')[:10]} 起 · 胜率包含未知和平局 · 未结算不计入 · 自动识别结果"
        if data["conflicts"] or data["malformed_lines"]:
            source_note += f" · 冲突 {data['conflicts']} / 损坏行 {data['malformed_lines']}"
        self.history_info.set(source_note)
        key = (self.scope.get(), json.dumps(data["records"], ensure_ascii=False), json.dumps(data["versions"]))
        if key == self.history_key:
            return
        self.history_key = key
        selected = self.history_tree.selection()
        position = self.history_tree.yview()[0]
        self.history_tree.delete(*self.history_tree.get_children())
        self.history_records = {}
        for row in data["records"]:
            iid = f"{row['strategy']}:{row['session']}:{row['battle']}"
            self.history_records[iid] = row
            deployment = f"{row['confirmed']}/{row['attempts']}" if row["attempts"] is not None else "—"
            self.history_tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    row["time"][5:],
                    row["result"],
                    row["battle"],
                    deployment,
                    policy_text(row["policy"]),
                    row["session"],
                    row.get("evidence_status", "待核验"),
                ),
                tags=(row["result"],),
            )
        if selected and self.history_tree.exists(selected[0]):
            self.history_tree.selection_set(selected)
        self.history_tree.yview_moveto(position)
        self._update_result_button()
        self.version_tree.delete(*self.version_tree.get_children())
        for row in data["versions"]:
            identity = row.get("strategy_hash")
            label = policy_text(row["policy"]) + (f" · {identity[:8]}" if identity else " · 来源未记录")
            self.version_tree.insert(
                "",
                "end",
                values=(
                    label,
                    row["total"],
                    row["wins"],
                    row["losses"],
                    f"{row['draws']} / {row['unknown']}",
                    rate_text(row),
                ),
            )

    def _open_result(self):
        selected = self.history_tree.selection()
        if not selected:
            self.notice.set("先选择一场对局，再查看结算图。")
            return
        row = self.history_records[selected[0]]
        path = Path(row.get("evidence") or "").resolve()
        if not path.is_relative_to(WORK.resolve()) or path.suffix.lower() != ".png" or not path.is_file():
            self.notice.set("此场没有可用的本地结算图；历史统计仍保留。")
            return
        if row.get("strategy") == "random":
            # Random-mode screenshots use a ring. Verify the battle's saved hash
            # before opening, and preserve an immutable copy for the image viewer.
            manifest = (WORK / "random-mastery" / row["session"] / f"battle-{row['battle']:04d}.json").resolve()
            try:
                if not manifest.is_relative_to(WORK.resolve()):
                    raise ValueError("Result manifest outside task work")
                evidence = json.loads(manifest.read_text(encoding="utf-8"))["evidence"]
                data = path.read_bytes()
                digest = hashlib.sha256(data).hexdigest()
                if Path(evidence["path"]).resolve() != path or digest != evidence["sha256"]:
                    self.notice.set("此场结算图已被轮换，无法确认匹配；历史统计仍保留。")
                    return
                preserved = WORK / "random-result-evidence" / f"{digest}.png"
                preserved.parent.mkdir(parents=True, exist_ok=True)
                if not preserved.exists():
                    preserved.write_bytes(data)
                path = preserved
            except (OSError, ValueError, KeyError, TypeError):
                self.notice.set("此场结算图缺少可验证的记录；历史统计仍保留。")
                return
        try:
            os.startfile(path)  # ty: ignore[unresolved-attribute]  # Windows-only console
        except OSError as error:
            self.notice.set(f"打开结算图失败：{error}")

    def _setup_styles(self):
        style = self.root.style
        style.configure("Console.TNotebook", background=COLORS["surface"], borderwidth=0, tabmargins=0)
        style.layout("Console.TNotebook.Tab", [])
        style.configure(
            "Journal.TCheckbutton", background=COLORS["surface"], foreground=COLORS["muted"], font=(FONT, 9)
        )
        style.map("Journal.TCheckbutton", background=[("active", COLORS["surface"])])
        style.configure(
            "Scope.TCombobox",
            fieldbackground=COLORS["surface"],
            background=COLORS["surface"],
            foreground=COLORS["ink"],
            bordercolor=COLORS["border"],
            arrowcolor=COLORS["muted"],
            padding=(8, 4),
            font=(FONT, 9),
        )
        style.map(
            "Scope.TCombobox",
            fieldbackground=[("readonly", COLORS["surface"])],
            foreground=[("readonly", COLORS["ink"])],
            selectbackground=[("readonly", COLORS["surface"])],
            selectforeground=[("readonly", COLORS["ink"])],
        )
        style.configure(
            "Battle.Treeview",
            font=(FONT, 9),
            rowheight=36,
            background=COLORS["surface"],
            fieldbackground=COLORS["surface"],
            foreground=COLORS["ink"],
            borderwidth=0,
            bordercolor=COLORS["surface"],
            relief="flat",
        )
        style.configure(
            "Battle.Treeview.Heading",
            font=(FONT, 9),
            background="#f4f7fc",
            foreground=COLORS["muted"],
            padding=(10, 6),
            relief="flat",
            borderwidth=0,
        )
        style.map("Battle.Treeview", background=[("selected", "#edf2ff")], foreground=[("selected", COLORS["ink"])])
        style.map("Battle.Treeview.Heading", background=[("active", "#edf2ff")])
        for orientation in ("Vertical", "Horizontal"):
            name = f"Console.{orientation}.TScrollbar"
            style.configure(
                name,
                background="#dce3dc",
                troughcolor=COLORS["surface"],
                bordercolor=COLORS["surface"],
                arrowcolor=COLORS["muted"],
                borderwidth=0,
                arrowsize=11,
            )

    def _resize(self, event):
        if event.widget is not self.root:
            return
        side = 216 if event.width >= 1500 else 198
        margin = 22 if event.width >= 1500 else 18
        workspace_width = max(1, event.width - side - 2 * margin)
        live_width = max(320, min(450, round(workspace_width * 0.30)))
        width = max(1, workspace_width - live_width - 18)
        self.sidebar.place(x=0, y=0, width=side, height=event.height - 36)
        self.footer.place(x=0, y=event.height - 36, width=event.width, height=36)
        self.workspace.place(x=side + margin, y=22, width=workspace_width, height=max(1, event.height - 80))
        self.workspace.columnconfigure(1, minsize=live_width)
        self.live_panel.configure(width=live_width)
        self.hero_detail_label.configure(wraplength=max(220, width - 328))
        for widget in (self.run_detail_label, self.flow_detail_label, self.reward_detail_label):
            widget.configure(wraplength=max(300, width - 48))
        self.session_label.configure(wraplength=max(240, int(width * 0.65) - 48))
        self.latest_label.configure(wraplength=max(250, width - 50))
        self.notice_label.configure(wraplength=max(200, event.width - 230))
        self.history_source_label.configure(wraplength=max(300, width - 40))
        chip_width = max(14, min(24, (int(width * 0.65) - 106) // 20 - 3))
        for chip in self.result_chips:
            chip.configure(width=chip_width)
        for panel in self.fixed_panels:
            panel.padding = min(panel.default_padding, 14) if event.height < 900 else panel.default_padding
            panel.configure(height=panel.body.winfo_reqheight() + 2 * panel.padding)
        self.root.after_idle(self._fit_metrics)

    def _refresh(self) -> None:
        state = bot_state()
        label, _background, foreground = STATUS_COLORS[state]
        if self.busy:
            label, _background, foreground = ("正在启动" if self.busy == "start" else "正在停止", "#fff4d6", "#925f00")
        self.status.configure(text=f"●  {label}", bg=COLORS["page"], fg=foreground)
        if self.shell is not None:
            self.shell.set_status(label, running=state in ("running", "starting"))
        if state == "paused":
            try:
                pause = json.loads(PID_FILE.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pause = {}
            pause_key = json.dumps(pause, sort_keys=True, ensure_ascii=False)
            if pause_key != self._pause_report_key and time.monotonic() >= self._report_retry_at:
                self._pause_report_key = pause_key
                try:
                    self._report_future = self.error_reporter.capture_pause(state=pause, background=True)
                except (OSError, ValueError, RuntimeError) as error:
                    self.notice.set(f"错误报告采集失败，稍后重试：{error}")
                    self._pause_report_key = None
                    self._report_retry_at = time.monotonic() + 10
        else:
            self._pause_report_key = None
        self.phase_dot.configure(fg=foreground)
        self.start_button.configure(state="normal" if state in ("stopped", "paused") and not self.busy else "disabled")
        self.stop_button.configure(state="normal" if state in ("running", "starting") and not self.busy else "disabled")
        self.hero_title.set(
            "正在启动机器人"
            if self.busy == "start"
            else "正在停止机器人"
            if self.busy
            else {
                "running": "自动对战进行中",
                "starting": "正在连接与恢复",
                "stopped": "准备好下一场对战",
                "paused": "机器人已暂停",
            }[state]
        )
        self.hero_detail.set(
            "请稍候，正在处理你的操作。"
            if self.busy
            else {
                "running": "自动出牌、结算并进入下一局。",
                "starting": "正在恢复对战连接，请稍候。",
                "stopped": "点击开始运行，进入无限 1V1 对战。",
                "paused": "请查看最近提醒，处理后可重新启动。",
            }[state]
        )
        latest_run = self.history_snapshots.get("all", {}).get("latest_session")
        if selected_strategy() == "random":
            live = read_random_status()
            if "rewards_received" in live:
                self._render_rewards(
                    {
                        "rewards": live["rewards_received"],
                        "coins": live.get("coins_received", 0),
                        "unknown_coin_items": live.get("unknown_coin_items", 0),
                    }
                )
            phase = RANDOM_PHASES.get(live.get("state"), "等待实时状态")
            if state == "running" and not self.busy:
                self.hero_title.set(phase)
                self.hero_detail.set("自动换卡组、出牌和结算，持续进入下一场对战。")
            self.run_detail.set(
                f"当前策略：随机卡组 · 无限对战  /  已完成 {live.get('completed', '—')} 局  /  已生成 {live.get('generated_decks', '—')} 套  /  一键领取 {live.get('claim_all_batches', 0)} 次"
            )
            action = live.get("last_action", {})
            if action:
                card = CARD_NAMES.get(action.get("card"), f"第{action.get('slot', 0) + 1}张手牌")
                self.run_detail.set(
                    self.run_detail.get()
                    + f"\n最近动作：{CATEGORY_NAMES.get(action.get('category'), '出牌')} · {card} · {ACTION_PHASES.get(action.get('phase'), '观察中')}  /  本局下牌已确认 {live.get('cards_confirmed', 0)} 次"
                )
            profile = live.get("combat_profile", {})
            if live.get("strategy_version"):
                self.flow_detail.set(
                    f"战术：{profile.get('mode', '建立卡组计划')}  /  当前规则：{live.get('decision_reason', '等待决策')}"
                )
            else:
                self.flow_detail.set("换卡组 → 经典1V1 → 底部领取全部检查 → 下一局")
            random_events = []
            for line in tail_log(RANDOM_TRACE, max_lines=60):
                try:
                    value = json.loads(line)
                    if isinstance(value, dict):
                        random_events.append(value)
                except ValueError:
                    continue
            reward = random_reward_text(random_events)
            if reward:
                self.reward_detail.set("最近奖励检查：" + reward)
            if state == "paused":
                failure = next(
                    (event.get("reason", "") for event in reversed(random_events) if event.get("event") == "paused"), ""
                )
                self.hero_detail.set(failure or "运行异常已暂停，查看运行日志后重新启动。")
        elif latest_run:
            detail = json.loads(latest_run["detail"])
            decision = detail.get("decision") or {}
            action = CATEGORY_NAMES.get(decision.get("category"), "等待场面识别")
            card = CARD_NAMES.get(decision.get("card"), "")
            self.run_detail.set(f"{policy_text(latest_run['policy'])}  /  {action} {card}")
            self.flow_detail.set("经典1V1 → 自动出牌 → 结算 → 下一局")
            self.reward_detail.set("")

        lines = tail_log(BATTLE_LOG, max_lines=60)
        mode = "raw" if self.raw_log.get() else "events"
        log_key = mode + "\n" + "\n".join(lines)
        if log_key != self.last_log_text:
            position = self.log_text.yview()[0]
            self.log_text.configure(state="normal")
            self.log_text.delete("1.0", "end")
            if self.raw_log.get():
                self.log_text.insert("end", "\n".join(lines) if lines else "尚无对战记录。", "body")
            else:
                entries = [entry for line in lines if (entry := display_event(line)) is not None]
                for stamp, kind, message in entries[-30:]:
                    self.log_text.insert("end", f"{stamp}   ", "time")
                    self.log_text.insert("end", f"{kind}   ", kind)
                    self.log_text.insert("end", f"{message}\n", "body")
                if not entries:
                    self.log_text.insert("end", "对战事件会显示在这里。启动机器人后即可查看。", "body")
            self.log_text.configure(state="disabled")
            if self.auto_scroll.get():
                self.log_text.see("end")
            else:
                self.log_text.yview_moveto(position)
            self.last_log_text = log_key
        event = next(
            (
                display_event(line)
                for line in reversed(lines)
                if any(key in line for key in ("对战开始", "对战结束", "恢复/重启"))
            ),
            None,
        )
        self.latest.set(f"最近更新  ·  {event[0]}  {event[2]}" if event else "等待新的对战事件")
        self.updated.set(f"已同步 {time.strftime('%H:%M:%S')}")
        self._fit_metrics()
        self._refresh_error_report()
        self._export_frontend_state(state)

    def _fit_metrics(self):
        for panel in self.fixed_panels:
            needed = panel.body.winfo_reqheight() + 2 * panel.padding
            if panel.winfo_height() != needed:
                panel.configure(height=needed)
        measured = tkfont.Font(family="Segoe UI", size=26, weight="bold")
        for key, widget in self.metric_values.items():
            available = max(40, widget.master.winfo_width() - 2)
            sizes = (22, 20, 18, 16, 14, 12) if key in ("rewards", "coins") else (26, 24, 22, 20, 18, 16)
            for size in sizes:
                measured.configure(size=size)
                if measured.measure(self.metrics[key].get()) <= available:
                    widget.configure(font=("Segoe UI", size, "bold"))
                    break

    def _export_frontend_state(self, state):
        data = {
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "pid": os.getpid(),
            "state": state,
            "scope": self.scope.get(),
            "phase": self.hero_title.get(),
            "metrics": {key: value.get() for key, value in self.metrics.items()},
            "tactics": self.flow_detail.get(),
            "actions": self.run_detail.get(),
            "hero_content_fits": self.hero_panel.body.winfo_reqheight() <= self.hero_panel.body.winfo_height(),
            "reward_status": self.reward_detail.get(),
            "refresh_seconds": 1,
            "layout": "windows-desktop-assistant",
            "application": "皇室战争助手",
            "frozen": bool(getattr(sys, "frozen", False)),
            "window_visible": not self._hidden,
            "desktop_shell": self.shell.diagnostics() if self.shell is not None else {},
            "latest_error_report": next(iter(self._error_catalog.values()), {}).get("report_md"),
            "error_report_count": len(self._error_catalog),
            "selected_error_report": self._selected_error_report,
            "selected_error_report_md": str(self._selected_report_path) if self._selected_report_path else None,
            "selected_error_report_png": str(self._error_image) if self._error_image else None,
            "live_view": self.live_view.diagnostics(),
            "metric_fits": {
                key: widget.winfo_reqwidth() <= widget.master.winfo_width()
                for key, widget in self.metric_values.items()
            },
        }
        path = FRONTEND_STATE
        try:
            atomic_write_json(path, data)
        except OSError:
            pass  # Diagnostic publication must not interrupt the control window.

    def _tick(self) -> None:
        if self._report_future is not None and self._report_future.done():
            future, self._report_future = self._report_future, None
            try:
                future.result()
            except Exception as error:
                self.notice.set(f"错误报告保存失败，稍后重试：{error}")
                self._pause_report_key = None
                self._report_retry_at = time.monotonic() + 10
            else:
                if bot_state() == "paused":
                    self.notice.set("任务已暂停，截图与原因已保存。请打开左侧错误报告。")
        try:
            status, payload = self.history_events.get_nowait()
        except queue.Empty:
            pass
        else:
            if status == "ok":
                self.history_snapshots = payload
                self._render_history()
            else:
                self.notice.set(f"战绩读取失败，已保留上次显示：{payload}")
        try:
            kind, message = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = None
            self.notice.set(message if kind == "ok" else f"操作失败：{message}")
            if self._exit_requested:
                if kind == "ok":
                    self._destroy_window()
                    return
                self._exit_requested = False
                self._show_window()
        self._refresh()
        self.root.after(1000, self._tick)

    def _action(self, name: str, function) -> None:
        if self.busy:
            return
        self.busy = name
        self.notice.set("正在连接 MEmu 并启动机器人…" if name == "start" else "正在停止后台机器人…")
        self._refresh()

        def worker() -> None:
            try:
                message = function()
                self.events.put(("ok", message))
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
                self.events.put(("error", str(error)))

        threading.Thread(target=worker, daemon=True).start()

    def _start(self) -> None:
        self._action("start", self._start_worker)

    def _stop(self) -> None:
        self._action("stop", self._stop_worker)

    @staticmethod
    def _start_worker(max_battles: int = 0, *, cancel_event=None, launch_lock=None, on_watchdog_started=None) -> str:
        def run(command, timeout=20):
            _check_start_cancelled(cancel_event)
            if cancel_event is None:
                return _run(command) if timeout == 20 else _run(command, timeout=timeout)
            return _run_cancellable(command, timeout, cancel_event)

        def wait(seconds):
            if cancel_event is None:
                time.sleep(seconds)
            else:
                cancel_event.wait(seconds)
                _check_start_cancelled(cancel_event)

        _check_start_cancelled(cancel_event)
        started_at_ns = time_ns()
        if max_battles < 0:
            raise ValueError("max_battles must be nonnegative")
        if bot_state() not in ("stopped", "paused"):
            return "机器人已在运行。"
        for tool in (PYTHON, ADB, MEMUC, WATCHDOG):
            if not tool.is_file():
                raise RuntimeError(f"缺少必要文件：{tool}")

        vm = run([str(MEMUC), "isvmrunning", "-i", "0"])
        if vm.returncode != 0 or vm.stdout.strip().lower() != "running":
            listed = run([str(MEMUC), "listvms"])
            vm_rows = [line.strip().split(",", 1) for line in listed.stdout.splitlines() if line.strip()]
            if listed.returncode != 0 or len(vm_rows) != 1 or len(vm_rows[0]) != 2 or vm_rows[0][0] != "0":
                raise RuntimeError("只能自动启动唯一的 0 号 MEmu 实例；实例列表不明确，已停止启动")
            memu_exe = MEMUC.with_name("MEmu.exe")
            if not memu_exe.is_file():
                raise RuntimeError(f"缺少必要文件：{memu_exe}")
            # memuc start can replace this installation's disk attachments.
            with launch_lock if launch_lock is not None else nullcontext():
                _check_start_cancelled(cancel_event)
                subprocess.Popen(
                    [str(memu_exe)],
                    cwd=MEMUC.parent,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )

        deadline = time.monotonic() + 90
        while True:
            _check_start_cancelled(cancel_event)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("MEmu 启动超时：ADB 设备未连接或 Android 未完成启动")
            try:
                device = run([str(ADB), "-s", SERIAL, "get-state"], timeout=min(5, remaining))
                remaining = deadline - time.monotonic()
                if device.returncode == 0 and device.stdout.strip() == "device":
                    if remaining > 0:
                        boot = run(
                            [str(ADB), "-s", SERIAL, "shell", "getprop", "sys.boot_completed"],
                            timeout=min(5, remaining),
                        )
                        if boot.returncode == 0 and boot.stdout.strip() == "1" and time.monotonic() < deadline:
                            break
                elif remaining > 0:
                    run([str(ADB), "connect", SERIAL], timeout=min(5, remaining))
            except (OSError, subprocess.TimeoutExpired):
                pass  # A cold boot can outlast one ADB connection attempt.
            remaining = deadline - time.monotonic()
            if remaining > 0:
                wait(min(2, remaining))

        package_deadline = time.monotonic() + 20
        valid_missing_queries = 0
        while True:
            _check_start_cancelled(cancel_event)
            remaining = package_deadline - time.monotonic()
            if remaining <= 0:
                if valid_missing_queries >= 2:
                    raise RuntimeError("MEmu 内未找到腾讯版《皇室战争》")
                raise RuntimeError("Android 游戏包列表尚未就绪；请稍后重试")
            try:
                installed = run(
                    [str(ADB), "-s", SERIAL, "shell", "pm", "list", "packages", PACKAGE],
                    timeout=min(5, remaining),
                )
                packages = [line.strip() for line in installed.stdout.splitlines() if line.strip()]
                if installed.returncode == 0 and all(line.startswith("package:") for line in packages):
                    if f"package:{PACKAGE}" in packages:
                        valid_missing_queries = 0
                        if time.monotonic() < package_deadline:
                            break
                    else:
                        valid_missing_queries += 1
                else:
                    valid_missing_queries = 0
            except (OSError, subprocess.TimeoutExpired):
                valid_missing_queries = 0
            remaining = package_deadline - time.monotonic()
            if remaining > 0:
                wait(min(1, remaining))
        launched = run(
            [
                str(ADB),
                "-s",
                SERIAL,
                "shell",
                "monkey",
                "-p",
                PACKAGE,
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
            ]
        )
        if launched.returncode != 0:
            raise RuntimeError("腾讯版《皇室战争》启动失败")

        command = component_command(
            PYTHON,
            WATCHDOG,
            "--adb",
            str(ADB),
            "--serial",
            SERIAL,
            "--memuc",
            str(MEMUC),
            "--vm-index",
            "0",
            "--log",
            str(BATTLE_LOG),
            "--watchdog-log",
            str(WATCHDOG_LOG),
            "--pid-file",
            str(PID_FILE),
            "--strategy",
            selected_strategy(),
            "--started-at-ns",
            str(started_at_ns),
        )
        if max_battles:
            command.extend(["--max-battles", str(max_battles)])
        with launch_lock if launch_lock is not None else nullcontext():
            _check_start_cancelled(cancel_event)
            watchdog_process = subprocess.Popen(
                command,
                cwd=REPO,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if on_watchdog_started is not None:
                try:
                    on_watchdog_started(watchdog_process)
                except (OSError, psutil.Error, RuntimeError):
                    if watchdog_process.poll() is None:
                        watchdog_process.terminate()
                        watchdog_process.wait(timeout=2)
                    raise
        deadline = time.monotonic() + 18
        while time.monotonic() < deadline:
            _check_start_cancelled(cancel_event)
            if bot_state() == "running":
                return (
                    f"限量验收已启动：完成{max_battles}场并回到大厅后停止。"
                    if max_battles
                    else "机器人已启动；关闭控制窗口不影响后台运行。"
                )
            wait(0.5)
        if bot_state() == "starting":
            return "守护进程已启动，运行器正在恢复；请查看最近事件。"
        raise RuntimeError("守护进程未能启动；请查看 cn-watchdog.log")

    @staticmethod
    def _stop_worker() -> str:
        from scripts.stop_cn_1v1 import stop_bot  # noqa: PLC0415

        stop_bot(PID_FILE)
        return "机器人已停止；MEmu 和游戏保持打开。"

    def _on_close(self) -> None:
        if self.shell is None or not self.shell.diagnostics().get("tray_icon_added", False):
            self.notice.set("系统托盘暂不可用；请使用应用菜单退出软件。")
            return
        if self._attach_after_id is not None:
            self.root.after_cancel(self._attach_after_id)
            self._attach_after_id = None
        self._restore_embedding = self._restore_embedding or self.live_view.host.embedded
        try:
            self.live_view.host.detach()
        except (OSError, RuntimeError) as error:
            self.notice.set(f"模拟器窗口还原失败，请重试：{error}")
            return
        self.live_view._state = "detached"
        self.live_view._show_state()
        self._hidden = True
        self.notice.set("已收进系统托盘；双击托盘图标可打开主界面。")
        self.root.withdraw()

    def _show_window(self):
        self._hidden = False
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        if self._restore_embedding:
            if self._attach_after_id is not None:
                self.root.after_cancel(self._attach_after_id)
            self._attach_after_id = self.root.after(150, self._restore_live_view)

    def _restore_live_view(self):
        self._attach_after_id = None
        if not self._hidden:
            self._restore_embedding = False
            self.live_view.attach()

    def _request_exit(self):
        if self.busy:
            self._show_window()
            self.notice.set("当前操作尚未完成，请稍后退出软件。")
            return
        if bot_state() in ("running", "starting"):
            self._exit_requested = True
            self._action("stop", self._stop_worker)
        else:
            self._destroy_window()

    def _destroy_window(self):
        if self._attach_after_id is not None:
            self.root.after_cancel(self._attach_after_id)
            self._attach_after_id = None
        try:
            self.live_view.close()
        except (OSError, RuntimeError) as error:
            self._exit_requested = False
            self._show_window()
            self.notice.set(f"模拟器窗口还原失败，已保留软件窗口：{error}")
            return
        self.history_stop.set()
        if self.shell is not None:
            self.shell.close()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main():
    instance = acquire_single_instance("皇室战争助手")
    if not instance.is_primary:
        instance.close()
        return
    try:
        ControlWindow(instance=instance).run()
    finally:
        instance.close()


if __name__ == "__main__":
    main()
