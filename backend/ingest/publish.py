"""Write the lecture JSON files to S3.

Layout under `lectures/<acadYear>/sem-<n>/`:
  days/<YYYY-MM-DD>.json   sessions on one date
  weeks/<label>.json       sessions in one week (week-01 ... week-13, recess, reading, exam-N)
  modules.json             descriptions for recommendations
  index.json               dates, weeks and counts; written after the files it lists
and `lectures/current.json` points at the semester being served.

A file is only rewritten when its content (ignoring generatedAt) changed, so a run
on unchanged data writes nothing.
"""

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timedelta

from botocore.exceptions import ClientError

from ingest.academic_calendar import Semester, week_label
from ingest.lesson_types import LESSON_TYPE_CODES
from ingest.transform import group_by_date

ROOT = "lectures"
HASH_KEY = "content-sha256"
CACHE_CONTROL = "public, max-age=86400"  # 1 day; data changes a few times a month

# Refuse to publish if the session count drops below this share of the last run.
MIN_RATIO_OF_PREVIOUS = 0.5


class SuspiciousDataError(Exception):
    """NUSMods data looks wrong; yesterday's files are left in place."""


def publish(
    s3,
    bucket: str,
    semester: Semester,
    sessions: list[dict],
    modules: list[dict],
    now: datetime,
) -> dict:
    prefix = f"{ROOT}/{semester.key}"
    generated_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    base = {"acadYear": semester.acad_year, "semester": semester.number}

    _check_counts(s3, bucket, f"{prefix}/index.json", len(sessions))

    documents: dict[str, dict] = {}

    by_date = group_by_date(sessions)
    for on, day_sessions in by_date.items():
        documents[f"{prefix}/days/{on.isoformat()}.json"] = {
            **base,
            "date": on.isoformat(),
            "week": week_label(semester, on),
            "sessions": day_sessions,
        }

    weeks = _group_by_week(semester, by_date)
    for label, (monday, week_sessions) in weeks.items():
        documents[f"{prefix}/weeks/{label}.json"] = {
            **base,
            "week": label,
            "startDate": monday.isoformat(),
            "endDate": (monday + timedelta(days=6)).isoformat(),
            "sessions": week_sessions,
        }

    documents[f"{prefix}/modules.json"] = {**base, "items": modules}

    written = unchanged = 0
    for key, document in documents.items():
        if _put_if_changed(s3, bucket, key, document, generated_at):
            written += 1
        else:
            unchanged += 1

    index = {
        **base,  # acadYear + semester
        "sessionCount": len(sessions),
        "days": [on.isoformat() for on in by_date],
        "weeks": [
            {
                "week": label,
                "startDate": monday.isoformat(),
                "endDate": (monday + timedelta(days=6)).isoformat(),
                "sessionCount": len(week_sessions),
            }
            for label, (monday, week_sessions) in weeks.items()
        ],
        "lessonTypes": LESSON_TYPE_CODES,
    }
    index_written = _put_if_changed(
        s3, bucket, f"{prefix}/index.json", index, generated_at
    )

    deleted = _delete_stale(s3, bucket, prefix, set(documents))

    _put_if_changed(
        s3,
        bucket,
        f"{ROOT}/current.json",
        {**base, "path": f"{prefix}/"},
        generated_at,
    )

    return {
        "semester": semester.key,
        "sessions": len(sessions),
        "files": len(documents),
        "written": written + index_written,
        "unchanged": unchanged + (not index_written),
        "deleted": deleted,
    }


def _group_by_week(
    semester: Semester, by_date: dict[date, list[dict]]
) -> dict[str, tuple[date, list[dict]]]:
    weeks: dict[str, tuple[date, list[dict]]] = {}
    sessions_by_label: dict[str, list[dict]] = defaultdict(list)
    for on, day_sessions in by_date.items():
        label = week_label(semester, on)
        monday = on - timedelta(days=on.weekday())
        weeks.setdefault(label, (monday, sessions_by_label[label]))
        sessions_by_label[label].extend(day_sessions)
    return weeks


def _check_counts(s3, bucket: str, index_key: str, count: int) -> None:
    if count == 0:
        raise SuspiciousDataError("NUSMods returned no lecture sessions")
    previous = _get_json(s3, bucket, index_key)
    if previous and count < previous["sessionCount"] * MIN_RATIO_OF_PREVIOUS:
        raise SuspiciousDataError(
            f"Only {count} sessions, down from {previous['sessionCount']} last run"
        )


def _content_hash(document: dict) -> str:
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _put_if_changed(
    s3, bucket: str, key: str, document: dict, generated_at: str
) -> bool:
    digest = _content_hash(document)
    try:
        head = s3.head_object(Bucket=bucket, Key=key)
        if head["Metadata"].get(HASH_KEY) == digest:
            return False
    except ClientError as error:
        if error.response["Error"]["Code"] not in ("404", "NoSuchKey"):
            raise
    body = json.dumps(
        {"generatedAt": generated_at, **document}, ensure_ascii=False
    ).encode()
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="application/json",
        CacheControl=CACHE_CONTROL,
        Metadata={HASH_KEY: digest},
    )
    return True


def _get_json(s3, bucket: str, key: str) -> dict | None:
    try:
        return json.load(s3.get_object(Bucket=bucket, Key=key)["Body"])
    except ClientError as error:
        if error.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return None
        raise


def _delete_stale(s3, bucket: str, prefix: str, keep: set[str]) -> int:
    stale = []
    for folder in ("days", "weeks"):
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=f"{prefix}/{folder}/"):
            stale += [
                o["Key"] for o in page.get("Contents", []) if o["Key"] not in keep
            ]
    for start in range(0, len(stale), 1000):
        s3.delete_objects(
            Bucket=bucket,
            Delete={"Objects": [{"Key": k} for k in stale[start : start + 1000]]},
        )
    return len(stale)
