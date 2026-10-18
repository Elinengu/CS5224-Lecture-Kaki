import json
from datetime import UTC, datetime

import boto3
import pytest
from moto import mock_aws

from handlers import ingest as ingest_handler
from ingest.publish import SuspiciousDataError, publish
from ingest.transform import build_modules, build_sessions

BUCKET = "lecturekaki-test-web"
PREFIX = "lectures/2026-2027/sem-1"
NOW = datetime(2026, 10, 18, 19, 0, tzinfo=UTC)


@pytest.fixture
def s3(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-southeast-1")
    with mock_aws():
        client = boto3.client("s3", region_name="ap-southeast-1")
        client.create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": "ap-southeast-1"},
        )
        yield client


@pytest.fixture
def data(module_info, venue_info, sem1):
    sessions = build_sessions(module_info, venue_info, sem1)
    return sessions, build_modules(module_info, sessions)


def read(s3, key):
    return json.load(s3.get_object(Bucket=BUCKET, Key=key)["Body"])


def keys(s3):
    return {o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET)["Contents"]}


def test_first_run_writes_everything(s3, sem1, data):
    sessions, modules = data
    result = publish(s3, BUCKET, sem1, sessions, modules, NOW)

    index = read(s3, f"{PREFIX}/index.json")
    assert index["sessionCount"] == len(sessions)
    assert index["lessonTypes"] == {"Lecture": "LEC"}
    assert index["generatedAt"] == "2026-10-18T19:00:00Z"
    assert {f"{PREFIX}/days/{d}.json" for d in index["days"]} <= keys(s3)
    assert {f"{PREFIX}/weeks/{w['week']}.json" for w in index["weeks"]} <= keys(s3)

    day = read(s3, f"{PREFIX}/days/2026-10-13.json")
    assert day["week"] == "week-09"
    assert "SC3210-LEC-1@2026-10-13" in {s["id"] for s in day["sessions"]}

    week = read(s3, f"{PREFIX}/weeks/week-09.json")
    assert (week["startDate"], week["endDate"]) == ("2026-10-12", "2026-10-18")
    assert {s["date"] for s in week["sessions"]} <= {
        f"2026-10-{d}" for d in range(12, 19)
    }

    assert read(s3, "lectures/current.json")["path"] == f"{PREFIX}/"
    assert read(s3, f"{PREFIX}/modules.json")["items"]
    assert result["written"] == result["files"] + 1
    assert result["deleted"] == 0


def test_rerun_on_same_data_writes_nothing(s3, sem1, data):
    sessions, modules = data
    publish(s3, BUCKET, sem1, sessions, modules, NOW)
    result = publish(s3, BUCKET, sem1, sessions, modules, NOW.replace(day=19))

    assert result["written"] == 0
    assert read(s3, f"{PREFIX}/index.json")["generatedAt"] == "2026-10-18T19:00:00Z"


def test_dates_that_disappear_are_deleted(s3, sem1, data):
    sessions, modules = data
    publish(s3, BUCKET, sem1, sessions, modules, NOW)
    remaining = [s for s in sessions if s["date"] != "2026-10-13"]
    # Keep the drop small so the bad-data check doesn't fire.
    result = publish(s3, BUCKET, sem1, remaining, modules, NOW)

    assert f"{PREFIX}/days/2026-10-13.json" not in keys(s3)
    assert result["deleted"] == 1
    assert "2026-10-13" not in read(s3, f"{PREFIX}/index.json")["days"]


def test_big_drop_keeps_previous_files(s3, sem1, data):
    sessions, modules = data
    publish(s3, BUCKET, sem1, sessions, modules, NOW)
    before = keys(s3)

    with pytest.raises(SuspiciousDataError):
        publish(s3, BUCKET, sem1, sessions[:10], modules, NOW)

    assert keys(s3) == before
    assert read(s3, f"{PREFIX}/index.json")["sessionCount"] == len(sessions)


def test_no_sessions_is_an_error(s3, sem1):
    with pytest.raises(SuspiciousDataError):
        publish(s3, BUCKET, sem1, [], [], NOW)


def test_handler(s3, monkeypatch, module_info, venue_info):
    monkeypatch.setenv("WEB_BUCKET", BUCKET)
    monkeypatch.setattr(
        ingest_handler,
        "fetch_semester",
        lambda acad_year, semester: (module_info, venue_info),
    )

    result = ingest_handler.handler({}, None, s3=s3, now=NOW)

    assert result["semester"] == "2026-2027/sem-1"
    assert result["sessions"] > 0
    assert f"{PREFIX}/index.json" in keys(s3)
