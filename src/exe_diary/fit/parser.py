from __future__ import annotations

from pathlib import Path

from exe_diary.fit.models import ParsedFitMetrics


class FitParser:
    def parse(self, fit_path: Path) -> ParsedFitMetrics:
        try:
            from fitparse import FitFile
        except ImportError:
            return ParsedFitMetrics()

        fit_file = FitFile(str(fit_path))
        metrics = ParsedFitMetrics()

        for record in fit_file.get_messages("session"):
            values = {field.name: field.value for field in record}
            metrics = ParsedFitMetrics(
                distance_m=_float(values.get("total_distance")),
                duration_s=_float(values.get("total_elapsed_time")),
                moving_time_s=_float(values.get("total_timer_time")),
                avg_hr=_int(values.get("avg_heart_rate")),
                max_hr=_int(values.get("max_heart_rate")),
                avg_cadence=_float(values.get("avg_cadence")),
                elevation_gain_m=_float(values.get("total_ascent")),
                calories=_int(values.get("total_calories")),
                training_effect=_float(values.get("total_training_effect")),
            )
            break

        return metrics


def _float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)

