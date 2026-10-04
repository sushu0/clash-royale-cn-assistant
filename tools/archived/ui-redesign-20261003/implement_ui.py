from pathlib import Path

path = Path(r'D:\codex\CodexWork\clash\py-clash-bot\scripts\cn_bot_control.py')
source = path.read_text(encoding='utf-8')
start = source.index('        self.page = tk.Frame(self.root')
end = source.index('    def _label(', start)
layout = '''        self.fixed_panels = []
        self._build_sidebar()
        self.page = tk.Frame(self.root, autostyle=False, bg=COLORS["page"])
        self.page.columnconfigure(0, weight=1)
        self.page.rowconfigure(4, weight=1)
        self._build_header()
        self._build_running_panel()
        self._build_metrics()
        self._build_insights()
        self._build_details()
        self._build_footer()
        self.root.bind("<Configure>", self._resize)
        for index in range(3):
            self.root.bind(f"<Control-Key-{index + 1}>", lambda _event, view=index: self._select_view(view))
        self._select_view(0)
        self.root.update_idletasks()
        self._resize(type("Size", (), {"widget": self.root, "width": self.root.winfo_width(),
                                       "height": self.root.winfo_height()})())
        self._fit_metrics()
        self._refresh()
        threading.Thread(target=self._history_worker, daemon=True).start()
        self.root.after(2000, self._tick)

    def _build_sidebar(self):
        self.sidebar = tk.Frame(self.root, autostyle=False, bg=COLORS["sidebar"])
        brand = tk.Frame(self.sidebar, autostyle=False, bg=COLORS["sidebar"])
        brand.pack(fill="x", padx=20, pady=(30, 38))
        mark = tk.Canvas(brand, autostyle=False, width=32, height=32,
                         bg=COLORS["sidebar"], highlightthickness=0)
        mark.pack(side="left", padx=(0, 10))
        mark.create_polygon(3, 10, 10, 16, 16, 5, 22, 16, 29, 10, 25, 27, 7, 27,
                            fill=COLORS["cream"], outline="")
        words = tk.Frame(brand, autostyle=False, bg=COLORS["sidebar"])
        words.pack(side="left")
        self._label(words, "皇室战争", size=14, bold=True, fg="#ffffff").pack(anchor="w")
        self._label(words, "自动对战控制台", size=8, fg=COLORS["nav_muted"]).pack(anchor="w", pady=(4, 0))
        self.nav_buttons = []
        for index, (title, icon) in enumerate((("对局记录", "records"), ("策略对比", "chart"), ("运行日志", "log"))):
            button = PanelButton(self.sidebar, text=title, icon=icon, variant="nav", height=48,
                                 command=lambda view=index: self._select_view(view))
            button.pack(fill="x", padx=12, pady=(0, 9))
            self.nav_buttons.append(button)
        foot = tk.Frame(self.sidebar, autostyle=False, bg=COLORS["sidebar"])
        foot.pack(side="bottom", fill="x", padx=24, pady=26)
        tk.Frame(foot, autostyle=False, bg="#365047", height=1).pack(fill="x", pady=(0, 16))
        self._label(foot, "腾讯国服", size=9, fg=COLORS["nav_muted"]).pack(anchor="w")
        self._label(foot, "经典 1V1", size=9, fg=COLORS["nav_muted"]).pack(anchor="w", pady=(5, 0))

    def _build_header(self):
        header = tk.Frame(self.page, autostyle=False, bg=COLORS["page"])
        header.grid(row=0, column=0, sticky="ew", pady=(0, 18))
        heading = tk.Frame(header, autostyle=False, bg=COLORS["page"])
        heading.pack(side="left")
        self._label(heading, "对战总览", size=22, bold=True).pack(anchor="w")
        self._label(heading, "实时战绩与运行动态", size=9, fg=COLORS["muted"]).pack(anchor="w", pady=(3, 0))
        self.status = self._label(header, "●  检查中", size=9, fg=COLORS["muted"])
        self.status.pack(side="right", padx=(18, 0))
        self.scope_combo = ttk.Combobox(header, textvariable=self.scope, values=list(SCOPES),
                                        state="readonly", width=12, style="Scope.TCombobox", font=(FONT, 9))
        self.scope_combo.pack(side="right", ipady=4)
        self._label(header, "战绩范围", size=9, fg=COLORS["muted"]).pack(side="right", padx=(12, 10))
        self.scope_combo.bind("<<ComboboxSelected>>", lambda _event: self._render_history())

    def _build_running_panel(self):
        hero = RoundedPanel(self.page, fill=COLORS["surface"], padding=22, height=202)
        self.hero_panel = hero
        hero.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        self.fixed_panels.append(hero)
        hero.body.columnconfigure(0, weight=1)
        hero_left = tk.Frame(hero.body, autostyle=False, bg=COLORS["surface"])
        hero_left.grid(row=0, column=0, sticky="ew", padx=(0, 20))
        title_row = tk.Frame(hero_left, autostyle=False, bg=COLORS["surface"])
        title_row.pack(anchor="w")
        self.phase_dot = self._label(title_row, "●", size=16, fg=COLORS["green"])
        self.phase_dot.pack(side="left", padx=(0, 10))
        self._label(title_row, variable=self.hero_title, size=18, bold=True).pack(side="left")
        self.hero_detail_label = self._label(hero_left, variable=self.hero_detail, size=9, fg=COLORS["muted"])
        self.hero_detail_label.pack(anchor="w", pady=(5, 0))
        actions = tk.Frame(hero.body, autostyle=False, bg=COLORS["surface"])
        actions.grid(row=0, column=1, sticky="ne", pady=4)
        self.start_button = PanelButton(actions, text="启动机器人", icon="play", width=150, height=43,
                                        command=self._start)
        self.start_button.pack(side="left", padx=(0, 10))
        self.stop_button = PanelButton(actions, text="停止机器人", icon="stop", width=150, height=43,
                                       variant="danger", command=self._stop)
        self.stop_button.pack(side="left")
        details = tk.Frame(hero.body, autostyle=False, bg=COLORS["surface"])
        details.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(15, 0))
        self.run_detail_label = self._label(details, variable=self.run_detail, size=9, fg=COLORS["muted"])
        self.run_detail_label.pack(anchor="w", pady=(0, 5))
        self.flow_detail_label = self._label(details, variable=self.flow_detail, size=9, fg=COLORS["muted"])
        self.flow_detail_label.pack(anchor="w", pady=(0, 5))
        self.reward_detail_label = self._label(details, variable=self.reward_detail, size=9, fg=COLORS["muted"])
        self.reward_detail_label.pack(anchor="w")

    def _build_metrics(self):
        stats = RoundedPanel(self.page, fill=COLORS["surface"], padding=20, height=123)
        stats.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        self.fixed_panels.append(stats)
        cards = (("累计已结算", "total", COLORS["ink"]), ("累计胜利", "wins", COLORS["green"]),
                 ("累计失败", "losses", COLORS["red"]), ("累计胜率", "rate", COLORS["ink"]),
                 ("近 20 局胜率", "recent", COLORS["ink"]))
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
                    row=0, column=column * 2 + 1, sticky="ns", pady=2)

    def _build_insights(self):
        row = tk.Frame(self.page, autostyle=False, bg=COLORS["page"])
        row.grid(row=3, column=0, sticky="ew", pady=(0, 14))
        row.columnconfigure(0, weight=65, uniform="insight")
        row.columnconfigure(1, weight=35, uniform="insight")
        insight = RoundedPanel(row, fill=COLORS["surface"], padding=18, height=126)
        self.insight_panel = insight
        insight.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
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
        reward = RoundedPanel(row, fill=COLORS["reward_surface"], padding=18, height=126)
        reward.grid(row=0, column=1, sticky="nsew")
        self.fixed_panels.append(reward)
        self._label(reward.body, "奖励累计", size=11, bold=True).pack(anchor="w", pady=(0, 8))
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
            note = self._label(group, variable=self.metric_notes[key], size=8, fg=COLORS["muted"])
            note.pack(anchor="center", pady=(3, 0))
        tk.Frame(groups, autostyle=False, bg="#dce6dd", width=1).grid(row=0, column=1, sticky="ns", pady=4)

    def _build_details(self):
        self.detail_panel = RoundedPanel(self.page, fill=COLORS["surface"], padding=18)
        self.detail_panel.grid(row=4, column=0, sticky="nsew")
        self.notebook = ttk.Notebook(self.detail_panel.body, style="Console.TNotebook")
        self.notebook.pack(fill="both", expand=True)
        history_tab = tk.Frame(self.notebook, autostyle=False, bg=COLORS["surface"])
        version_tab = tk.Frame(self.notebook, autostyle=False, bg=COLORS["surface"])
        log_tab = tk.Frame(self.notebook, autostyle=False, bg=COLORS["surface"])
        self.notebook.add(history_tab, text="对局记录")
        self.notebook.add(version_tab, text="策略对比")
        self.notebook.add(log_tab, text="运行日志")
        toolbar = tk.Frame(history_tab, autostyle=False, bg=COLORS["surface"])
        toolbar.pack(fill="x", pady=(0, 12))
        self._label(toolbar, "对局记录", size=11, bold=True).pack(side="left", padx=(0, 12))
        self._label(toolbar, "最近 60 场 · 双击查看结算图", size=8, fg=COLORS["muted"]).pack(side="left")
        self.open_result_button = PanelButton(toolbar, text="查看结算图", command=self._open_result,
                                              variant="outline", width=130, height=33)
        self.open_result_button.pack(side="right")
        self.history_tree = self._tree(history_tab, (("time", "结算时间", 170), ("result", "胜负", 84),
                                       ("battle", "场次", 60), ("deployment", "出牌确认", 90),
                                       ("policy", "策略版本", 255), ("session", "运行批次", 175)))
        self.history_tree.bind("<Double-1>", lambda _event: self._open_result())
        self.history_tree.bind("<<ResultOpen>>", lambda _event: self._open_result())
        self.history_tree.bind("<<TreeviewSelect>>", lambda _event: self._update_result_button())
        self.history_source_label = self._label(history_tab, variable=self.history_info, size=8, fg=COLORS["muted"])
        self.history_source_label.pack(anchor="w", fill="x", pady=(10, 0))
        self._label(version_tab, "策略对比", size=11, bold=True).pack(anchor="w", pady=(3, 8))
        self._label(version_tab, "按实际运行版本独立统计；不同对手和样本量的胜率仅供观察。", size=9,
                    fg=COLORS["muted"]).pack(anchor="w", pady=(0, 12))
        self.version_tree = self._tree(version_tab, (("policy", "策略版本", 340), ("total", "局数", 70),
                                                     ("wins", "胜", 60), ("losses", "负", 60),
                                                     ("unknown", "平 / 未知", 100), ("rate", "胜率", 90)))
        log_tab.columnconfigure(0, weight=1)
        log_tab.rowconfigure(2, weight=1)
        journal_head = tk.Frame(log_tab, autostyle=False, bg=COLORS["surface"])
        journal_head.grid(row=0, column=0, sticky="ew", pady=(3, 0))
        self._label(journal_head, "运行日志", size=11, bold=True).pack(side="left")
        self._label(journal_head, "每秒同步", size=8, fg=COLORS["muted"]).pack(side="left", padx=12)
        ttk.Checkbutton(journal_head, text="原始日志", variable=self.raw_log, command=self._refresh,
                        style="Journal.TCheckbutton").pack(side="right")
        ttk.Checkbutton(journal_head, text="自动滚动", variable=self.auto_scroll,
                        command=lambda: self.log_text.see("end") if self.auto_scroll.get() else None,
                        style="Journal.TCheckbutton").pack(side="right", padx=(0, 14))
        self.latest_label = self._label(log_tab, variable=self.latest, size=9, fg=COLORS["muted"])
        self.latest_label.grid(row=1, column=0, sticky="w", pady=(8, 12))
        log_frame = tk.Frame(log_tab, autostyle=False, bg=COLORS["surface"])
        log_frame.grid(row=2, column=0, sticky="nsew")
        self.log_text = tk.Text(log_frame, autostyle=False, wrap="word", height=4, font=(FONT, 9),
                                bg=COLORS["surface"], fg=COLORS["ink"], relief="flat", bd=0,
                                highlightthickness=0, padx=0, pady=2, spacing1=5, spacing3=5,
                                selectbackground="#dce9de", selectforeground=COLORS["ink"], state="disabled")
        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview, style="Console.Vertical.TScrollbar")
        scrollbar.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.tag_configure("time", foreground=COLORS["muted"], font=("Consolas", 9))
        self.log_text.tag_configure("body", foreground=COLORS["ink"])
        for tag, color in {"对战": COLORS["green"], "胜利": COLORS["green"], "失败": COLORS["red"],
                           "恢复": "#947441", "提醒": "#947441", "启动": COLORS["green"],
                           "完成": COLORS["green"], "记录": COLORS["muted"]}.items():
            self.log_text.tag_configure(tag, foreground=color, font=(FONT, 9, "bold"))
        self._update_result_button()

    def _build_footer(self):
        footer = tk.Frame(self.page, autostyle=False, bg=COLORS["page"])
        footer.grid(row=5, column=0, sticky="ew", pady=(12, 0))
        self.notice_label = self._label(footer, variable=self.notice, size=8, fg=COLORS["muted"])
        self.notice_label.pack(side="left", fill="x", expand=True)
        self._label(footer, variable=self.updated, size=8, fg=COLORS["muted"]).pack(side="right")

    def _select_view(self, index):
        self.notebook.select(index)
        for position, button in enumerate(self.nav_buttons):
            button.set_selected(position == index)

    def _update_result_button(self):
        self.open_result_button.configure(state="normal" if self.history_tree.selection() else "disabled")

'''
source = source[:start] + layout + source[end:]
source = source.replace('width = min(1180, self.root.winfo_screenwidth()-80)',
                        'width = min(1440, self.root.winfo_screenwidth()-80)')
