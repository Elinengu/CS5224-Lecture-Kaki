from collections import Counter

import pytest

from ingest.transform import build_modules, build_sessions, module_level


@pytest.fixture
def sessions(module_info, venue_info, sem1):
    return build_sessions(module_info, venue_info, sem1)


def by_module(sessions, code, class_no=None):
    return [
        s
        for s in sessions
        if s["moduleCode"] == code and (class_no is None or s["classNo"] == class_no)
    ]


def test_session_shape(sessions):
    session = next(s for s in sessions if s["id"] == "SC3210-LEC-1@2026-10-13")
    assert session == {
        "id": "SC3210-LEC-1@2026-10-13",
        "moduleCode": "SC3210",
        "crossListed": [],
        "moduleTitle": "AI and Society",
        "faculty": "Arts and Social Science",
        "department": "Sociology and Anthropology",
        "level": 3000,
        "lessonType": "Lecture",
        "classNo": "1",
        "date": "2026-10-13",
        "startTime": "10:00",
        "endTime": "12:00",
        "venue": "UTSRC-GLR",
        "building": "UTSRC",
        "online": False,
        "size": 40,
    }


def test_only_lectures(sessions):
    assert {s["lessonType"] for s in sessions} == {"Lecture"}
    assert len(by_module(sessions, "SC3210")) == 13


def test_nus_iss_excluded(sessions):
    assert by_module(sessions, "EBA5003") == []


def test_ids_unique_and_sorted(sessions):
    assert not [i for i, n in Counter(s["id"] for s in sessions).items() if n > 1]
    keys = [(s["date"], s["startTime"], s["moduleCode"], s["id"]) for s in sessions]
    assert keys == sorted(keys)


def test_room_change_by_week_keeps_plain_id(sessions):
    laj = by_module(sessions, "LAJ1201", "1")
    assert len(laj) == 11  # 13 Mondays minus National Day and Deepavali (observed)
    assert {s["venue"] for s in laj if s["date"] < "2026-09-21"} == {"LT19"}
    assert {s["venue"] for s in laj if s["date"] > "2026-09-21"} == {"LT14"}
    assert all("@" in s["id"] and s["id"].endswith(s["date"]) for s in laj)


def test_two_rooms_same_time_get_venue_suffix(sessions):
    thursday = [s for s in by_module(sessions, "ID3041") if s["date"] == "2026-10-15"]
    assert sorted(s["id"] for s in thursday) == [
        "ID3041-LEC-1@2026-10-15-SDE3-LT424",
        "ID3041-LEC-1@2026-10-15-SDE3-LT425",
    ]
    friday = [s for s in by_module(sessions, "ID3041") if s["date"] == "2026-10-16"]
    assert [s["id"] for s in friday] == ["ID3041-LEC-1@2026-10-16"]


def test_two_start_times_same_day_get_time_suffix(sessions):
    tuesday = [s for s in by_module(sessions, "CG2028") if s["date"] == "2026-08-11"]
    assert sorted(s["id"] for s in tuesday) == [
        "CG2028-LEC-01@2026-08-11-1400",
        "CG2028-LEC-01@2026-08-11-1500",
    ]


def test_duplicate_slot_keeps_longer_entry(sessions):
    bmi = [s for s in by_module(sessions, "BMI5102") if s["date"] == "2026-10-05"]
    assert len(bmi) == 1
    assert bmi[0]["endTime"] == "21:30"


def test_cross_listed_code(sessions):
    ce = by_module(sessions, "CE2112T")
    assert ce
    assert all(s["crossListed"] == ["CE2112"] for s in ce)
    assert ce[0]["moduleTitle"]


def test_online_venue(sessions):
    nm = by_module(sessions, "NM2103")
    online = [s for s in nm if s["online"]]
    assert online and all(s["venue"] == "E-Learn_C" for s in online)
    assert all(s["building"] is None for s in online)
    assert {s["building"] for s in nm if not s["online"]} == {"BIZ2"}


def test_module_level():
    assert module_level("SC3210") == 3000
    assert module_level("LAJ1201") == 1000
    assert module_level("??") is None


def test_build_modules(module_info, sessions):
    modules = build_modules(module_info, sessions)
    assert "EBA5003" not in {m["moduleCode"] for m in modules}
    sc = next(m for m in modules if m["moduleCode"] == "SC3210")
    assert sc["description"]
    assert sc["level"] == 3000
