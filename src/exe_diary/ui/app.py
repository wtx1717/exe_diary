from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText
import traceback
from typing import Any

from exe_diary.app.workflow import AppWorkflow
from exe_diary.config import Settings, load_settings
from exe_diary.db.database import Database
from exe_diary.db.repositories import ActivityNoteRepository, ActivityRepository, SyncRunRepository
from exe_diary.garmin.sync import SyncResult
from exe_diary.ui.prompt import PromptService


Event = tuple[str, str, Any, Callable[[Any], None] | None]


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
        self._view_mode_var = tk.StringVar(value="day")
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
        ttk.Button(actions, text="删除选中活动", command=self._delete_selected_activity).grid(
            row=7,
            column=0,
            sticky="ew",
            pady=3,
        )
        ttk.Button(actions, text="刷新", command=self.refresh).grid(row=8, column=0, sticky="ew", pady=(10, 3))

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
        controls.columnconfigure(8, weight=1)

        ttk.Label(controls, text="视角").grid(row=0, column=0, sticky="w", padx=(0, 4))
        view_options = (("日", "day"), ("周", "week"), ("月", "month"), ("自定义", "custom"))
        for index, (label, value) in enumerate(view_options, start=1):
            ttk.Radiobutton(
                controls,
                text=label,
                value=value,
                variable=self._view_mode_var,
                command=self._apply_activity_view,
            ).grid(row=0, column=index, sticky="w", padx=2)

        ttk.Label(controls, text="开始").grid(row=0, column=5, sticky="e", padx=(14, 4))
        ttk.Entry(controls, textvariable=self._view_start_var, width=12).grid(row=0, column=6, sticky="w")
        ttk.Label(controls, text="结束").grid(row=0, column=7, sticky="e", padx=(10, 4))
        ttk.Entry(controls, textvariable=self._view_end_var, width=12).grid(row=0, column=8, sticky="w")

        ttk.Button(controls, text="应用", command=self._apply_activity_view).grid(row=0, column=9, padx=(10, 0))
        ttk.Button(controls, text="今天", command=self._show_today).grid(row=0, column=10, padx=(6, 0))
        ttk.Button(controls, text="详情", command=self._show_selected_activity_detail).grid(row=0, column=11, padx=(14, 0))
        ttk.Button(controls, text="删除", command=self._delete_selected_activity).grid(row=0, column=12, padx=(6, 0))

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
            tree.column(key, width=width, minwidth=60, anchor="w", stretch=key in {"name", "message"})

    def refresh(self) -> None:
        try:
            from_date, to_date = self._activity_view_dates()
            self._database.initialize()
            with self._database.connect() as connection:
                activities = ActivityRepository(connection).list_between(from_date.isoformat(), to_date.isoformat())
                pending = ActivityRepository(connection).list_without_notes()
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
            f"就绪：{self._activity_view_label()} {from_date.isoformat()} 至 {to_date.isoformat()} "
            f"{len(activities)} 条，待补填 {len(pending)}"
        )

    def _activity_view_dates(self) -> tuple[date, date]:
        mode = self._view_mode_var.get()
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
            "day": "日视角",
            "week": "周视角",
            "month": "月视角",
            "custom": "自定义视角",
        }.get(self._view_mode_var.get(), "活动")

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
            return ActivityRepository(connection).get_with_note(activity_id)

    def _open_activity_detail(self, activity: dict) -> None:
        window = tk.Toplevel(self._root)
        window.title("活动详情")
        window.geometry("660x620")
        window.minsize(560, 480)
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
                ("平均步频", _value(activity.get("avg_cadence"))),
                ("爬升", _meters(activity.get("elevation_gain_m"))),
                ("卡路里", _value(activity.get("calories"))),
                ("训练效果", _value(activity.get("training_effect"))),
            ],
        )
        notebook.add(metrics, text="运动指标")

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
                "关联的主观记录也会删除；原始 FIT 文件会保留。"
            ),
            parent=parent,
        )
        if not confirmed:
            return

        with self._database.connect() as connection:
            deleted = ActivityRepository(connection).delete(activity_id)
            connection.commit()

        if deleted:
            self._append_log(f"已删除活动：{activity.get('start_time')} {activity.get('activity_name')}")
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


def _read_date_text(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"{label}需要使用 YYYY-MM-DD 格式。") from exc
