from __future__ import annotations

import argparse
from datetime import date

from exe_diary.app.workflow import AppWorkflow
from exe_diary.config import load_settings
from exe_diary.db.database import Database


def _date_arg(value: str) -> date:
    return date.fromisoformat(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="exe-diary")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="initialize the local SQLite database")

    run = subparsers.add_parser("run", help="sync today's activities and prompt for subjective notes")
    run.add_argument("--limit", type=int, default=None, help="maximum number of running activities to process")

    sync_today = subparsers.add_parser("sync-today", help="sync today's Garmin running activities")
    sync_today.add_argument("--limit", type=int, default=None, help="maximum number of running activities to process")

    sync_range = subparsers.add_parser("sync-range", help="manually sync a date range")
    sync_range.add_argument("--from-date", required=True, type=_date_arg)
    sync_range.add_argument("--to-date", required=True, type=_date_arg)
    sync_range.add_argument("--limit", type=int, default=None, help="maximum number of running activities to process")

    sync_latest = subparsers.add_parser("sync-latest", help="sync the latest Garmin running activities for local testing")
    sync_latest.add_argument("--limit", type=int, default=2, help="maximum number of running activities to process")

    subparsers.add_parser("pending-notes", help="list activities that still need subjective notes")
    subparsers.add_parser("prompt-notes", help="open note prompts for activities that still need subjective notes")
    backfill = subparsers.add_parser("backfill-fit-details", help="parse saved FIT files and persist detail data")
    backfill.add_argument("--limit", type=int, default=None, help="maximum number of activities to backfill")
    subparsers.add_parser("cleanup-orphan-fit", help="delete FIT files that are not referenced by the database")
    subparsers.add_parser("gui", help="open the desktop visual interface")
    subparsers.add_parser(
        "scheduled-run",
        help="open the desktop interface and run the daily sync-note workflow immediately",
    )
    install_schedule = subparsers.add_parser(
        "install-daily-schedule",
        help="create or update the Windows daily startup task",
    )
    install_schedule.add_argument("--time", default=None, help="daily startup time in HH:MM format")
    subparsers.add_parser("remove-daily-schedule", help="delete the Windows daily startup task")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.command in {"gui", "scheduled-run"}:
        from exe_diary.ui.app import main as gui_main

        gui_main(start_scheduled_flow=args.command == "scheduled-run")
        return

    settings = load_settings()

    if args.command == "install-daily-schedule":
        from exe_diary.app.scheduler import install_daily_start_task
        from exe_diary.config import save_auto_run_settings

        run_time = args.time or settings.auto_run_time
        save_auto_run_settings(True, run_time)
        result = install_daily_start_task(run_time)
        print(result.message)
        if not result.success:
            raise SystemExit(1)
        return

    if args.command == "remove-daily-schedule":
        from exe_diary.app.scheduler import remove_daily_start_task
        from exe_diary.config import save_auto_run_settings

        save_auto_run_settings(False, settings.auto_run_time)
        result = remove_daily_start_task()
        print(result.message)
        if not result.success:
            raise SystemExit(1)
        return

    database = Database(settings.db_path)

    if args.command == "init-db":
        database.initialize()
        print(f"database initialized: {settings.db_path}")
        return

    workflow = AppWorkflow(settings, database)

    if args.command == "run":
        sync_result, saved_count = workflow.run(max_activities=args.limit)
        print(sync_result.summary_text())
        print(f"notes saved: {saved_count}")
        return

    if args.command == "sync-today":
        result = workflow.sync_today(max_activities=args.limit)
        print(result.summary_text())
        return

    if args.command == "sync-range":
        result = workflow.sync_range(args.from_date, args.to_date, max_activities=args.limit)
        print(result.summary_text())
        return

    if args.command == "sync-latest":
        result = workflow.sync_latest(max_activities=args.limit)
        print(result.summary_text())
        return

    if args.command == "pending-notes":
        for activity in workflow.list_pending_notes():
            print(f"{activity['local_id']} {activity['start_time']} {activity['activity_name']}")
        return

    if args.command == "prompt-notes":
        saved_count = workflow.prompt_pending_notes()
        print(f"notes saved: {saved_count}")
        return

    if args.command == "backfill-fit-details":
        result = workflow.backfill_fit_details(limit=args.limit)
        print(result.summary_text())
        return

    if args.command == "cleanup-orphan-fit":
        result = workflow.cleanup_orphan_fit_files()
        print(result.summary_text())
        return


if __name__ == "__main__":
    main()
