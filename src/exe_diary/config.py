from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def _bool_from_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    garmin_email: str | None
    garmin_password: str | None
    garmin_is_cn_account: bool
    auto_run_enabled: bool
    auto_run_time: str
    data_dir: Path
    db_path: Path
    log_dir: Path
    fit_raw_dir: Path
    garth_session_dir: Path


def _app_dir() -> Path:
    package_dir = Path(__file__).resolve().parent
    if package_dir.parent.name == "src":
        return package_dir.parent.parent
    return package_dir.parent


def _path_from_env(name: str, default: Path, base_dir: Path) -> Path:
    raw_value = os.getenv(name)
    path = Path(raw_value) if raw_value else default
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def normalize_daily_time(value: str) -> str:
    text = value.strip()
    parts = text.split(":")
    if len(parts) != 2:
        raise ValueError("每日自动运行时间需要使用 HH:MM 格式。")

    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as exc:
        raise ValueError("每日自动运行时间需要使用 HH:MM 格式。") from exc

    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("每日自动运行时间需要在 00:00-23:59 之间。")
    return f"{hour:02d}:{minute:02d}"


def _daily_time_from_env(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return normalize_daily_time(value)
    except ValueError:
        return default


def save_auto_run_settings(enabled: bool, run_time: str) -> Path:
    normalized_time = normalize_daily_time(run_time)
    values = {
        "EXE_DIARY_AUTO_RUN_ENABLED": "true" if enabled else "false",
        "EXE_DIARY_AUTO_RUN_TIME": normalized_time,
    }
    env_path = _app_dir() / ".env"
    _write_dotenv_values(env_path, values)
    os.environ.update(values)
    return env_path


def _write_dotenv_values(path: Path, values: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    output: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            output.append(line)
            continue

        key = line.split("=", 1)[0].strip()
        if key in values:
            output.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            output.append(line)

    if output and output[-1].strip():
        output.append("")
    for key, value in values.items():
        if key not in seen:
            output.append(f"{key}={value}")

    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def load_settings() -> Settings:
    app_dir = _app_dir()
    cwd_env = Path(".env").resolve()
    app_env = app_dir / ".env"
    if cwd_env != app_env:
        _load_dotenv(cwd_env)
    _load_dotenv(app_env)

    data_dir = _path_from_env("EXE_DIARY_DATA_DIR", app_dir / "data", app_dir)
    db_path = _path_from_env("EXE_DIARY_DB_PATH", data_dir / "exe_diary.sqlite", app_dir)
    log_dir = _path_from_env("EXE_DIARY_LOG_DIR", app_dir / "logs", app_dir)
    fit_raw_dir = data_dir / "fit" / "raw"
    garth_session_dir = data_dir / ".garth_session"

    return Settings(
        garmin_email=os.getenv("GARMIN_EMAIL"),
        garmin_password=os.getenv("GARMIN_PASSWORD"),
        garmin_is_cn_account=_bool_from_env("GARMIN_IS_CN_ACCOUNT", True),
        auto_run_enabled=_bool_from_env("EXE_DIARY_AUTO_RUN_ENABLED", False),
        auto_run_time=_daily_time_from_env("EXE_DIARY_AUTO_RUN_TIME", "20:30"),
        data_dir=data_dir,
        db_path=db_path,
        log_dir=log_dir,
        fit_raw_dir=fit_raw_dir,
        garth_session_dir=garth_session_dir,
    )
