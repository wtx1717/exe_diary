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
    data_dir: Path
    db_path: Path
    log_dir: Path
    fit_raw_dir: Path
    garth_session_dir: Path


def load_settings() -> Settings:
    _load_dotenv(Path(".env"))

    data_dir = Path(os.getenv("EXE_DIARY_DATA_DIR", "data")).resolve()
    db_path = Path(os.getenv("EXE_DIARY_DB_PATH", data_dir / "exe_diary.sqlite")).resolve()
    log_dir = Path(os.getenv("EXE_DIARY_LOG_DIR", "logs")).resolve()
    fit_raw_dir = data_dir / "fit" / "raw"
    garth_session_dir = data_dir / ".garth_session"

    return Settings(
        garmin_email=os.getenv("GARMIN_EMAIL"),
        garmin_password=os.getenv("GARMIN_PASSWORD"),
        garmin_is_cn_account=_bool_from_env("GARMIN_IS_CN_ACCOUNT", True),
        data_dir=data_dir,
        db_path=db_path,
        log_dir=log_dir,
        fit_raw_dir=fit_raw_dir,
        garth_session_dir=garth_session_dir,
    )
