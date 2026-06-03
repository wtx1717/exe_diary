from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
import json
import math
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText
import traceback
from typing import Any, TypeVar

from exe_diary.app.workflow import AppWorkflow, FitBackfillResult, FitCleanupResult
from exe_diary.config import Settings, load_settings
from exe_diary.db.database import Database
from exe_diary.db.repositories import ActivityNoteRepository, ActivityRepository, SyncRunRepository
from exe_diary.garmin.sync import SyncResult
from exe_diary.ui.prompt import PromptService


Event = tuple[str, str, Any, Callable[[Any], None] | None]
_T = TypeVar("_T")


class DiaryDesktopApp:
    def __init__(self, root: tk.Tk, settings: Settings, database: Database) -> None:
        self._root = root
        self._settings = settings
        self._database = database
        self._workflow = AppWorkflow(settings, database)
        self._events: queue.Queue[Event] = queue.Queue()
        self._busy = False

        self._limit_var = tk.StringVar(value="")
        self._from_date_var = tk.StringVar(value=date.today().isoformat())
        self._to_date_var = tk.StringVar(value=date.today().isoformat())
        self._view_mode_var = tk.StringVar(value="all")
        self._view_start_var = tk.StringVar(value=date.today().isoformat())
        self._view_end_var = tk.StringVar(value=date.today().isoformat())
        self._status_var = tk.StringVar(value="就绪")
        self._active_activity_tree: ttk.Treeview | None = None

        self._build()
        self._root.after(100, self._drain_events)
        self.refresh()

    def _build(self) -> None:
        self._root.title("exe_diary 跑步训练日记")
        self._root.geometry("1040x720")
        self._root.minsize(920, 620)

        root_frame = ttk.Frame(self._root, padding=12)
        root_frame.grid(row=0, column=0, sticky="nsew")
        self._root.columnconfigure(0, weight=1)
        self._root.rowconfigure(0, weight=1)
        root_frame.columnconfigure(1, weight=1)
        root_frame.rowconfigure(1, weight=1)

        header = ttk.Frame(root_frame)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)

        title = ttk.Label(header, text="exe_diary 跑步训练日记", font=("", 16, "bold"))
        title.grid(row=0, column=0, sticky="w")
        ttk.Label(header, textvariable=self._status_var).grid(row=0, column=1, sticky="e")

        sidebar = ttk.Frame(root_frame, width=270)
        sidebar.grid(row=1, column=0, sticky="nsw", padx=(0, 12))
        sidebar.columnconfigure(0, weight=1)

        self._build_actions(sidebar)
        self._build_settings(sidebar)

        content = ttk.Frame(root_frame)
        content.grid(row=1, column=1, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)
        content.rowconfigure(1, weight=0)

        self._build_tables(content)
        self._build_log(content)

    def _build_actions(self, parent: ttk.Frame) -> None:
        actions = ttk.LabelFrame(parent, text="操作", padding=10)
        actions.grid(row=0, column=0, sticky="ew")
        actions.columnconfigure(0, weight=1)

        ttk.Button(actions, text="初始化数据库", command=self._init_db).grid(row=0, column=0, sticky="ew", pady=3)
        ttk.Button(actions, text="同步今天", command=self._sync_today).grid(row=1, column=0, sticky="ew", pady=3)
        ttk.Button(actions, text="同步最近活动", command=self._sync_latest).grid(row=2, column=0, sticky="ew", pady=3)
        ttk.Button(actions, text="同步日期范围", command=self._sync_range).grid(row=3, column=0, sticky="ew", pady=3)
        ttk.Button(actions, text="同步今天并补填", command=self._run_today_with_prompts).grid(
            row=4,
            column=0,
            sticky="ew",
            pady=3,
        )
        ttk.Button(actions, text="补填待记录活动", command=self.prompt_notes).grid(row=5, column=0, sticky="ew", pady=3)
        ttk.Button(actions, text="查看活动详情", command=self._show_selected_activity_detail).grid(
            row=6,
            column=0,
            sticky="ew",
            pady=(10, 3),
        )
        ttk.Button(actions, text="回填 FIT 明细", command=self._backfill_fit_details).grid(
            row=7,
            column=0,
            sticky="ew",
            pady=3,
        )
        ttk.Button(actions, text="清理孤立 FIT", command=self._cleanup_orphan_fit_files).grid(
            row=8,
            column=0,
            sticky="ew",
            pady=3,
        )
        ttk.Button(actions, text="删除选中活动", command=self._delete_selected_activity).grid(
            row=9,
            column=0,
            sticky="ew",
            pady=3,
        )
        ttk.Button(actions, text="刷新", command=self.refresh).grid(row=10, column=0, sticky="ew", pady=(10, 3))

    def _build_settings(self, parent: ttk.Frame) -> None:
        settings = ttk.LabelFrame(parent, text="同步参数", padding=10)
        settings.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        settings.columnconfigure(1, weight=1)

        ttk.Label(settings, text="开始日期").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(settings, textvariable=self._from_date_var, width=14).grid(row=0, column=1, sticky="ew", pady=4)

        ttk.Label(settings, text="结束日期").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(settings, textvariable=self._to_date_var, width=14).grid(row=1, column=1, sticky="ew", pady=4)

        ttk.Label(settings, text="活动上限").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(settings, textvariable=self._limit_var, width=14).grid(row=2, column=1, sticky="ew", pady=4)

        paths = ttk.LabelFrame(parent, text="路径", padding=10)
        paths.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        paths.columnconfigure(0, weight=1)
        ttk.Label(paths, text=f"数据库：{self._settings.db_path}", wraplength=250).grid(row=0, column=0, sticky="w")
        ttk.Label(paths, text=f"FIT：{self._settings.fit_raw_dir}", wraplength=250).grid(row=1, column=0, sticky="w")

    def _build_tables(self, parent: ttk.Frame) -> None:
        notebook = ttk.Notebook(parent)
        notebook.grid(row=0, column=0, sticky="nsew")

        recent_frame = ttk.Frame(notebook, padding=(0, 8, 0, 0))
        recent_frame.columnconfigure(0, weight=1)
        recent_frame.rowconfigure(1, weight=1)
        self._build_activity_view_controls(recent_frame)
        self._recent_tree = ttk.Treeview(
            recent_frame,
            columns=("time", "name", "distance", "duration", "pace", "hr", "note"),
            show="headings",
            height=14,
        )
        self._configure_tree(
            self._recent_tree,
            {
                "time": ("时间", 150),
                "name": ("活动", 220),
                "distance": ("距离", 80),
                "duration": ("用时", 80),
                "pace": ("配速", 80),
                "hr": ("心率", 70),
                "note": ("记录", 70),
            },
        )
        self._recent_tree.grid(row=1, column=0, sticky="nsew")
        recent_scrollbar = ttk.Scrollbar(recent_frame, orient="vertical", command=self._recent_tree.yview)
        recent_scrollbar.grid(row=1, column=1, sticky="ns")
        self._recent_tree.configure(yscrollcommand=recent_scrollbar.set)
        self._bind_activity_tree(self._recent_tree)
        notebook.add(recent_frame, text="活动")

        pending_frame = ttk.Frame(notebook, padding=(0, 8, 0, 0))
        pending_frame.columnconfigure(0, weight=1)
        pending_frame.rowconfigure(0, weight=1)
        self._pending_tree = ttk.Treeview(
            pending_frame,
            columns=("time", "name", "distance", "duration", "pace", "hr"),
            show="headings",
            height=14,
        )
        self._configure_tree(
            self._pending_tree,
            {
                "time": ("时间", 150),
                "name": ("活动", 260),
                "distance": ("距离", 80),
                "duration": ("用时", 80),
                "pace": ("配速", 80),
                "hr": ("心率", 70),
            },
        )
        self._pending_tree.grid(row=0, column=0, sticky="nsew")
        pending_scrollbar = ttk.Scrollbar(pending_frame, orient="vertical", command=self._pending_tree.yview)
        pending_scrollbar.grid(row=0, column=1, sticky="ns")
        self._pending_tree.configure(yscrollcommand=pending_scrollbar.set)
        self._bind_activity_tree(self._pending_tree)
        notebook.add(pending_frame, text="待补填")

        sync_frame = ttk.Frame(notebook, padding=(0, 8, 0, 0))
        sync_frame.columnconfigure(0, weight=1)
        sync_frame.rowconfigure(0, weight=1)
        self._sync_tree = ttk.Treeview(
            sync_frame,
            columns=("started", "finished", "status", "downloaded", "parsed", "errors", "message"),
            show="headings",
            height=14,
        )
        self._configure_tree(
            self._sync_tree,
            {
                "started": ("开始", 145),
                "finished": ("结束", 145),
                "status": ("状态", 70),
                "downloaded": ("下载", 60),
                "parsed": ("入库", 60),
                "errors": ("错误", 60),
                "message": ("摘要", 280),
            },
        )
        self._sync_tree.grid(row=0, column=0, sticky="nsew")
        sync_scrollbar = ttk.Scrollbar(sync_frame, orient="vertical", command=self._sync_tree.yview)
        sync_scrollbar.grid(row=0, column=1, sticky="ns")
        self._sync_tree.configure(yscrollcommand=sync_scrollbar.set)
        notebook.add(sync_frame, text="同步记录")

    def _build_activity_view_controls(self, parent: ttk.Frame) -> None:
        controls = ttk.Frame(parent)
        controls.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        controls.columnconfigure(9, weight=1)

        ttk.Label(controls, text="视角").grid(row=0, column=0, sticky="w", padx=(0, 4))
        view_options = (("全部", "all"), ("日", "day"), ("周", "week"), ("月", "month"), ("自定义", "custom"))
        for index, (label, value) in enumerate(view_options, start=1):
            ttk.Radiobutton(
                controls,
                text=label,
                value=value,
                variable=self._view_mode_var,
                command=self._apply_activity_view,
            ).grid(row=0, column=index, sticky="w", padx=2)

        ttk.Label(controls, text="开始").grid(row=0, column=6, sticky="e", padx=(14, 4))
        ttk.Entry(controls, textvariable=self._view_start_var, width=12).grid(row=0, column=7, sticky="w")
        ttk.Label(controls, text="结束").grid(row=0, column=8, sticky="e", padx=(10, 4))
        ttk.Entry(controls, textvariable=self._view_end_var, width=12).grid(row=0, column=9, sticky="w")

        ttk.Button(controls, text="应用", command=self._apply_activity_view).grid(row=0, column=10, padx=(10, 0))
        ttk.Button(controls, text="今天", command=self._show_today).grid(row=0, column=11, padx=(6, 0))
        ttk.Button(controls, text="详情", command=self._show_selected_activity_detail).grid(row=0, column=12, padx=(14, 0))
        ttk.Button(controls, text="删除", command=self._delete_selected_activity).grid(row=0, column=13, padx=(6, 0))

    def _bind_activity_tree(self, tree: ttk.Treeview) -> None:
        tree.bind("<<TreeviewSelect>>", lambda _event, selected_tree=tree: self._remember_activity_tree(selected_tree))
        tree.bind("<Double-1>", lambda _event: self._show_selected_activity_detail())

    def _build_log(self, parent: ttk.Frame) -> None:
        log_frame = ttk.LabelFrame(parent, text="日志", padding=8)
        log_frame.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        log_frame.columnconfigure(0, weight=1)
        self._log = ScrolledText(log_frame, height=8, wrap="word")
        self._log.grid(row=0, column=0, sticky="ew")
        self._log.configure(state="disabled")

    def _configure_tree(self, tree: ttk.Treeview, columns: dict[str, tuple[str, int]]) -> None:
        for key, (heading, width) in columns.items():
            tree.heading(key, text=heading)
            tree.column(key, width=width, minwidth=60, anchor="w", stretch=key in {"name", "message", "value"})

    def refresh(self) -> None:
        try:
            from_date, to_date = self._activity_view_dates()
            self._database.initialize()
            with self._database.connect() as connection:
                activity_repository = ActivityRepository(connection)
                if from_date is None or to_date is None:
                    activities = activity_repository.list_all()
                else:
                    activities = activity_repository.list_between(from_date.isoformat(), to_date.isoformat())
                pending = activity_repository.list_without_notes()
                sync_runs = SyncRunRepository(connection).list_recent(limit=30)
        except Exception as exc:
            self._set_status(f"刷新失败：{exc}")
            self._append_log(f"刷新失败：{exc}")
            return

        self._replace_activity_rows(
            self._recent_tree,
            [
                (
                    int(activity["id"]),
                    activity.get("start_time"),
                    activity.get("activity_name"),
                    _km(activity.get("distance_m")),
                    _duration(activity.get("duration_s")),
                    _pace(activity.get("avg_pace_s_per_km")),
                    _value(activity.get("avg_hr")),
                    "已填" if activity.get("has_note") else "待填",
                )
                for activity in activities
            ],
        )
        self._replace_activity_rows(
            self._pending_tree,
            [
                (
                    int(activity["id"]),
                    activity.get("start_time"),
                    activity.get("activity_name"),
                    _km(activity.get("distance_m")),
                    _duration(activity.get("duration_s")),
                    _pace(activity.get("avg_pace_s_per_km")),
                    _value(activity.get("avg_hr")),
                )
                for activity in pending
            ],
        )
        self._replace_rows(
            self._sync_tree,
            [
                (
                    run.get("started_at"),
                    run.get("finished_at") or "",
                    run.get("status"),
                    run.get("new_fit_count"),
                    run.get("parsed_count"),
                    run.get("error_count"),
                    _single_line(run.get("message")),
                )
                for run in sync_runs
            ],
        )
        self._set_status(
            f"就绪：{self._activity_view_status_text(from_date, to_date)} "
            f"{len(activities)} 条，待补填 {len(pending)}"
        )

    def _activity_view_dates(self) -> tuple[date | None, date | None]:
        mode = self._view_mode_var.get()

        if mode == "all":
            return None, None

        anchor = _read_date_text(self._view_start_var.get(), "开始日期")

        if mode == "day":
            from_date = anchor
            to_date = anchor
        elif mode == "week":
            from_date = anchor - timedelta(days=anchor.weekday())
            to_date = from_date + timedelta(days=6)
        elif mode == "month":
            from_date = anchor.replace(day=1)
            if from_date.month == 12:
                next_month = from_date.replace(year=from_date.year + 1, month=1)
            else:
                next_month = from_date.replace(month=from_date.month + 1)
            to_date = next_month - timedelta(days=1)
        elif mode == "custom":
            from_date = anchor
            to_date = _read_date_text(self._view_end_var.get(), "结束日期")
            if from_date > to_date:
                raise ValueError("开始日期不能晚于结束日期。")
        else:
            raise ValueError(f"未知视角：{mode}")

        self._view_start_var.set(from_date.isoformat())
        self._view_end_var.set(to_date.isoformat())
        return from_date, to_date

    def _activity_view_label(self) -> str:
        return {
            "all": "全部视角",
            "day": "日视角",
            "week": "周视角",
            "month": "月视角",
            "custom": "自定义视角",
        }.get(self._view_mode_var.get(), "活动")

    def _activity_view_status_text(self, from_date: date | None, to_date: date | None) -> str:
        if from_date is None or to_date is None:
            return self._activity_view_label()
        return f"{self._activity_view_label()} {from_date.isoformat()} 至 {to_date.isoformat()}"

    def _apply_activity_view(self) -> None:
        self.refresh()

    def _show_today(self) -> None:
        today = date.today().isoformat()
        self._view_mode_var.set("day")
        self._view_start_var.set(today)
        self._view_end_var.set(today)
        self.refresh()

    def _remember_activity_tree(self, tree: ttk.Treeview) -> None:
        self._active_activity_tree = tree

    def _selected_activity_id(self) -> int | None:
        trees: list[ttk.Treeview] = []
        if self._active_activity_tree is not None:
            trees.append(self._active_activity_tree)
        for tree in (self._recent_tree, self._pending_tree):
            if tree not in trees:
                trees.append(tree)

        for tree in trees:
            selection = tree.selection()
            if not selection:
                continue
            try:
                return int(selection[0])
            except ValueError:
                continue
        return None

    def _show_selected_activity_detail(self) -> None:
        activity_id = self._selected_activity_id()
        if activity_id is None:
            messagebox.showinfo("未选择活动", "请先在活动列表中选择一条活动。", parent=self._root)
            return

        activity = self._load_activity(activity_id)
        if activity is None:
            messagebox.showinfo("活动不存在", "该活动可能已经被删除，请刷新后重试。", parent=self._root)
            self.refresh()
            return

        self._open_activity_detail(activity)

    def _load_activity(self, activity_id: int) -> dict | None:
        self._database.initialize()
        with self._database.connect() as connection:
            repository = ActivityRepository(connection)
            return repository.get_detail(activity_id)

    def _load_fit_messages(self, activity_id: int) -> list[dict]:
        self._database.initialize()
        with self._database.connect() as connection:
            return ActivityRepository(connection).list_fit_messages(activity_id)

    def _open_activity_detail(self, activity: dict) -> None:
        window = tk.Toplevel(self._root)
        window.title("活动详情")
        window.geometry("980x760")
        window.minsize(780, 620)
        window.transient(self._root)

        root = ttk.Frame(window, padding=14)
        root.grid(row=0, column=0, sticky="nsew")
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        title = ttk.Label(root, text=activity.get("activity_name") or "未命名活动", font=("", 14, "bold"))
        title.grid(row=0, column=0, sticky="w", pady=(0, 10))

        notebook = ttk.Notebook(root)
        notebook.grid(row=1, column=0, sticky="nsew")

        basic = ttk.Frame(notebook, padding=12)
        basic.columnconfigure(1, weight=1)
        self._add_detail_rows(
            basic,
            [
                ("时间", activity.get("start_time")),
                ("日期", activity.get("start_date")),
                ("活动类型", activity.get("sport_type")),
                ("来源", activity.get("source")),
                ("本地 ID", activity.get("local_id")),
                ("外部 ID", activity.get("external_id")),
                ("创建时间", activity.get("created_at")),
                ("更新时间", activity.get("updated_at")),
            ],
        )
        notebook.add(basic, text="基本信息")

        metrics = ttk.Frame(notebook, padding=12)
        metrics.columnconfigure(1, weight=1)
        self._add_detail_rows(
            metrics,
            [
                ("距离", _km(activity.get("distance_m"))),
                ("用时", _duration(activity.get("duration_s"))),
                ("移动时间", _duration(activity.get("moving_time_s"))),
                ("平均配速", _pace(activity.get("avg_pace_s_per_km"))),
                ("平均心率", _value(activity.get("avg_hr"))),
                ("最高心率", _value(activity.get("max_hr"))),
                ("平均步频", _cadence(activity.get("avg_cadence"))),
                ("平均步幅", _stride(activity.get("avg_stride_m"))),
                ("爬升", _meters(activity.get("elevation_gain_m"))),
                ("卡路里", _value(activity.get("calories"))),
                ("训练效果", _value(activity.get("training_effect"))),
            ],
        )
        notebook.add(metrics, text="运动指标")

        records = activity.get("records") or []
        laps = activity.get("laps") or []
        self._add_track_tab(notebook, records)
        self._add_charts_tab(notebook, records)
        self._add_laps_tab(notebook, laps)
        self._add_fit_messages_tab(notebook, int(activity["id"]))

        note = ttk.Frame(notebook, padding=12)
        note.columnconfigure(1, weight=1)
        if activity.get("has_note"):
            self._add_detail_rows(
                note,
                [
                    ("疲劳程度", _value(activity.get("note_fatigue_level"))),
                    ("酸痛/疼痛", _value(activity.get("note_soreness_level"))),
                    ("睡眠质量", _value(activity.get("note_sleep_quality"))),
                    ("RPE", _value(activity.get("note_rpe"))),
                    ("心情", activity.get("note_mood") or "未知"),
                    ("异常疼痛", activity.get("note_pain_note") or "无"),
                    ("训练备注", activity.get("note_summary") or "无"),
                    ("记录时间", activity.get("note_created_at")),
                    ("更新时间", activity.get("note_updated_at")),
                ],
                wraplength=450,
            )
        else:
            ttk.Label(note, text="这条活动还没有主观记录。").grid(row=0, column=0, sticky="w")
        notebook.add(note, text="主观记录")

        files = ttk.Frame(notebook, padding=12)
        files.columnconfigure(1, weight=1)
        self._add_detail_rows(
            files,
            [
                ("FIT 路径", activity.get("fit_path")),
                ("FIT SHA256", activity.get("fit_sha256")),
            ],
            wraplength=470,
        )
        notebook.add(files, text="文件")

        buttons = ttk.Frame(root)
        buttons.grid(row=2, column=0, sticky="e", pady=(12, 0))
        ttk.Button(
            buttons,
            text="删除活动",
            command=lambda: self._delete_activity_by_id(int(activity["id"]), window),
        ).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="关闭", command=window.destroy).grid(row=0, column=1)

    def _add_track_tab(self, notebook: ttk.Notebook, records: list[dict]) -> None:
        tab = ttk.Frame(notebook, padding=12)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)

        canvas = tk.Canvas(tab, background="white", highlightthickness=1, highlightbackground="#d9d9d9")
        canvas.grid(row=0, column=0, sticky="nsew")

        points = [
            (float(record["latitude"]), float(record["longitude"]))
            for record in records
            if record.get("latitude") is not None and record.get("longitude") is not None
        ]

        def redraw(_event: tk.Event | None = None) -> None:
            self._draw_track(canvas, points)

        canvas.bind("<Configure>", redraw)
        redraw()
        notebook.add(tab, text="轨迹")

    def _add_charts_tab(self, notebook: ttk.Notebook, records: list[dict]) -> None:
        tab = ttk.Frame(notebook, padding=12)
        tab.columnconfigure(0, weight=1)

        chart_specs = [
            ("心率", "heart_rate", _heart_rate, "#d14b4b", False),
            ("配速（快在上）", "pace_s_per_km", _pace, "#3777b8", True),
            ("步频", "cadence_spm", _cadence, "#3b8f5a", False),
            ("步幅", "stride_m", _stride, "#8a5fbf", False),
        ]

        for row, (title, field, formatter, color, invert) in enumerate(chart_specs):
            tab.rowconfigure(row, weight=1)
            frame = ttk.LabelFrame(tab, text=title, padding=8)
            frame.grid(row=row, column=0, sticky="nsew", pady=(0, 8))
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(0, weight=1)
            canvas = tk.Canvas(frame, height=122, background="white", highlightthickness=0)
            canvas.grid(row=0, column=0, sticky="nsew")

            def redraw(
                _event: tk.Event | None = None,
                chart_canvas: tk.Canvas = canvas,
                chart_field: str = field,
                chart_formatter: Callable[[object], str] = formatter,
                chart_color: str = color,
                chart_invert: bool = invert,
            ) -> None:
                self._draw_series_chart(
                    chart_canvas,
                    records,
                    chart_field,
                    chart_formatter,
                    chart_color,
                    invert=chart_invert,
                )

            canvas.bind("<Configure>", redraw)
            redraw()

        notebook.add(tab, text="曲线")

    def _add_laps_tab(self, notebook: ttk.Notebook, laps: list[dict]) -> None:
        tab = ttk.Frame(notebook, padding=12)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)

        columns = ("index", "distance", "time", "pace", "hr", "cadence", "stride", "trigger", "intensity")
        tree = ttk.Treeview(tab, columns=columns, show="headings", height=12)
        self._configure_tree(
            tree,
            {
                "index": ("圈", 50),
                "distance": ("距离", 80),
                "time": ("用时", 80),
                "pace": ("配速", 90),
                "hr": ("心率", 80),
                "cadence": ("步频", 80),
                "stride": ("步幅", 80),
                "trigger": ("触发", 90),
                "intensity": ("强度", 90),
            },
        )
        tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=scrollbar.set)

        for lap in laps:
            tree.insert(
                "",
                "end",
                values=(
                    lap.get("lap_index"),
                    _km(lap.get("distance_m")),
                    _duration(lap.get("moving_time_s") or lap.get("elapsed_s")),
                    _pace(lap.get("avg_pace_s_per_km")),
                    _hr_range(lap.get("avg_hr"), lap.get("max_hr")),
                    _cadence(lap.get("avg_cadence_spm")),
                    _stride(lap.get("avg_stride_m")),
                    _value(lap.get("trigger")),
                    _value(lap.get("intensity")),
                ),
            )

        if not laps:
            ttk.Label(tab, text="没有计圈数据。").grid(row=1, column=0, sticky="w", pady=(8, 0))

        notebook.add(tab, text="计圈")

    def _add_fit_messages_tab(self, notebook: ttk.Notebook, activity_id: int) -> None:
        tab = ttk.Frame(notebook, padding=12)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        summary_var = tk.StringVar(value="FIT 原始数据未加载")
        ttk.Label(tab, textvariable=summary_var).grid(row=0, column=0, sticky="w", pady=(0, 8))

        paned = ttk.PanedWindow(tab, orient="horizontal")
        paned.grid(row=1, column=0, sticky="nsew")

        type_frame = ttk.Frame(paned)
        type_frame.columnconfigure(0, weight=1)
        type_frame.rowconfigure(0, weight=1)
        type_tree = ttk.Treeview(type_frame, columns=("name", "count"), show="headings", height=18)
        self._configure_tree(type_tree, {"name": ("类型", 150), "count": ("数量", 70)})
        type_tree.grid(row=0, column=0, sticky="nsew")
        type_scrollbar = ttk.Scrollbar(type_frame, orient="vertical", command=type_tree.yview)
        type_scrollbar.grid(row=0, column=1, sticky="ns")
        type_tree.configure(yscrollcommand=type_scrollbar.set)
        paned.add(type_frame, weight=1)

        message_frame = ttk.Frame(paned)
        message_frame.columnconfigure(0, weight=1)
        message_frame.rowconfigure(0, weight=1)
        message_tree = ttk.Treeview(message_frame, columns=("index", "local", "name", "fields"), show="headings", height=18)
        self._configure_tree(
            message_tree,
            {
                "index": ("全局序号", 80),
                "local": ("类型序号", 80),
                "name": ("类型", 130),
                "fields": ("字段数", 70),
            },
        )
        message_tree.grid(row=0, column=0, sticky="nsew")
        message_scrollbar = ttk.Scrollbar(message_frame, orient="vertical", command=message_tree.yview)
        message_scrollbar.grid(row=0, column=1, sticky="ns")
        message_tree.configure(yscrollcommand=message_scrollbar.set)
        paned.add(message_frame, weight=2)

        field_frame = ttk.Frame(paned)
        field_frame.columnconfigure(0, weight=1)
        field_frame.rowconfigure(0, weight=1)
        field_tree = ttk.Treeview(field_frame, columns=("name", "value", "units"), show="headings", height=18)
        self._configure_tree(
            field_tree,
            {
                "name": ("字段", 150),
                "value": ("值", 260),
                "units": ("单位", 80),
            },
        )
        field_tree.grid(row=0, column=0, sticky="nsew")
        field_scrollbar = ttk.Scrollbar(field_frame, orient="vertical", command=field_tree.yview)
        field_scrollbar.grid(row=0, column=1, sticky="ns")
        field_tree.configure(yscrollcommand=field_scrollbar.set)
        paned.add(field_frame, weight=3)

        fit_messages: list[dict] = []
        messages_by_type: dict[str, list[dict]] = {}
        message_lookup: dict[str, dict] = {}
        loaded = False

        def clear_tree(tree: ttk.Treeview) -> None:
            for item_id in tree.get_children():
                tree.delete(item_id)

        def fill_messages(message_name: str | None = None) -> None:
            clear_tree(message_tree)
            clear_tree(field_tree)
            selected_messages = fit_messages if message_name in (None, "__all__") else messages_by_type.get(message_name, [])
            for message in selected_messages:
                item_id = str(message.get("message_index"))
                message_lookup[item_id] = message
                fields = message.get("fields") or []
                message_tree.insert(
                    "",
                    "end",
                    iid=item_id,
                    values=(
                        message.get("message_index"),
                        message.get("local_index"),
                        message.get("message_name"),
                        len(fields),
                    ),
                )
            first_message = message_tree.get_children()
            if first_message:
                message_tree.selection_set(first_message[0])
                fill_fields(first_message[0])

        def load_fit_messages() -> None:
            nonlocal fit_messages, messages_by_type, loaded
            if loaded:
                return
            loaded = True
            fit_messages = self._load_fit_messages(activity_id)
            messages_by_type = {}
            for message in fit_messages:
                messages_by_type.setdefault(str(message.get("message_name")), []).append(message)

            clear_tree(type_tree)
            type_tree.insert("", "end", iid="__all__", values=("全部", len(fit_messages)))
            for message_name in sorted(messages_by_type):
                type_tree.insert("", "end", iid=message_name, values=(message_name, len(messages_by_type[message_name])))

            summary_var.set(f"{len(fit_messages)} 条 FIT message，{len(messages_by_type)} 种类型")
            if not fit_messages:
                summary_var.set("没有 FIT 原始 message 数据，请先同步或回填 FIT 明细")

        def fill_fields(item_id: str) -> None:
            clear_tree(field_tree)
            message = message_lookup.get(item_id)
            if not message:
                return
            for index, field in enumerate(message.get("fields") or []):
                field_tree.insert(
                    "",
                    "end",
                    iid=f"{item_id}:{index}",
                    values=(
                        field.get("name"),
                        _raw_value(field.get("value")),
                        field.get("units") or "",
                    ),
                )

        def on_type_select(_event: tk.Event) -> None:
            selection = type_tree.selection()
            fill_messages(selection[0] if selection else "__all__")

        def on_message_select(_event: tk.Event) -> None:
            selection = message_tree.selection()
            if selection:
                fill_fields(selection[0])

        type_tree.bind("<<TreeviewSelect>>", on_type_select)
        message_tree.bind("<<TreeviewSelect>>", on_message_select)

        def on_tab_changed(_event: tk.Event) -> None:
            if notebook.select() == str(tab):
                load_fit_messages()

        notebook.bind("<<NotebookTabChanged>>", on_tab_changed, add="+")

        notebook.add(tab, text="FIT 原始数据")

    def _draw_track(self, canvas: tk.Canvas, points: list[tuple[float, float]]) -> None:
        canvas.delete("all")
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        padding = 28

        if len(points) < 2:
            canvas.create_text(width / 2, height / 2, text="没有 GPS 轨迹数据", fill="#666666")
            return

        points = _sample_sequence(points, 2000)
        mean_lat = sum(lat for lat, _lon in points) / len(points)
        lon_scale = max(math.cos(math.radians(mean_lat)), 0.01)
        projected = [(lon * lon_scale, lat) for lat, lon in points]
        min_x = min(x for x, _y in projected)
        max_x = max(x for x, _y in projected)
        min_y = min(y for _x, y in projected)
        max_y = max(y for _x, y in projected)

        x_span = max(max_x - min_x, 0.000001)
        y_span = max(max_y - min_y, 0.000001)
        plot_width = max(width - padding * 2, 1)
        plot_height = max(height - padding * 2, 1)
        scale = min(plot_width / x_span, plot_height / y_span)
        offset_x = (width - x_span * scale) / 2
        offset_y = (height - y_span * scale) / 2

        screen_points: list[float] = []
        for x, y in projected:
            screen_points.extend(
                (
                    offset_x + (x - min_x) * scale,
                    height - (offset_y + (y - min_y) * scale),
                )
            )

        canvas.create_line(*screen_points, fill="#2f6fb2", width=3)
        start_x, start_y = screen_points[0], screen_points[1]
        end_x, end_y = screen_points[-2], screen_points[-1]
        canvas.create_oval(start_x - 5, start_y - 5, start_x + 5, start_y + 5, fill="#2e9d57", outline="")
        canvas.create_oval(end_x - 5, end_y - 5, end_x + 5, end_y + 5, fill="#c84646", outline="")
        canvas.create_text(12, 12, text="起", fill="#2e9d57", anchor="nw")
        canvas.create_text(12, 30, text="终", fill="#c84646", anchor="nw")

    def _draw_series_chart(
        self,
        canvas: tk.Canvas,
        records: list[dict],
        field: str,
        formatter: Callable[[object], str],
        color: str,
        invert: bool = False,
    ) -> None:
        canvas.delete("all")
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        left = 52
        right = 14
        top = 16
        bottom = 22

        points: list[tuple[float, float]] = []
        for index, record in enumerate(records):
            value = record.get(field)
            if value is None:
                continue
            x_value = record.get("distance_m")
            if x_value is None:
                x_value = record.get("elapsed_s")
            if x_value is None:
                x_value = index
            points.append((float(x_value), float(value)))

        if len(points) < 2:
            canvas.create_text(width / 2, height / 2, text="没有数据", fill="#666666")
            return

        points = _sample_sequence(points, 700)
        min_x = min(x for x, _y in points)
        max_x = max(x for x, _y in points)
        min_y = min(y for _x, y in points)
        max_y = max(y for _x, y in points)
        if math.isclose(min_y, max_y):
            min_y -= 1
            max_y += 1
        x_span = max(max_x - min_x, 1)
        y_span = max(max_y - min_y, 0.000001)
        plot_width = max(width - left - right, 1)
        plot_height = max(height - top - bottom, 1)

        canvas.create_line(left, top, left, height - bottom, fill="#d0d0d0")
        canvas.create_line(left, height - bottom, width - right, height - bottom, fill="#d0d0d0")
        canvas.create_text(6, top, text=formatter(max_y), anchor="nw", fill="#555555")
        canvas.create_text(6, height - bottom - 12, text=formatter(min_y), anchor="nw", fill="#555555")

        screen_points: list[float] = []
        for x, y in points:
            screen_x = left + ((x - min_x) / x_span) * plot_width
            y_ratio = (y - min_y) / y_span if invert else (max_y - y) / y_span
            screen_y = top + y_ratio * plot_height
            screen_points.extend((screen_x, screen_y))

        canvas.create_line(*screen_points, fill=color, width=2)
        canvas.create_text(
            width - right,
            height - 8,
            text=_km(max_x),
            anchor="se",
            fill="#555555",
        )

    def _add_detail_rows(
        self,
        parent: ttk.Frame,
        rows: list[tuple[str, object]],
        wraplength: int = 380,
    ) -> None:
        for index, (label, value) in enumerate(rows):
            ttk.Label(parent, text=label).grid(row=index, column=0, sticky="nw", pady=4, padx=(0, 12))
            ttk.Label(parent, text=_detail_value(value), wraplength=wraplength, justify="left").grid(
                row=index,
                column=1,
                sticky="ew",
                pady=4,
            )

    def _delete_selected_activity(self) -> None:
        activity_id = self._selected_activity_id()
        if activity_id is None:
            messagebox.showinfo("未选择活动", "请先在活动列表中选择一条活动。", parent=self._root)
            return
        self._delete_activity_by_id(activity_id, self._root)

    def _delete_activity_by_id(self, activity_id: int, parent: tk.Misc) -> None:
        if self._busy:
            messagebox.showinfo("任务运行中", "请等待当前任务完成。", parent=parent)
            return

        activity = self._load_activity(activity_id)
        if activity is None:
            messagebox.showinfo("活动不存在", "该活动可能已经被删除，请刷新后重试。", parent=parent)
            self.refresh()
            return

        confirmed = messagebox.askyesno(
            "确认删除活动",
            (
                f"确定删除这条本地活动记录吗？\n\n"
                f"{activity.get('start_time')}  {activity.get('activity_name')}\n\n"
                "关联的主观记录、解析明细和原始 FIT 文件都会删除。"
            ),
            parent=parent,
        )
        if not confirmed:
            return

        fit_path = activity.get("fit_path")
        with self._database.connect() as connection:
            deleted = ActivityRepository(connection).delete(activity_id)
            connection.commit()

        if deleted:
            self._append_log(f"已删除活动：{activity.get('start_time')} {activity.get('activity_name')}")
            fit_message = self._delete_fit_file(fit_path)
            if fit_message:
                self._append_log(fit_message)
        else:
            self._append_log(f"删除活动失败：未找到 ID {activity_id}")

        if isinstance(parent, tk.Toplevel):
            parent.destroy()
        self.refresh()

    def prompt_notes(self) -> None:
        if self._busy:
            messagebox.showinfo("任务运行中", "请等待当前同步任务完成。", parent=self._root)
            return

        self._database.initialize()
        saved_count = 0
        with self._database.connect() as connection:
            activity_repo = ActivityRepository(connection)
            note_repo = ActivityNoteRepository(connection)
            prompt = PromptService(parent=self._root)

            for activity in activity_repo.list_without_notes():
                note = prompt.collect_note(activity)
                if note is None:
                    continue

                note_repo.upsert(activity_id=int(activity["id"]), note=note)
                connection.commit()
                saved_count += 1

        self._append_log(f"补填完成：保存 {saved_count} 条记录")
        self.refresh()

    def _init_db(self) -> None:
        self._run_background(
            "初始化数据库",
            lambda: self._init_db_task(),
        )

    def _sync_today(self) -> None:
        limit = self._read_limit()
        if limit is None and self._limit_var.get().strip():
            return
        self._run_background(
            "同步今天",
            lambda: self._workflow.sync_today(max_activities=limit),
        )

    def _sync_latest(self) -> None:
        limit = self._read_limit(default=2)
        if limit is None:
            return
        self._run_background(
            "同步最近活动",
            lambda: self._workflow.sync_latest(max_activities=limit),
        )

    def _sync_range(self) -> None:
        try:
            from_date = date.fromisoformat(self._from_date_var.get().strip())
            to_date = date.fromisoformat(self._to_date_var.get().strip())
        except ValueError:
            messagebox.showerror("日期错误", "日期需要使用 YYYY-MM-DD 格式。", parent=self._root)
            return
        if from_date > to_date:
            messagebox.showerror("日期错误", "开始日期不能晚于结束日期。", parent=self._root)
            return

        limit = self._read_limit()
        if limit is None and self._limit_var.get().strip():
            return
        self._run_background(
            "同步日期范围",
            lambda: self._workflow.sync_range(from_date, to_date, max_activities=limit),
        )

    def _run_today_with_prompts(self) -> None:
        limit = self._read_limit()
        if limit is None and self._limit_var.get().strip():
            return
        self._run_background(
            "同步今天并补填",
            lambda: self._workflow.sync_today(max_activities=limit),
            on_success=lambda _: self.prompt_notes(),
        )

    def _backfill_fit_details(self) -> None:
        self._run_background(
            "回填 FIT 明细",
            lambda: self._workflow.backfill_fit_details(),
        )

    def _cleanup_orphan_fit_files(self) -> None:
        confirmed = messagebox.askyesno(
            "确认清理孤立 FIT",
            (
                "确定删除数据库中未引用的本地 FIT 文件吗？\n\n"
                f"仅会清理目录：{self._settings.fit_raw_dir}"
            ),
            parent=self._root,
        )
        if not confirmed:
            return
        self._run_background(
            "清理孤立 FIT",
            lambda: self._workflow.cleanup_orphan_fit_files(),
        )

    def _delete_fit_file(self, fit_path: object) -> str | None:
        if not fit_path:
            return None
        path = Path(str(fit_path)).resolve()
        fit_root = self._settings.fit_raw_dir.resolve()
        if not _is_relative_to(path, fit_root):
            return f"跳过删除 FIT：路径不在 FIT 目录内 {path}"
        if not path.exists():
            return f"FIT 文件已不存在：{path}"
        try:
            path.unlink()
        except Exception as exc:
            return f"删除 FIT 文件失败：{path}，{exc}"
        _remove_empty_parent_dirs(path.parent, fit_root)
        return f"已删除 FIT 文件：{path}"

    def _run_background(
        self,
        label: str,
        task: Callable[[], Any],
        on_success: Callable[[Any], None] | None = None,
    ) -> None:
        if self._busy:
            messagebox.showinfo("任务运行中", "请等待当前任务完成。", parent=self._root)
            return

        self._busy = True
        self._set_status(f"{label}中...")
        self._append_log(f"{label}开始")

        def worker() -> None:
            try:
                result = task()
            except Exception as exc:
                self._events.put(("error", label, exc, None))
                self._events.put(("traceback", label, traceback.format_exc(), None))
                return
            self._events.put(("success", label, result, on_success))

        threading.Thread(target=worker, daemon=True).start()

    def _drain_events(self) -> None:
        while True:
            try:
                event_type, label, payload, callback = self._events.get_nowait()
            except queue.Empty:
                break

            if event_type == "success":
                self._busy = False
                self._append_log(f"{label}完成")
                if isinstance(payload, SyncResult):
                    self._append_log(payload.summary_text())
                elif isinstance(payload, FitBackfillResult):
                    self._append_log(payload.summary_text())
                elif isinstance(payload, FitCleanupResult):
                    self._append_log(payload.summary_text())
                elif payload is not None:
                    self._append_log(str(payload))
                self.refresh()
                if callback is not None:
                    callback(payload)
            elif event_type == "error":
                self._busy = False
                self._append_log(f"{label}失败：{payload}")
                self._set_status(f"{label}失败")
                self.refresh()
                messagebox.showerror(f"{label}失败", str(payload), parent=self._root)
            elif event_type == "traceback":
                self._append_log(str(payload))

        self._root.after(100, self._drain_events)

    def _init_db_task(self) -> str:
        self._database.initialize()
        return f"数据库已初始化：{self._settings.db_path}"

    def _read_limit(self, default: int | None = None) -> int | None:
        raw_value = self._limit_var.get().strip()
        if not raw_value:
            return default
        try:
            value = int(raw_value)
        except ValueError:
            messagebox.showerror("参数错误", "活动上限需要填写整数。", parent=self._root)
            return None
        if value <= 0:
            messagebox.showerror("参数错误", "活动上限需要大于 0。", parent=self._root)
            return None
        return value

    def _replace_rows(self, tree: ttk.Treeview, rows: list[tuple[Any, ...]]) -> None:
        for item_id in tree.get_children():
            tree.delete(item_id)
        for row in rows:
            tree.insert("", "end", values=row)

    def _replace_activity_rows(self, tree: ttk.Treeview, rows: list[tuple[Any, ...]]) -> None:
        for item_id in tree.get_children():
            tree.delete(item_id)
        for row in rows:
            activity_id, *values = row
            tree.insert("", "end", iid=str(activity_id), values=values)

    def _append_log(self, message: str) -> None:
        self._log.configure(state="normal")
        self._log.insert("end", f"{message}\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _set_status(self, message: str) -> None:
        self._status_var.set(message)


def main() -> None:
    settings = load_settings()
    database = Database(settings.db_path)
    root = tk.Tk()
    DiaryDesktopApp(root, settings, database)
    root.mainloop()


def _km(value: object) -> str:
    if value is None:
        return "未知"
    return f"{float(value) / 1000:.2f} km"


def _meters(value: object) -> str:
    if value is None:
        return "未知"
    return f"{float(value):.1f} m"


def _duration(value: object) -> str:
    if value is None:
        return "未知"
    seconds = int(float(value))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _pace(value: object) -> str:
    if value is None:
        return "未知"
    seconds = int(float(value))
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}:{seconds:02d} /km"


