from __future__ import annotations

from datetime import date

from exe_diary.config import Settings
from exe_diary.db.database import Database
from exe_diary.db.repositories import ActivityRepository, SyncRunRepository
from exe_diary.fit.parser import FitParser
from exe_diary.garmin.client import GarminClient
from exe_diary.garmin.sync import GarminSyncService, SyncResult


class AppWorkflow:
    def __init__(self, settings: Settings, database: Database) -> None:
        self._settings = settings
        self._database = database

    def sync_today(self, max_activities: int | None = None) -> SyncResult:
        today = date.today()
        return self.sync_range(today, today, max_activities=max_activities)

    def sync_range(self, from_date: date, to_date: date, max_activities: int | None = None) -> SyncResult:
        return self._run_sync(from_date=from_date, to_date=to_date, max_activities=max_activities)

    def sync_latest(self, max_activities: int = 2) -> SyncResult:
        return self._run_sync(from_date=None, to_date=None, max_activities=max_activities)

    def _run_sync(
        self,
        from_date: date | None,
        to_date: date | None,
        max_activities: int | None,
    ) -> SyncResult:
        self._database.initialize()
        with self._database.connect() as connection:
            activity_repo = ActivityRepository(connection)
            sync_repo = SyncRunRepository(connection)
            run_id = sync_repo.start()
            service = GarminSyncService(
                client=GarminClient(self._settings),
                parser=FitParser(),
                activities=activity_repo,
                fit_raw_dir=self._settings.fit_raw_dir,
            )

            try:
                result = service.sync_range(from_date, to_date, max_activities=max_activities)
            except Exception as exc:
                sync_repo.finish(
                    run_id,
                    status="failed",
                    message=str(exc),
                    new_fit_count=0,
                    parsed_count=0,
                    error_count=1,
                )
                raise

            sync_repo.finish(
                run_id,
                status="success",
                message=result.summary_text(),
                new_fit_count=result.downloaded_count,
                parsed_count=result.imported_count,
                error_count=result.error_count,
            )
            return result

    def list_pending_notes(self) -> list[dict]:
        self._database.initialize()
        with self._database.connect() as connection:
            return ActivityRepository(connection).list_without_notes()
