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
    sync_today = subparsers.add_parser("sync-today", help="sync today's Garmin running activities")
    sync_today.add_argument("--limit", type=int, default=None, help="maximum number of running activities to process")

    sync_range = subparsers.add_parser("sync-range", help="manually sync a date range")
    sync_range.add_argument("--from-date", required=True, type=_date_arg)
    sync_range.add_argument("--to-date", required=True, type=_date_arg)
    sync_range.add_argument("--limit", type=int, default=None, help="maximum number of running activities to process")

    sync_latest = subparsers.add_parser("sync-latest", help="sync the latest Garmin running activities for local testing")
    sync_latest.add_argument("--limit", type=int, default=2, help="maximum number of running activities to process")

    subparsers.add_parser("pending-notes", help="list activities that still need subjective notes")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = load_settings()
    database = Database(settings.db_path)

    if args.command == "init-db":
        database.initialize()
        print(f"database initialized: {settings.db_path}")
        return

    workflow = AppWorkflow(settings, database)

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


if __name__ == "__main__":
    main()
