from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import math
from pathlib import Path

from exe_diary.fit.models import FitLap, FitRawField, FitRawMessage, FitRecordPoint, ParsedFitMetrics


class FitParser:
    def parse(self, fit_path: Path) -> ParsedFitMetrics:
        sdk_metrics = _try_parse_with_garmin_sdk(fit_path)
        if sdk_metrics is not None:
            return sdk_metrics

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
                avg_cadence=_cadence_spm(
                    values.get("avg_running_cadence") or values.get("avg_cadence"),
                    values.get("avg_fractional_cadence"),
                ),
                avg_stride_m=_stride_m(values.get("avg_step_length")),
                elevation_gain_m=_float(values.get("total_ascent")),
                calories=_int(values.get("total_calories")),
                training_effect=_float(values.get("total_training_effect")),
            )
            break

        records = tuple(_parse_records(fit_file))
        laps = tuple(_parse_laps(fit_file))
        raw_messages = tuple(_parse_raw_messages(fit_file))

        return ParsedFitMetrics(
            distance_m=metrics.distance_m,
            duration_s=metrics.duration_s,
            moving_time_s=metrics.moving_time_s,
            avg_hr=metrics.avg_hr,
            max_hr=metrics.max_hr,
            avg_cadence=metrics.avg_cadence,
            avg_stride_m=metrics.avg_stride_m,
            elevation_gain_m=metrics.elevation_gain_m,
            calories=metrics.calories,
            training_effect=metrics.training_effect,
            records=records,
            laps=laps,
            raw_messages=raw_messages,
        )


def _try_parse_with_garmin_sdk(fit_path: Path) -> ParsedFitMetrics | None:
    try:
        from garmin_fit_sdk import Decoder, Stream
    except ImportError:
        return None

    try:
        stream = Stream.from_file(str(fit_path))
        decoder = Decoder(stream)
        try:
            messages, _errors = decoder.read(
                apply_scale_and_offset=True,
                expand_sub_fields=True,
                expand_components=True,
            )
        except TypeError:
            messages, _errors = decoder.read()
    except Exception:
        return None

    session_values = _first_sdk_message(messages, "session") or {}
    distance_m = _float(session_values.get("total_distance"))
    duration_s = _float(session_values.get("total_elapsed_time"))
    moving_time_s = _float(_first_present(session_values.get("total_timer_time"), session_values.get("total_moving_time")))

    records = tuple(_parse_sdk_records(messages))
    laps = tuple(_parse_sdk_laps(messages))
    raw_messages = tuple(_parse_sdk_raw_messages(messages))

    return ParsedFitMetrics(
        distance_m=distance_m,
        duration_s=duration_s,
        moving_time_s=moving_time_s,
        avg_hr=_int(session_values.get("avg_heart_rate")),
        max_hr=_int(session_values.get("max_heart_rate")),
        avg_cadence=_cadence_spm(
            session_values.get("avg_running_cadence") or session_values.get("avg_cadence"),
            session_values.get("avg_fractional_cadence"),
        ),
        avg_stride_m=_stride_m(session_values.get("avg_step_length")),
        elevation_gain_m=_float(session_values.get("total_ascent")),
        calories=_int(session_values.get("total_calories")),
        training_effect=_float(session_values.get("total_training_effect")),
        records=records,
        laps=laps,
        raw_messages=raw_messages,
    )


def _parse_sdk_records(messages: dict[str, object]) -> list[FitRecordPoint]:
    points: list[FitRecordPoint] = []
    first_timestamp: datetime | None = None

    for values in _sdk_messages(messages, "record"):
        timestamp = values.get("timestamp")
        if not isinstance(timestamp, datetime):
            timestamp = None
        if first_timestamp is None and timestamp is not None:
            first_timestamp = timestamp

        speed_mps = _float(_first_present(values.get("enhanced_speed"), values.get("speed")))
        point = FitRecordPoint(
            timestamp=timestamp,
            elapsed_s=_elapsed_seconds(first_timestamp, timestamp),
            distance_m=_float(values.get("distance")),
            latitude=_position_degrees(values.get("position_lat")),
            longitude=_position_degrees(values.get("position_long")),
            altitude_m=_float(_first_present(values.get("enhanced_altitude"), values.get("altitude"))),
            speed_mps=speed_mps,
            pace_s_per_km=_pace_from_speed(speed_mps),
            heart_rate=_int(values.get("heart_rate")),
            cadence_spm=_cadence_spm(values.get("cadence"), values.get("fractional_cadence")),
            stride_m=_stride_m(values.get("step_length")),
            power_w=_int(values.get("power")),
            temperature_c=_int(values.get("temperature")),
        )
        if _has_record_value(point):
            points.append(point)

    return points


