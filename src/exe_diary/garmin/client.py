from __future__ import annotations

import io
import zipfile
from collections.abc import Iterable
from typing import Any

from exe_diary.config import Settings


MAX_FIT_DOWNLOAD_BYTES = 100 * 1024 * 1024


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
        if len(data) > MAX_FIT_DOWNLOAD_BYTES:
            raise RuntimeError("Downloaded payload is too large to be a normal FIT file.")

        if data.startswith(b"PK\x03\x04"):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                fit_infos = [
                    info
                    for info in archive.infolist()
                    if not info.is_dir() and info.filename.lower().endswith(".fit")
                ]
                if not fit_infos:
                    raise RuntimeError("Downloaded zip archive does not contain a FIT file.")
                fit_info = sorted(fit_infos, key=lambda item: item.filename)[0]
                if fit_info.file_size > MAX_FIT_DOWNLOAD_BYTES:
                    raise RuntimeError("Downloaded FIT file is too large.")
                data = archive.read(fit_info)

        if len(data) < 14 or b".FIT" not in data[8:15]:
            raise RuntimeError("Downloaded payload is not a valid FIT file.")

        return data
