"""Scheduled Lambda: NUSMods -> lecture JSON in the web bucket.

Invoke with {"date": "YYYY-MM-DD"} to ingest the semester containing that date
instead of today's.
"""

import json
import logging
import os
from datetime import UTC, date, datetime, timedelta, timezone

import boto3

from ingest.academic_calendar import semester_for
from ingest.nusmods import fetch_semester
from ingest.publish import publish
from ingest.transform import build_modules, build_sessions

SINGAPORE = timezone(timedelta(hours=8))

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context, *, s3=None, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    if event and event.get("date"):
        today = date.fromisoformat(event["date"])
    else:
        today = now.astimezone(SINGAPORE).date()
    semester = semester_for(today)

    module_info, venue_info = fetch_semester(semester.acad_year, semester.number)
    sessions = build_sessions(module_info, venue_info, semester)
    modules = build_modules(module_info, sessions)

    result = publish(
        s3 or boto3.client("s3"),
        os.environ["WEB_BUCKET"],
        semester,
        sessions,
        modules,
        now,
    )
    logger.info(json.dumps(result))
    return result