def _parse_sdk_laps(messages: dict[str, object]) -> list[FitLap]:
    laps: list[FitLap] = []

    for index, values in enumerate(_sdk_messages(messages, "lap"), start=1):
        distance_m = _float(values.get("total_distance"))
        moving_time_s = _float(_first_present(values.get("total_timer_time"), values.get("total_moving_time")))
        start_time = values.get("start_time")
        if not isinstance(start_time, datetime):
            start_time = None

        laps.append(
            FitLap(
                index=index,
                start_time=start_time,
                elapsed_s=_float(values.get("total_elapsed_time")),
                moving_time_s=moving_time_s,
                distance_m=distance_m,
                avg_pace_s_per_km=_pace_from_distance_time(distance_m, moving_time_s),
                avg_hr=_int(values.get("avg_heart_rate")),
                max_hr=_int(values.get("max_heart_rate")),
                avg_cadence_spm=_cadence_spm(
                    values.get("avg_running_cadence") or values.get("avg_cadence"),
                    values.get("avg_fractional_cadence"),
                ),
                max_cadence_spm=_cadence_spm(
                    values.get("max_running_cadence") or values.get("max_cadence"),
                    values.get("max_fractional_cadence"),
                ),
                avg_stride_m=_stride_m(values.get("avg_step_length")),
                ascent_m=_float(values.get("total_ascent")),
                descent_m=_float(values.get("total_descent")),
                calories=_int(values.get("total_calories")),
                trigger=_text(values.get("lap_trigger")),
                intensity=_text(values.get("intensity")),
            )
        )

    return laps


def _parse_sdk_raw_messages(messages: dict[str, object]) -> list[FitRawMessage]:
    raw_messages: list[FitRawMessage] = []
    message_index = 0

    for raw_name, raw_items in messages.items():
        message_name = _sdk_message_name(raw_name)
        if not isinstance(raw_items, list):
            raw_items = [raw_items]

        for local_index, raw_item in enumerate(raw_items):
            if not isinstance(raw_item, dict):
                fields = (FitRawField(name="value", value=_json_value(raw_item), units=None),)
            else:
                fields = tuple(
                    FitRawField(name=_sdk_field_name(field_name), value=_json_value(value), units=None)
                    for field_name, value in raw_item.items()
                )
            raw_messages.append(
                FitRawMessage(
                    message_index=message_index,
                    message_name=message_name,
                    local_index=local_index,
                    fields=fields,
                )
            )
            message_index += 1

    return raw_messages


def _sdk_messages(messages: dict[str, object], message_name: str) -> list[dict]:
    value = messages.get(f"{message_name}_mesgs")
    if value is None:
        value = messages.get(message_name)
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _first_sdk_message(messages: dict[str, object], message_name: str) -> dict | None:
    items = _sdk_messages(messages, message_name)
    return items[0] if items else None


def _sdk_message_name(raw_name: object) -> str:
    name = str(raw_name)
    if name.endswith("_mesgs"):
        name = name[:-6]
    if name.isdigit():
        return f"unknown_{name}"
    return name


def _sdk_field_name(raw_name: object) -> str:
    name = str(raw_name)
    if name.isdigit():
        return f"unknown_{name}"
    return name


def _parse_records(fit_file: object) -> list[FitRecordPoint]:
    points: list[FitRecordPoint] = []
    first_timestamp: datetime | None = None

    for record in fit_file.get_messages("record"):
        values = {field.name: field.value for field in record}
        timestamp = values.get("timestamp")
        if not isinstance(timestamp, datetime):
            timestamp = None
        if first_timestamp is None and timestamp is not None:
            first_timestamp = timestamp

        speed_mps = _float(_first_present(values.get("enhanced_speed"), values.get("speed")))
        point = FitRecordPoint(
            timestamp=timestamp,
            elapsed_s=_elapsed_seconds(first_timestamp, timestamp),
            distance_m=_float(values.get("distance")),
            latitude=_position_degrees(values.get("position_lat")),
            longitude=_position_degrees(values.get("position_long")),
            altitude_m=_float(_first_present(values.get("enhanced_altitude"), values.get("altitude"))),
            speed_mps=speed_mps,
            pace_s_per_km=_pace_from_speed(speed_mps),
            heart_rate=_int(values.get("heart_rate")),
            cadence_spm=_cadence_spm(values.get("cadence"), values.get("fractional_cadence")),
            stride_m=_stride_m(values.get("step_length")),
            power_w=_int(values.get("power")),
            temperature_c=_int(values.get("temperature")),
        )

        if _has_record_value(point):
            points.append(point)

    return points


