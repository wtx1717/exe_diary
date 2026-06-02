from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ParsedFitMetrics:
    distance_m: float | None = None
    duration_s: float | None = None
    moving_time_s: float | None = None
    avg_hr: int | None = None
    max_hr: int | None = None
    avg_cadence: float | None = None
    elevation_gain_m: float | None = None
    calories: int | None = None
    training_effect: float | None = None


@dataclass(frozen=True)
class ActivitySummary:
    local_id: str
    source: str
    external_id: str
    activity_name: str
    sport_type: str
    start_time: datetime
    start_date: str
    fit_path: Path
    fit_sha256: str
    distance_m: float | None
    duration_s: float | None
    moving_time_s: float | None
    avg_pace_s_per_km: float | None
    avg_hr: int | None
    max_hr: int | None
    avg_cadence: float | None
    elevation_gain_m: float | None
    calories: int | None
    training_effect: float | None

    @classmethod
    def from_garmin_activity(
        cls,
        raw_activity: dict[str, Any],
        local_id: str,
        fit_path: Path,
        fit_sha256: str,
        parsed_metrics: ParsedFitMetrics,
    ) -> ActivitySummary:
        start_time = _parse_start_time(raw_activity["startTimeLocal"])
        sport_type = raw_activity.get("activityType", {}).get("typeKey", "unknown")
        distance_m = parsed_metrics.distance_m or _number(raw_activity.get("distance"))
        duration_s = parsed_metrics.duration_s or _number(raw_activity.get("duration"))

        avg_pace = None
        if distance_m and duration_s and distance_m > 0:
            avg_pace = duration_s / (distance_m / 1000)

        return cls(
            local_id=local_id,
            source="garmin",
            external_id=str(raw_activity["activityId"]),
            activity_name=raw_activity.get("activityName") or "Untitled activity",
            sport_type=sport_type,
            start_time=start_time,
            start_date=start_time.date().isoformat(),
            fit_path=fit_path,
            fit_sha256=fit_sha256,
            distance_m=distance_m,
            duration_s=duration_s,
            moving_time_s=parsed_metrics.moving_time_s or _number(raw_activity.get("movingDuration")),
            avg_pace_s_per_km=avg_pace,
            avg_hr=parsed_metrics.avg_hr or _integer(raw_activity.get("averageHR")),
            max_hr=parsed_metrics.max_hr or _integer(raw_activity.get("maxHR")),
            avg_cadence=parsed_metrics.avg_cadence or _number(raw_activity.get("averageRunningCadenceInStepsPerMinute")),
            elevation_gain_m=parsed_metrics.elevation_gain_m or _number(raw_activity.get("elevationGain")),
            calories=parsed_metrics.calories or _integer(raw_activity.get("calories")),
            training_effect=parsed_metrics.training_effect or _number(raw_activity.get("aerobicTrainingEffect")),
        )


def _parse_start_time(value: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unsupported Garmin start time: {value}")


def _number(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _integer(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)

