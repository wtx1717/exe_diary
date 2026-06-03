from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from exe_diary.config import Settings
from exe_diary.db.database import Database
from exe_diary.db.repositories import ActivityNoteRepository, ActivityRepository, SyncRunRepository
from exe_diary.fit.parser import FitParser
from exe_diary.garmin.client import GarminClient
from exe_diary.garmin.sync import GarminSyncService, SyncResult
from exe_diary.ui.prompt import PromptService


MAX_BACKFILL_LIMIT = 5000


@dataclass(frozen=True)
class FitBackfillResult:
    parsed_count: int
    error_count: int
    errors: tuple[str, ...] = ()

    def summary_text(self) -> str:
        text = f"FIT detail backfill finished: parsed={self.parsed_count}, errors={self.error_count}"
        if self.errors:
            text += "\n" + "\n".join(f"- {error}" for error in self.errors)
        return text


@dataclass(frozen=True)
class FitCleanupResult:
    deleted_count: int
    skipped_count: int
    errors: tuple[str, ...] = ()

    def summary_text(self) -> str:
        text = f"orphan FIT cleanup finished: deleted={self.deleted_count}, skipped={self.skipped_count}, errors={len(self.errors)}"
        if self.errors:
            text += "\n" + "\n".join(f"- {error}" for error in self.errors)
        return text


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

    def run(self, max_activities: int | None = None) -> tuple[SyncResult, int]:
        sync_result = self.sync_today(max_activities=max_activities)
        saved_count = self.prompt_pending_notes()
        return sync_result, saved_count

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

    def prompt_pending_notes(self) -> int:
        self._database.initialize()
        saved_count = 0

        with self._database.connect() as connection:
            activity_repo = ActivityRepository(connection)
            note_repo = ActivityNoteRepository(connection)
            prompt = PromptService()

            for activity in activity_repo.list_without_notes():
                note = prompt.collect_note(activity)
                if note is None:
                    continue

                note_repo.upsert(activity_id=int(activity["id"]), note=note)
                connection.commit()
                saved_count += 1

        return saved_count

    def backfill_fit_details(self, limit: int | None = None) -> FitBackfillResult:
        if limit is not None and (limit <= 0 or limit > MAX_BACKFILL_LIMIT):
            raise ValueError(f"limit must be between 1 and {MAX_BACKFILL_LIMIT}.")

        self._database.initialize()
        parsed_count = 0
        errors: list[str] = []

        with self._database.connect() as connection:
            activity_repo = ActivityRepository(connection)
            parser = FitParser()

            for activity in activity_repo.list_missing_fit_details(limit=limit):
                fit_path = Path(str(activity.get("fit_path") or ""))
                local_id = str(activity.get("local_id") or activity.get("id"))
                if not fit_path.exists():
                    errors.append(f"{local_id}: FIT file not found: {fit_path}")
                    continue

                try:
                    parsed = parser.parse(fit_path)
                    activity_repo.update_fit_details(int(activity["id"]), parsed)
                    connection.commit()
                except Exception as exc:
                    connection.rollback()
                    errors.append(f"{local_id}: {exc}")
                    continue
                parsed_count += 1

        return FitBackfillResult(
            parsed_count=parsed_count,
            error_count=len(errors),
            errors=tuple(errors),
        )

    def cleanup_orphan_fit_files(self) -> FitCleanupResult:
        self._database.initialize()
        fit_root = self._settings.fit_raw_dir.resolve()
        if not fit_root.exists():
            return FitCleanupResult(deleted_count=0, skipped_count=0)

        deleted_count = 0
        skipped_count = 0
        errors: list[str] = []

        with self._database.connect() as connection:
            referenced_paths = {Path(path).resolve() for path in ActivityRepository(connection).list_fit_paths()}

        for fit_path in fit_root.rglob("*.fit"):
            resolved_path = fit_path.resolve()
            if not resolved_path.is_file():
                skipped_count += 1
                continue
            if resolved_path in referenced_paths:
                skipped_count += 1
                continue
            if not _is_relative_to(resolved_path, fit_root):
                skipped_count += 1
                continue
            try:
                resolved_path.unlink()
                deleted_count += 1
            except Exception as exc:
                errors.append(f"{resolved_path}: {exc}")

        _remove_empty_dirs(fit_root)
        return FitCleanupResult(
            deleted_count=deleted_count,
            skipped_count=skipped_count,
            errors=tuple(errors),
        )


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _remove_empty_dirs(root: Path) -> None:
    if not root.exists():
        return
    for directory in sorted((path for path in root.rglob("*") if path.is_dir()), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            continue
