"""Scheduled Lambda: NUSMods -> lecture JSON in the web bucket.

The schedule runs on every Monday; runs that aren't due (see `ingest_due`) are
skipped. Invoke with {"date": "YYYY-MM-DD"} to ingest the semester containing
that date right away.
"""

import json
import logging
import os
from datetime import UTC, date, datetime, timedelta, timezone

import boto3

from ingest.academic_calendar import ingest_due, semester_for
from ingest.nusmods import fetch_semester
from ingest.publish import publish
from ingest.transform import build_modules, build_sessions

SINGAPORE = timezone(timedelta(hours=8))

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context, *, s3=None, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    manual = bool(
        event and event.get("date")
    )  # if event has a "date" key, it's a manual invocation
    if manual:
        today = date.fromisoformat(event["date"])
    else:
        today = now.astimezone(SINGAPORE).date()
    semester = semester_for(today) # pick semester 1 or 2

    if not manual and not ingest_due(semester, today):
        result = {"semester": semester.key, "skipped": f"not due on {today}"}
        logger.info(json.dumps(result))
        return result

    # download two files
    module_info, venue_info = fetch_semester(semester.acad_year, semester.number)
    sessions = build_sessions(module_info, venue_info, semester)
    modules = build_modules(module_info, sessions)

    # publish to S3
    result = publish(
        s3 or boto3.client("s3"),
        os.environ["WEB_BUCKET"], # defined in infra/template.yaml
        semester,
        sessions,
        modules,
        now,
    )
    logger.info(json.dumps(result))
    return result