def _heart_rate(value: object) -> str:
    if value is None:
        return "未知"
    return f"{int(float(value))} bpm"


def _hr_range(avg_value: object, max_value: object) -> str:
    if avg_value is None and max_value is None:
        return "未知"
    if max_value is None:
        return _heart_rate(avg_value)
    if avg_value is None:
        return f"最高 {_heart_rate(max_value)}"
    return f"{int(float(avg_value))}/{int(float(max_value))} bpm"


def _cadence(value: object) -> str:
    if value is None:
        return "未知"
    return f"{float(value):.0f} spm"


def _stride(value: object) -> str:
    if value is None:
        return "未知"
    return f"{float(value):.2f} m"


def _value(value: object) -> str:
    if value is None:
        return "未知"
    return str(value)


def _single_line(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).splitlines())


def _detail_value(value: object) -> str:
    if value is None:
        return "未知"
    text = str(value).strip()
    return text or "无"


def _raw_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _sample_sequence(values: list[_T], max_count: int) -> list[_T]:
    if len(values) <= max_count:
        return values
    step = (len(values) - 1) / (max_count - 1)
    return [values[round(index * step)] for index in range(max_count)]


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _remove_empty_parent_dirs(start: Path, root: Path) -> None:
    current = start
    while _is_relative_to(current, root) and current != root:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _read_date_text(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"{label}需要使用 YYYY-MM-DD 格式。") from exc
