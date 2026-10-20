"""Turn NUSMods moduleInfo + venueInformation into lecture sessions (pure functions)."""

import re
from collections import defaultdict
from datetime import date

from ingest.academic_calendar import Semester, class_dates
from ingest.lesson_types import INCLUDED_LESSON_TYPES, LESSON_TYPE_CODES
from ingest.venues import building_for, is_online

# All-day NUS-ISS courses aren't lectures that can join by outsiders.
EXCLUDED_FACULTIES = frozenset({"NUS-ISS"})

_LEVEL = re.compile(r"[A-Z]+(\d)")


def module_level(module_code: str) -> int | None:
    """SC3210 -> 3000."""
    match = _LEVEL.match(module_code)
    return int(match.group(1)) * 1000 if match else None


def split_module_code(raw: str) -> tuple[str, list[str]]:
    """Cross-listed classes come as 'CS2103T/\u200bCS2103': first code, then the rest."""
    codes = [c.strip() for c in raw.replace("\u200b", "").split("/") if c.strip()]
    return codes[0], codes[1:]


def hhmm(time: str) -> str:
    """'1000' -> '10:00'."""
    return f"{time[:2]}:{time[2:]}"


# transformation
def build_sessions(
    module_info: list[dict], venue_info: dict, semester: Semester
) -> list[dict]:
    """Every lecture session in the semester, sorted by date, start time and module."""
    modules = {m["moduleCode"]: m for m in module_info}

    # (module, lessonType, classNo, date, start, venue) -> (end, size, crossListed).
    # NUSMods sometimes lists the same slot twice with different end times; keep
    # the longer one.
    # CS2103/CS2103T gives moduleCode:CS2103 and crossListed:CS2103T
    slots: dict[tuple, tuple] = {}
    for venue, days in venue_info.items():
        for day in days:
            for lesson in day["classes"]:
                if lesson["lessonType"] not in INCLUDED_LESSON_TYPES:
                    continue
                module_code, cross_listed = split_module_code(lesson["moduleCode"])
                if modules.get(module_code, {}).get("faculty") in EXCLUDED_FACULTIES:
                    continue
                for on in class_dates(semester, day["day"], lesson["weeks"]):
                    key = (
                        module_code,
                        lesson["lessonType"],
                        lesson["classNo"],
                        on,
                        lesson["startTime"],
                        venue,
                    )
                    value = (
                        lesson["endTime"],
                        lesson.get("size") or 0,
                        tuple(cross_listed),
                    )
                    if key not in slots or value > slots[key]:
                        slots[key] = value

    groups: dict[tuple, list[tuple]] = defaultdict(list)
    for key, value in slots.items():
        groups[key[:4]].append(
            key + value
        )  # group the modules with (module, lessonType, classNo, date)

    # example:
    # groups = {
    # ("SC3210","Lecture","1", 2026-10-13): [ (…"1000","UTSRC-GLR"…) ], # 1 item
    # ("ID3041","Lecture","1", 2026-10-15): [ (…"1400","SDE3-LT424"…), (…"1400","SDE3-LT425"…) ], # 2 rooms (same module, same date)
    # ("CG2028","Lecture","01",2026-08-11): [ (…"1400","E-Learn_A"…),  (…"1500","SDE3-LT424"…) ], # 2 times
    # }

    sessions = []
    for (module_code, lesson_type, class_no, on), group in groups.items():
        base_id = f"{module_code}-{LESSON_TYPE_CODES[lesson_type]}-{class_no}@{on.isoformat()}"
        for occurrence in group:
            sessions.append(
                _session(
                    _session_id(base_id, occurrence, group),
                    occurrence,
                    modules.get(module_code, {}),
                )
            )

    sessions.sort(key=lambda s: (s["date"], s["startTime"], s["moduleCode"], s["id"]))
    return sessions


def _session_id(base_id: str, occurrence: tuple, group: list[tuple]) -> str:
    """`<module>-LEC-<classNo>@<date>`
    When a class has several sessions on the same day:
    a different start time adds `-HHMM`, a different room adds `-<venue>`."""
    # occurrence = (module, lessonType, classNo, date, start, venue, end, size, cross)
    start, venue = occurrence[4], occurrence[5]

    start_times = {o[4] for o in group}
    rooms_at_this_start = {o[5] for o in group if o[4] == start}

    session_id = base_id
    if len(start_times) > 1:
        session_id += f"-{start}"
    if len(rooms_at_this_start) > 1:
        session_id += f"-{venue}"
    return session_id


def _session(session_id: str, occurrence: tuple, module: dict) -> dict:
    module_code, lesson_type, class_no, on, start, venue, end, size, cross = occurrence
    return {
        "id": session_id,
        "moduleCode": module_code,
        "crossListed": list(cross),
        "moduleTitle": module.get("title"),
        "faculty": module.get("faculty"),
        "department": module.get("department"),
        "level": module_level(module_code),
        "lessonType": lesson_type,
        "classNo": class_no,
        "date": on.isoformat(),
        "startTime": hhmm(start),
        "endTime": hhmm(end),
        "venue": venue,
        "building": building_for(venue),
        "online": is_online(venue),
        "size": size,
    }


def build_modules(module_info: list[dict], sessions: list[dict]) -> list[dict]:
    """Descriptions for the modules that have sessions, for recommendations."""
    codes = {s["moduleCode"] for s in sessions}
    return [
        {
            "moduleCode": m["moduleCode"],
            "title": m.get("title"),
            "faculty": m.get("faculty"),
            "department": m.get("department"),
            "level": module_level(m["moduleCode"]),
            "moduleCredit": m.get("moduleCredit"),
            "description": m.get("description"),
        }
        for m in sorted(module_info, key=lambda m: m["moduleCode"])
        if m["moduleCode"] in codes
    ]


def group_by_date(sessions: list[dict]) -> dict[date, list[dict]]:
    by_date: dict[date, list[dict]] = defaultdict(list)
    for session in sessions:
        by_date[date.fromisoformat(session["date"])].append(session)
    return dict(sorted(by_date.items()))
