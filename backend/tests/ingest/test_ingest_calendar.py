from datetime import date

import pytest

from ingest.academic_calendar import (
    SEMESTERS,
    class_dates,
    semester_for,
    teaching_week_monday,
    week_label,
)

SEM1 = SEMESTERS[("2026-2027", 1)]
ALL_WEEKS = list(range(1, 14))


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 10, 18), ("2026-2027", 1)),
        (date(2026, 8, 1), ("2026-2027", 1)),
        (date(2027, 1, 4), ("2026-2027", 2)),
        (date(2027, 6, 15), ("2026-2027", 2)),  # June/July keep serving Sem 2
    ],
)
def test_semester_for(today, expected):
    semester = semester_for(today)
    assert (semester.acad_year, semester.number) == expected


def test_semester_for_missing_calendar_entry():
    with pytest.raises(KeyError, match="2027-2028"):
        semester_for(date(2027, 8, 10))


def test_teaching_weeks_skip_recess():
    assert teaching_week_monday(SEM1, 1) == date(2026, 8, 10)
    assert teaching_week_monday(SEM1, 6) == date(2026, 9, 14)
    assert teaching_week_monday(SEM1, 7) == date(2026, 9, 28)
    assert teaching_week_monday(SEM1, 13) == date(2026, 11, 9)


@pytest.mark.parametrize(
    ("day", "label"),
    [
        (date(2026, 8, 10), "week-01"),
        (date(2026, 9, 20), "week-06"),
        (date(2026, 9, 22), "recess"),
        (date(2026, 9, 28), "week-07"),
        (date(2026, 11, 13), "week-13"),
        (date(2026, 11, 16), "reading"),
        (date(2026, 11, 23), "exam-1"),
        (date(2026, 12, 5), "exam-2"),
        (date(2026, 12, 6), None),
        (date(2026, 8, 9), None),
    ],
)
def test_week_label(day, label):
    assert week_label(SEM1, day) == label


def test_list_weeks():
    dates = class_dates(SEM1, "Tuesday", ALL_WEEKS)
    assert len(dates) == 13
    assert dates[0] == date(2026, 8, 11)
    assert date(2026, 9, 22) not in dates  # recess
    assert date(2026, 9, 29) in dates  # week 7
    assert dates[-1] == date(2026, 11, 10)


def test_public_holidays_dropped():
    dates = class_dates(SEM1, "Monday", ALL_WEEKS)
    assert date(2026, 8, 10) not in dates  # National Day observed
    assert date(2026, 11, 9) not in dates  # Deepavali observed
    assert len(dates) == 11


def test_date_range_weeks_count_calendar_weeks_from_start():
    weeks = {
        "start": "2026-08-13",
        "end": "2026-11-19",
        "weeks": [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 15],
    }
    dates = class_dates(SEM1, "Thursday", weeks)
    assert dates[0] == date(2026, 8, 13)
    assert date(2026, 9, 24) not in dates
    assert dates[-1] == date(2026, 11, 19)
    assert len(dates) == 14


def test_date_range_without_weeks_uses_interval():
    weeks = {"start": "2026-10-01", "end": "2026-10-29", "weekInterval": 2}
    assert class_dates(SEM1, "Thursday", weeks) == [
        date(2026, 10, 1),
        date(2026, 10, 15),
        date(2026, 10, 29),
    ]


def test_date_range_outside_semester_dropped():
    weeks = {"start": "2026-07-11", "end": "2026-08-15", "weeks": [1, 6]}
    assert class_dates(SEM1, "Saturday", weeks) == [date(2026, 8, 15)]