source = source.replace('height = min(920, self.root.winfo_screenheight()-100)',
                        'height = min(960, self.root.winfo_screenheight()-100)')
source = source.replace('self.root.minsize(900, 740)', 'self.root.minsize(1080, 800)')
source = source.replace('tree = ttk.Treeview(holder,', 'tree = ResultTree(holder,')
source = source.replace('    RoundedPanel,', '    ResultTree,\n    RoundedPanel,')
source = source.replace('("time", "结算时间", 170)', '("time", "结算时间", 160)')
source = source.replace('("policy", "策略版本", 255)', '("policy", "策略版本", 235)')
source = source.replace('("session", "运行批次", 175)', '("session", "运行批次", 175)')
source = source.replace('vertical = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)',
                        'vertical = ttk.Scrollbar(holder, orient="vertical", command=tree.yview, style="Console.Vertical.TScrollbar")')
source = source.replace('horizontal = ttk.Scrollbar(holder, orient="horizontal", command=tree.xview)',
                        'horizontal = ttk.Scrollbar(holder, orient="horizontal", command=tree.xview, style="Console.Horizontal.TScrollbar")')
source = source.replace('            tree.heading(name, text=title)', '            tree.heading(name, text=title, anchor="w")')
tag_start = source.index('        for tag, color in {"胜利":', source.index('    def _tree'))
tag_end = source.index('        return tree', tag_start)
source = source[:tag_start] + '''        for tag in ("胜利", "失败", "未知", "平局"):
            tree.tag_configure(tag, foreground=COLORS["ink"])
''' + source[tag_end:]
source = source.replace('self.session_detail.set(f"最近运行  {session[\'total\']} 局',
                        'self.session_detail.set(f"{session[\'total\']} 局')