def _parse_laps(fit_file: object) -> list[FitLap]:
    laps: list[FitLap] = []

    for index, lap in enumerate(fit_file.get_messages("lap"), start=1):
        values = {field.name: field.value for field in lap}
        distance_m = _float(values.get("total_distance"))
        moving_time_s = _float(_first_present(values.get("total_timer_time"), values.get("total_moving_time")))
        start_time = values.get("start_time")
        if not isinstance(start_time, datetime):
            start_time = None

        laps.append(
            FitLap(
                index=index,
                start_time=start_time,
                elapsed_s=_float(values.get("total_elapsed_time")),
                moving_time_s=moving_time_s,
                distance_m=distance_m,
                avg_pace_s_per_km=_pace_from_distance_time(distance_m, moving_time_s),
                avg_hr=_int(values.get("avg_heart_rate")),
                max_hr=_int(values.get("max_heart_rate")),
                avg_cadence_spm=_cadence_spm(
                    values.get("avg_running_cadence") or values.get("avg_cadence"),
                    values.get("avg_fractional_cadence"),
                ),
                max_cadence_spm=_cadence_spm(
                    values.get("max_running_cadence") or values.get("max_cadence"),
                    values.get("max_fractional_cadence"),
                ),
                avg_stride_m=_stride_m(values.get("avg_step_length")),
                ascent_m=_float(values.get("total_ascent")),
                descent_m=_float(values.get("total_descent")),
                calories=_int(values.get("total_calories")),
                trigger=_text(values.get("lap_trigger")),
                intensity=_text(values.get("intensity")),
            )
        )

    return laps


def _parse_raw_messages(fit_file: object) -> list[FitRawMessage]:
    messages: list[FitRawMessage] = []
    local_indexes: defaultdict[str, int] = defaultdict(int)

    for message_index, message in enumerate(fit_file.get_messages()):
        message_name = str(message.name)
        local_index = local_indexes[message_name]
        local_indexes[message_name] += 1
        fields = tuple(
            FitRawField(
                name=str(field.name),
                value=_json_value(field.value),
                units=_text(getattr(field, "units", None)),
            )
            for field in message
        )
        messages.append(
            FitRawMessage(
                message_index=message_index,
                message_name=message_name,
                local_index=local_index,
                fields=fields,
            )
        )

    return messages


def _float(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _text(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _elapsed_seconds(first: datetime | None, current: datetime | None) -> float | None:
    if first is None or current is None:
        return None
    return (current - first).total_seconds()


def _semicircles_to_degrees(value: object) -> float | None:
    raw = _float(value)
    if raw is None:
        return None
    return raw * (180 / 2**31)


def _position_degrees(value: object) -> float | None:
    raw = _float(value)
    if raw is None:
        return None
    if -180 <= raw <= 180:
        return raw
    return _semicircles_to_degrees(raw)


def _pace_from_speed(speed_mps: float | None) -> float | None:
    if speed_mps is None or speed_mps <= 0:
        return None
    return 1000 / speed_mps


def _pace_from_distance_time(distance_m: float | None, duration_s: float | None) -> float | None:
    if distance_m is None or duration_s is None or distance_m <= 0:
        return None
    return duration_s / (distance_m / 1000)


def _cadence_spm(value: object, fractional: object = None) -> float | None:
    cadence = _float(value)
    if cadence is None:
        return None

    cadence += _float(fractional) or 0
    if cadence <= 0:
        return None

    if cadence < 130:
        return cadence * 2
    return cadence


def _stride_m(value: object) -> float | None:
    stride = _float(value)
    if stride is None or stride <= 0:
        return None
    if stride > 20:
        return stride / 1000
    return stride


def _has_record_value(point: FitRecordPoint) -> bool:
    return any(
        value is not None
        for value in (
            point.timestamp,
            point.distance_m,
            point.latitude,
            point.longitude,
            point.altitude_m,
            point.speed_mps,
            point.heart_rate,
            point.cadence_spm,
            point.stride_m,
            point.power_w,
        )
    )


def _first_present(*values: object) -> object | None:
    for value in values:
        if value is not None:
            return value
    return None


def _json_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
