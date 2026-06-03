from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from exe_diary.fit.models import ActivitySummary, FitLap, FitRawMessage, FitRecordPoint, ParsedFitMetrics


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
              avg_hr, max_hr, avg_cadence, avg_stride_m, elevation_gain_m, calories,
              training_effect
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
              avg_stride_m = excluded.avg_stride_m,
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
                activity.avg_stride_m,
                activity.elevation_gain_m,
                activity.calories,
                activity.training_effect,
            ),
        )
        changed = self._connection.total_changes > before

        activity_id = self._activity_id_by_external_id(activity.external_id)
        self._replace_records(activity_id, activity)
        self._replace_laps(activity_id, activity)
        self._replace_fit_messages(activity_id, activity.raw_messages)
        return changed

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

    def list_between(self, from_date: str, to_date: str) -> list[dict]:
        rows = self._connection.execute(
            """
            SELECT
              a.*,
              CASE WHEN n.id IS NULL THEN 0 ELSE 1 END AS has_note
            FROM activities a
            LEFT JOIN activity_notes n ON n.activity_id = a.id
            WHERE a.start_date BETWEEN ? AND ?
            ORDER BY a.start_time DESC
            """,
            (from_date, to_date),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_with_note(self, activity_id: int) -> dict | None:
        row = self._connection.execute(
            """
            SELECT
              a.*,
              CASE WHEN n.id IS NULL THEN 0 ELSE 1 END AS has_note,
              n.fatigue_level AS note_fatigue_level,
              n.soreness_level AS note_soreness_level,
              n.sleep_quality AS note_sleep_quality,
              n.mood AS note_mood,
              n.rpe AS note_rpe,
              n.pain_note AS note_pain_note,
              n.summary AS note_summary,
              n.created_at AS note_created_at,
              n.updated_at AS note_updated_at
            FROM activities a
            LEFT JOIN activity_notes n ON n.activity_id = a.id
            WHERE a.id = ?
            """,
            (activity_id,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def get_detail(self, activity_id: int, include_fit_messages: bool = False) -> dict | None:
        activity = self.get_with_note(activity_id)
        if activity is None:
            return None
        activity["records"] = self.list_records(activity_id)
        activity["laps"] = self.list_laps(activity_id)
        activity["fit_messages"] = self.list_fit_messages(activity_id) if include_fit_messages else []
        return activity

    def list_records(self, activity_id: int) -> list[dict]:
        rows = self._connection.execute(
            """
            SELECT *
            FROM activity_records
            WHERE activity_id = ?
            ORDER BY point_index
            """,
            (activity_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_fit_messages(self, activity_id: int) -> list[dict]:
        rows = self._connection.execute(
            """
            SELECT *
            FROM activity_fit_messages
            WHERE activity_id = ?
            ORDER BY message_index
            """,
            (activity_id,),
        ).fetchall()
        messages: list[dict] = []
        for row in rows:
            message = dict(row)
            message["fields"] = json.loads(message.pop("fields_json"))
            messages.append(message)
        return messages

    def list_laps(self, activity_id: int) -> list[dict]:
        rows = self._connection.execute(
            """
            SELECT *
            FROM activity_laps
            WHERE activity_id = ?
            ORDER BY lap_index
            """,
            (activity_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def update_fit_details(self, activity_id: int, parsed: ParsedFitMetrics) -> None:
        self._connection.execute(
            """
            UPDATE activities
            SET
              avg_cadence = COALESCE(?, avg_cadence),
              avg_stride_m = COALESCE(?, avg_stride_m),
              updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (parsed.avg_cadence, parsed.avg_stride_m, activity_id),
        )
        self._replace_record_points(activity_id, parsed.records)
        self._replace_lap_rows(activity_id, parsed.laps)
        self._replace_fit_messages(activity_id, parsed.raw_messages)

    def list_missing_fit_details(self, limit: int | None = None) -> list[dict]:
        sql = """
            SELECT a.id, a.local_id, a.fit_path
            FROM activities a
            WHERE
              NOT EXISTS (
                SELECT 1 FROM activity_fit_messages m WHERE m.activity_id = a.id
              )
              OR (
                NOT EXISTS (
                  SELECT 1 FROM activity_records r WHERE r.activity_id = a.id
                )
                AND NOT EXISTS (
                  SELECT 1 FROM activity_laps l WHERE l.activity_id = a.id
                )
              )
            ORDER BY a.start_time DESC
        """
        params: tuple[int, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        rows = self._connection.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def list_fit_paths(self) -> list[str]:
        rows = self._connection.execute("SELECT fit_path FROM activities").fetchall()
        return [str(row["fit_path"]) for row in rows if row["fit_path"]]

    def delete(self, activity_id: int) -> bool:
        before = self._connection.total_changes
        self._connection.execute("DELETE FROM activities WHERE id = ?", (activity_id,))
        return self._connection.total_changes > before

    def _activity_id_by_external_id(self, external_id: str) -> int:
        row = self._connection.execute(
            "SELECT id FROM activities WHERE external_id = ?",
            (external_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"Activity was not saved: {external_id}")
        return int(row["id"])

    def _replace_records(self, activity_id: int, activity: ActivitySummary) -> None:
        self._replace_record_points(activity_id, activity.records)

    def _replace_record_points(self, activity_id: int, records: tuple[FitRecordPoint, ...]) -> None:
        self._connection.execute("DELETE FROM activity_records WHERE activity_id = ?", (activity_id,))
        self._connection.executemany(
            """
            INSERT INTO activity_records (
              activity_id, point_index, timestamp, elapsed_s, distance_m,
              latitude, longitude, altitude_m, speed_mps, pace_s_per_km,
              heart_rate, cadence_spm, stride_m, power_w, temperature_c
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    activity_id,
                    index,
                    point.timestamp.isoformat(sep=" ") if point.timestamp else None,
                    point.elapsed_s,
                    point.distance_m,
                    point.latitude,
                    point.longitude,
                    point.altitude_m,
                    point.speed_mps,
                    point.pace_s_per_km,
                    point.heart_rate,
                    point.cadence_spm,
                    point.stride_m,
                    point.power_w,
                    point.temperature_c,
                )
                for index, point in enumerate(records)
            ],
        )

    def _replace_laps(self, activity_id: int, activity: ActivitySummary) -> None:
        self._replace_lap_rows(activity_id, activity.laps)

    def _replace_lap_rows(self, activity_id: int, laps: tuple[FitLap, ...]) -> None:
        self._connection.execute("DELETE FROM activity_laps WHERE activity_id = ?", (activity_id,))
        self._connection.executemany(
            """
            INSERT INTO activity_laps (
              activity_id, lap_index, start_time, elapsed_s, moving_time_s,
              distance_m, avg_pace_s_per_km, avg_hr, max_hr,
              avg_cadence_spm, max_cadence_spm, avg_stride_m,
              ascent_m, descent_m, calories, trigger, intensity
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    activity_id,
                    lap.index,
                    lap.start_time.isoformat(sep=" ") if lap.start_time else None,
                    lap.elapsed_s,
                    lap.moving_time_s,
                    lap.distance_m,
                    lap.avg_pace_s_per_km,
                    lap.avg_hr,
                    lap.max_hr,
                    lap.avg_cadence_spm,
                    lap.max_cadence_spm,
                    lap.avg_stride_m,
                    lap.ascent_m,
                    lap.descent_m,
                    lap.calories,
                    lap.trigger,
                    lap.intensity,
                )
                for lap in laps
            ],
        )

    def _replace_fit_messages(self, activity_id: int, messages: tuple[FitRawMessage, ...]) -> None:
        self._connection.execute("DELETE FROM activity_fit_messages WHERE activity_id = ?", (activity_id,))
        self._connection.executemany(
            """
            INSERT INTO activity_fit_messages (
              activity_id, message_index, message_name, local_index, fields_json
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    activity_id,
                    message.message_index,
                    message.message_name,
                    message.local_index,
                    json.dumps(
                        [
                            {
                                "name": field.name,
                                "value": field.value,
                                "units": field.units,
                            }
                            for field in message.fields
                        ],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )
                for message in messages
            ],
        )


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
