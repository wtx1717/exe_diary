from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from exe_diary.db.repositories import ActivityRepository
from exe_diary.fit.models import ActivitySummary
from exe_diary.fit.parser import FitParser
from exe_diary.garmin.client import GarminClient


MAX_SYNC_ACTIVITIES = 500


@dataclass(frozen=True)
class SyncResult:
    downloaded_count: int
    imported_count: int
    skipped_count: int
    error_count: int
    errors: tuple[str, ...] = ()

    def summary_text(self) -> str:
        text = (
            "sync finished: "
            f"downloaded={self.downloaded_count}, "
            f"imported={self.imported_count}, "
            f"skipped={self.skipped_count}, "
            f"errors={self.error_count}"
        )
        if self.errors:
            text += "\n" + "\n".join(f"- {error}" for error in self.errors)
        return text


class GarminSyncService:
    def __init__(
        self,
        client: GarminClient,
        parser: FitParser,
        activities: ActivityRepository,
        fit_raw_dir: Path,
    ) -> None:
        self._client = client
        self._parser = parser
        self._activities = activities
        self._fit_raw_dir = fit_raw_dir

    def sync_range(
        self,
        from_date: date | None,
        to_date: date | None,
        max_activities: int | None = None,
    ) -> SyncResult:
        if from_date is not None and to_date is not None and from_date > to_date:
            raise ValueError("from_date must not be later than to_date.")
        if max_activities is not None and (max_activities <= 0 or max_activities > MAX_SYNC_ACTIVITIES):
            raise ValueError(f"max_activities must be between 1 and {MAX_SYNC_ACTIVITIES}.")

        downloaded_count = 0
        imported_count = 0
        skipped_count = 0
        error_count = 0
        processed_running_count = 0
        errors: list[str] = []

        for raw_activity in self._client.iter_activities():
            start_time = _parse_garmin_start_time(raw_activity)
            if start_time is None:
                skipped_count += 1
                continue

            activity_date = start_time.date()
            if to_date is not None and activity_date > to_date:
                continue
            if from_date is not None and activity_date < from_date:
                break
            if not _is_running_activity(raw_activity):
                skipped_count += 1
                continue

            if max_activities is not None and processed_running_count >= max_activities:
                break
            processed_running_count += 1

            activity_id = str(raw_activity["activityId"])
            local_id = f"{activity_date:%Y%m%d}_{activity_id}"
            fit_path = self._fit_path(activity_date, local_id)

            try:
                if fit_path.exists():
                    fit_data = fit_path.read_bytes()
                else:
                    fit_data = self._client.download_fit(activity_id)
                    fit_path.parent.mkdir(parents=True, exist_ok=True)
                    tmp_path = fit_path.with_suffix(f"{fit_path.suffix}.tmp")
                    try:
                        tmp_path.write_bytes(fit_data)
                        tmp_path.replace(fit_path)
                    except Exception:
                        tmp_path.unlink(missing_ok=True)
                        raise
                    downloaded_count += 1

                fit_sha256 = hashlib.sha256(fit_data).hexdigest()
                parsed = self._parser.parse(fit_path)
                summary = ActivitySummary.from_garmin_activity(
                    raw_activity=raw_activity,
                    local_id=local_id,
                    fit_path=fit_path,
                    fit_sha256=fit_sha256,
                    parsed_metrics=parsed,
                )
                if self._activities.upsert(summary):
                    imported_count += 1
                else:
                    skipped_count += 1
            except Exception as exc:
                error_count += 1
                errors.append(f"{local_id}: {exc}")

        return SyncResult(
            downloaded_count=downloaded_count,
            imported_count=imported_count,
            skipped_count=skipped_count,
            error_count=error_count,
            errors=tuple(errors),
        )

    def _fit_path(self, activity_date: date, local_id: str) -> Path:
        return self._fit_raw_dir / f"{activity_date:%Y}" / f"{activity_date:%m}" / f"{local_id}.fit"


def _is_running_activity(activity: dict[str, Any]) -> bool:
    type_key = activity.get("activityType", {}).get("typeKey", "")
    return "running" in type_key


def _parse_garmin_start_time(activity: dict[str, Any]) -> datetime | None:
    value = activity.get("startTimeLocal")
    if not value:
        return None

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None
