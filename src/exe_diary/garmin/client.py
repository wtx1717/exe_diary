from __future__ import annotations

import io
import zipfile
from collections.abc import Iterable
from typing import Any

from exe_diary.config import Settings


class GarminClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._logged_in = False

    def login(self) -> None:
        import garth

        if self._settings.garmin_is_cn_account:
            garth.configure(domain="garmin.cn")

        if self._settings.garth_session_dir.exists():
            garth.resume(str(self._settings.garth_session_dir))
        else:
            if not self._settings.garmin_email or not self._settings.garmin_password:
                raise RuntimeError("Garmin credentials are missing. Set GARMIN_EMAIL and GARMIN_PASSWORD.")
            garth.login(self._settings.garmin_email, self._settings.garmin_password)
            self._settings.garth_session_dir.parent.mkdir(parents=True, exist_ok=True)
            garth.save(str(self._settings.garth_session_dir))

        self._logged_in = True

    def list_activities(self, start: int = 0, limit: int = 50) -> list[dict[str, Any]]:
        import garth

        self._ensure_login()
        return garth.client.connectapi(
            "/activitylist-service/activities/search/activities",
            params={"start": start, "limit": limit},
        )

    def iter_activities(self, page_size: int = 50) -> Iterable[dict[str, Any]]:
        start = 0
        while True:
            activities = self.list_activities(start=start, limit=page_size)
            if not activities:
                break

            yield from activities

            if len(activities) < page_size:
                break
            start += page_size

    def download_fit(self, activity_id: str | int) -> bytes:
        import garth

        self._ensure_login()
        data = garth.client.download(f"/download-service/files/activity/{activity_id}")
        return self._extract_fit(data)

    def _ensure_login(self) -> None:
        if not self._logged_in:
            self.login()

    @staticmethod
    def _extract_fit(data: bytes) -> bytes:
        if data.startswith(b"PK\x03\x04"):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                fit_names = [name for name in archive.namelist() if name.lower().endswith(".fit")]
                if not fit_names:
                    raise RuntimeError("Downloaded zip archive does not contain a FIT file.")
                data = archive.read(fit_names[0])

        if b".FIT" not in data[8:15]:
            raise RuntimeError("Downloaded payload is not a valid FIT file.")

        return data

