from __future__ import annotations

import sqlite3
from datetime import datetime

from exe_diary.fit.models import ActivitySummary


class ActivityRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def upsert(self, activity: ActivitySummary) -> bool:
        before = self._connection.total_changes
        self._connection.execute(
            """
            INSERT INTO activities (
              local_id, source, external_id, activity_name, sport_type,
              start_time, start_date, fit_path, fit_sha256,
              distance_m, duration_s, moving_time_s, avg_pace_s_per_km,
              avg_hr, max_hr, avg_cadence, elevation_gain_m, calories,
              training_effect
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(external_id) DO UPDATE SET
              local_id = excluded.local_id,
              activity_name = excluded.activity_name,
              sport_type = excluded.sport_type,
              start_time = excluded.start_time,
              start_date = excluded.start_date,
              fit_path = excluded.fit_path,
              fit_sha256 = excluded.fit_sha256,
              distance_m = excluded.distance_m,
              duration_s = excluded.duration_s,
              moving_time_s = excluded.moving_time_s,
              avg_pace_s_per_km = excluded.avg_pace_s_per_km,
              avg_hr = excluded.avg_hr,
              max_hr = excluded.max_hr,
              avg_cadence = excluded.avg_cadence,
              elevation_gain_m = excluded.elevation_gain_m,
              calories = excluded.calories,
              training_effect = excluded.training_effect,
              updated_at = CURRENT_TIMESTAMP
            """,
            (
                activity.local_id,
                activity.source,
                activity.external_id,
                activity.activity_name,
                activity.sport_type,
                activity.start_time.isoformat(sep=" "),
                activity.start_date,
                str(activity.fit_path),
                activity.fit_sha256,
                activity.distance_m,
                activity.duration_s,
                activity.moving_time_s,
                activity.avg_pace_s_per_km,
                activity.avg_hr,
                activity.max_hr,
                activity.avg_cadence,
                activity.elevation_gain_m,
                activity.calories,
                activity.training_effect,
            ),
        )
        return self._connection.total_changes > before

    def list_without_notes(self) -> list[dict]:
        rows = self._connection.execute(
            """
            SELECT a.*
            FROM activities a
            LEFT JOIN activity_notes n ON n.activity_id = a.id
            WHERE n.id IS NULL
            ORDER BY a.start_time DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def list_recent(self, limit: int = 50) -> list[dict]:
        rows = self._connection.execute(
            """
            SELECT
              a.*,
              CASE WHEN n.id IS NULL THEN 0 ELSE 1 END AS has_note
            FROM activities a
            LEFT JOIN activity_notes n ON n.activity_id = a.id
            ORDER BY a.start_time DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


class ActivityNoteRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def upsert(self, activity_id: int, note: dict) -> None:
        self._connection.execute(
            """
            INSERT INTO activity_notes (
              activity_id, fatigue_level, soreness_level, sleep_quality,
              mood, rpe, pain_note, summary
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(activity_id) DO UPDATE SET
              fatigue_level = excluded.fatigue_level,
              soreness_level = excluded.soreness_level,
              sleep_quality = excluded.sleep_quality,
              mood = excluded.mood,
              rpe = excluded.rpe,
              pain_note = excluded.pain_note,
              summary = excluded.summary,
              updated_at = CURRENT_TIMESTAMP
            """,
            (
                activity_id,
                note.get("fatigue_level"),
                note.get("soreness_level"),
                note.get("sleep_quality"),
                note.get("mood"),
                note.get("rpe"),
                note.get("pain_note"),
                note.get("summary"),
            ),
        )


class SyncRunRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def start(self) -> int:
        cursor = self._connection.execute(
            "INSERT INTO sync_runs (status) VALUES (?)",
            ("running",),
        )
        return int(cursor.lastrowid)

    def finish(
        self,
        run_id: int,
        status: str,
        message: str,
        new_fit_count: int,
        parsed_count: int,
        error_count: int,
    ) -> None:
        self._connection.execute(
            """
            UPDATE sync_runs
            SET finished_at = ?, status = ?, message = ?,
                new_fit_count = ?, parsed_count = ?, error_count = ?
            WHERE id = ?
            """,
            (
                datetime.now().isoformat(sep=" ", timespec="seconds"),
                status,
                message,
                new_fit_count,
                parsed_count,
                error_count,
                run_id,
            ),
        )

    def list_recent(self, limit: int = 20) -> list[dict]:
        rows = self._connection.execute(
            """
            SELECT *
            FROM sync_runs
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