source = source.replace('bg="#eef2f7"', 'bg="#eef2ee"')
source = source.replace('("#eef2f7", COLORS["muted"])', '("#eef2ee", COLORS["muted"])')
source = source.replace('        self.history_tree.yview_moveto(position)',
                        '        self.history_tree.yview_moveto(position)\n        self._update_result_button()')
style_start = source.index('    def _setup_styles(self):')
style_end = source.index('    def _refresh(self)', style_start)
source = source[:style_start] + '''    def _setup_styles(self):
        style = self.root.style
        style.configure("Console.TNotebook", background=COLORS["surface"], borderwidth=0, tabmargins=0)
        style.layout("Console.TNotebook.Tab", [])
        style.configure("Journal.TCheckbutton", background=COLORS["surface"],
                        foreground=COLORS["muted"], font=(FONT, 9))
        style.map("Journal.TCheckbutton", background=[("active", COLORS["surface"])])
        style.configure("Scope.TCombobox", fieldbackground=COLORS["surface"], background=COLORS["surface"],
                        foreground=COLORS["ink"], bordercolor=COLORS["border"], arrowcolor=COLORS["muted"],
                        padding=(8, 4), font=(FONT, 9))
        style.map("Scope.TCombobox", fieldbackground=[("readonly", COLORS["surface"])],
                  foreground=[("readonly", COLORS["ink"])], selectbackground=[("readonly", COLORS["surface"])],
                  selectforeground=[("readonly", COLORS["ink"])])
        style.configure("Battle.Treeview", font=(FONT, 9), rowheight=36, background=COLORS["surface"],
                        fieldbackground=COLORS["surface"], foreground=COLORS["ink"], borderwidth=0,
                        bordercolor=COLORS["surface"], relief="flat")
        style.configure("Battle.Treeview.Heading", font=(FONT, 9), background="#f2f5f1",
                        foreground=COLORS["muted"], padding=(10, 8), relief="flat", borderwidth=0)
        style.map("Battle.Treeview", background=[("selected", "#edf3ed")],
                  foreground=[("selected", COLORS["ink"])])
        style.map("Battle.Treeview.Heading", background=[("active", "#eaf0e9")])
        for orientation in ("Vertical", "Horizontal"):
            name = f"Console.{orientation}.TScrollbar"
            style.configure(name, background="#dce3dc", troughcolor=COLORS["surface"],
                            bordercolor=COLORS["surface"], arrowcolor=COLORS["muted"], borderwidth=0, arrowsize=11)

    def _resize(self, event):
        if event.widget is not self.root:
            return
        side = 202 if event.width >= 1250 else 178
        margin = 26 if event.width >= 1250 else 20
        width = max(1, event.width - side - 2 * margin)
        self.sidebar.place(x=0, y=0, width=side, height=event.height)
        self.page.place(x=side + margin, y=20, width=width, height=max(1, event.height - 40))
        self.hero_detail_label.configure(wraplength=max(220, width - 380))
        for widget in (self.run_detail_label, self.flow_detail_label, self.reward_detail_label):
            widget.configure(wraplength=max(300, width - 48))
        self.session_label.configure(wraplength=max(300, int(width * 0.65) - 58))
        self.latest_label.configure(wraplength=max(250, width - 50))
        self.notice_label.configure(wraplength=max(200, width - 170))
        self.history_source_label.configure(wraplength=max(300, width - 40))
        chip_width = max(14, min(24, (int(width * 0.65) - 106) // 20 - 3))
        for chip in self.result_chips:
            chip.configure(width=chip_width)
        for panel in self.fixed_panels:
            panel.configure(height=panel.body.winfo_reqheight() + 2 * panel.padding)
        self.root.after_idle(self._fit_metrics)

''' + source[style_end:]
source = source.replace('self.status.configure(text=f"●  {label}", bg=background, fg=foreground)',
                        'self.status.configure(text=f"●  {label}", bg=COLORS["page"], fg=foreground)\n        self.phase_dot.configure(fg=foreground)')
fit_start = source.index('    def _fit_metrics(self):')
fit_end = source.index('    def _export_frontend_state(', fit_start)
source = source[:fit_start] + '''    def _fit_metrics(self):
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

''' + source[fit_end:]
path.write_text(source, encoding='utf-8')
print(path)
