from __future__ import annotations

from tkinter import messagebox, ttk
import tkinter as tk


class PromptService:
    """Tkinter-based prompt for collecting subjective activity notes."""

    def collect_note(self, activity: dict) -> dict | None:
        result: dict | None = None

        root = tk.Tk()
        root.title("exe_diary 训练记录")
        root.resizable(False, False)
        root.attributes("-topmost", True)

        frame = ttk.Frame(root, padding=16)
        frame.grid(row=0, column=0, sticky="nsew")

        title = ttk.Label(frame, text="补充训练记录", font=("", 13, "bold"))
        title.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        summary = _activity_summary(activity)
        ttk.Label(frame, text=summary, justify="left", wraplength=420).grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(0, 14),
        )

        fatigue_var = tk.IntVar(value=5)
        soreness_var = tk.IntVar(value=0)
        sleep_var = tk.IntVar(value=3)
        rpe_var = tk.IntVar(value=5)
        mood_var = tk.StringVar(value="一般")

        row = 2
        _spinbox(frame, row, "疲劳程度 1-10", fatigue_var, 1, 10)
        row += 1
        _spinbox(frame, row, "酸痛/疼痛 0-10", soreness_var, 0, 10)
        row += 1
        _spinbox(frame, row, "睡眠质量 1-5", sleep_var, 1, 5)
        row += 1
        _spinbox(frame, row, "主观强度 RPE 1-10", rpe_var, 1, 10)
        row += 1

        ttk.Label(frame, text="心情").grid(row=row, column=0, sticky="w", pady=4)
        mood = ttk.Combobox(
            frame,
            textvariable=mood_var,
            values=("一般", "好", "疲惫", "兴奋", "低落"),
            width=16,
            state="readonly",
        )
        mood.grid(row=row, column=1, sticky="ew", pady=4)
        row += 1

        ttk.Label(frame, text="异常疼痛").grid(row=row, column=0, sticky="nw", pady=4)
        pain_text = tk.Text(frame, width=42, height=3)
        pain_text.grid(row=row, column=1, sticky="ew", pady=4)
        row += 1

        ttk.Label(frame, text="训练备注").grid(row=row, column=0, sticky="nw", pady=4)
        summary_text = tk.Text(frame, width=42, height=4)
        summary_text.grid(row=row, column=1, sticky="ew", pady=4)
        row += 1

        buttons = ttk.Frame(frame)
        buttons.grid(row=row, column=0, columnspan=2, sticky="e", pady=(12, 0))

        def save() -> None:
            nonlocal result
            try:
                result = {
                    "fatigue_level": _read_int(fatigue_var, 1, 10, "疲劳程度"),
                    "soreness_level": _read_int(soreness_var, 0, 10, "酸痛/疼痛"),
                    "sleep_quality": _read_int(sleep_var, 1, 5, "睡眠质量"),
                    "rpe": _read_int(rpe_var, 1, 10, "RPE"),
                    "mood": mood_var.get(),
                    "pain_note": pain_text.get("1.0", "end").strip(),
                    "summary": summary_text.get("1.0", "end").strip(),
                }
            except (ValueError, tk.TclError) as exc:
                messagebox.showerror("输入错误", str(exc), parent=root)
                return
            root.destroy()

        def later() -> None:
            root.destroy()

        ttk.Button(buttons, text="稍后", command=later).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="保存", command=save).grid(row=0, column=1)

        root.protocol("WM_DELETE_WINDOW", later)
        root.mainloop()
        return result


def _spinbox(frame: ttk.Frame, row: int, label: str, variable: tk.IntVar, from_: int, to: int) -> None:
    ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=4)
    spinbox = tk.Spinbox(frame, from_=from_, to=to, textvariable=variable, width=18)
    spinbox.grid(row=row, column=1, sticky="ew", pady=4)


def _read_int(variable: tk.IntVar, min_value: int, max_value: int, label: str) -> int:
    try:
        value = int(variable.get())
    except (ValueError, tk.TclError) as exc:
        raise ValueError(f"{label} 需要填写整数。") from exc

    if value < min_value or value > max_value:
        raise ValueError(f"{label} 需要在 {min_value}-{max_value} 之间。")
    return value


def _activity_summary(activity: dict) -> str:
    lines = [
        f"运动：{activity.get('activity_name') or '未命名活动'}",
        f"时间：{activity.get('start_time')}",
        f"距离：{_km(activity.get('distance_m'))}",
        f"用时：{_duration(activity.get('duration_s'))}",
        f"平均配速：{_pace(activity.get('avg_pace_s_per_km'))}",
        f"平均心率：{_value(activity.get('avg_hr'), 'bpm')}",
    ]
    return "\n".join(lines)


def _km(value: object) -> str:
    if value is None:
        return "未知"
    return f"{float(value) / 1000:.2f} km"


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


def _value(value: object, unit: str) -> str:
    if value is None:
        return "未知"
    return f"{value} {unit}"
