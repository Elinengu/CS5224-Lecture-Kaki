# Ingest pipeline (workstream 0)

Scheduled Lambda that turns NUSMods data into the lecture JSON the frontend and
lecture service read. Extends §1.1–1.2 of `team-agreements-and-aws-setup.md`
and step 0 of `implementation-plan.md`. Code: `backend/handlers/ingest.py` and
`backend/ingest/`.

## Source data

Two downloads per run (checked against AY2026-2027 data in Oct 2026):

| Endpoint | Gives us |
|---|---|
| `/v2/<acadYear>/moduleInfo.json` (~19 MB) | title, faculty, department, description, credits. **No timetable.** |
| `/v2/<acadYear>/semesters/<n>/venueInformation.json` | every scheduled class per room per day: `moduleCode`, `lessonType`, `classNo`, `startTime`, `endTime`, `weeks`, `size` |

Things the code handles:

- Times are `"HHMM"` → output `"HH:MM"`.
- `weeks` is either a list of teaching-week numbers (recess falls after week 6)
  or `{"start", "end", "weeks"?, "weekInterval"?}`, where week numbers count
  calendar weeks from `start`.
- Online classes appear under pseudo-rooms `E-Learn_*` / `E-Hybrid_*`.
- Cross-listed classes appear as `"CS2103T/​CS2103"` (slash plus a
  zero-width space).
- Some slots are listed twice with different end times (e.g. BMI5102 Mon
  18:30–20:00 and 18:30–21:30 in the same room).
- A class can move rooms in some weeks (LAJ1201: LT19 weeks 1–6, LT14 weeks
  7–13). Rooms are attached per date, so each date shows the right room.

## Decisions

Decided by the team (Oct 2026):

| # | Topic | Decision |
|---|---|---|
| 1 | Semester | Automatic from today's Singapore date: Aug–Dec → Sem 1, Jan–Jul → Sem 2 (Sem 2 files keep being served through June–July; no Special Term ingest). |
| 2 | Lesson types | `Lecture` only. |
| 3 | Classes with no room | Skipped (they aren't in venueInformation). |
| 4 | Postgrad / evening | Included, with a `level` field (SC3210 → 3000). |
| 5 | Weekends | Included. |
| 6 | Range | Whole semester, week 1 to the end of exams. |
| 7 | Public holidays | Lectures on gazetted holidays (and days observed in lieu) are dropped. |
| 8 | Session ID | `<module>-<code>-<classNo>@<YYYY-MM-DD>`, e.g. `SC3210-LEC-1@2026-10-13`. |
| 9 | Lesson-type codes | `Lecture` → `LEC`, defined once in `ingest/lesson_types.py` and published in `index.json`. |
| 10 | Same class in two rooms at once | One session per room; only those sessions get the room appended: `ID3041-LEC-1@2026-10-15-SDE3-LT424`. |
| 11–12 | Files | Per day and per week, under `lectures/<acadYear>/sem-<n>/days/` and `/weeks/`; weeks named by NUS week (`week-01` … `week-13`, `recess`, `reading`, `exam-1`, `exam-2`). |
| 13 | Index | `index.json` per semester. |
| 14 | Extra fields | `department`, `size`, `level`; descriptions go in a separate `modules.json`. |
| 15 | Building | Prefix of the room code (`COM1-0207` → `COM1`), plus a map for lecture theatres in `ingest/venues.py`. |
| 16 | Faculty names | NUSMods' raw names; the frontend maps them to display labels. |
| 17 | Schedule | Weekly in teaching weeks 1–3, then monthly. Implemented as a Monday 03:00 SGT schedule; the handler skips Mondays that aren't in weeks 1–3 or the first Monday of the month (`ingest_due`). A manual invoke with `{"date": ...}` always runs. |
| 18 | Vanished dates | Their files are deleted. |
| 19 | Bad data | Abort without writing if sessions drop below 50% of the last run or to zero; the Lambda error triggers an email alert. |
| 20 | Calendar | Hand-entered table in `ingest/academic_calendar.py`. |
| 21 | Python | 3.14 (Lambda `python3.14`); export `requirements.txt` from Poetry for `sam build`. |
| 22 | HTTP | Standard-library `urllib`; no extra runtime dependency. |
| 23 | Code location | `backend/handlers/ingest.py` + `backend/ingest/`. |
| 24 | Frontend access | Browsing reads the JSON straight from CloudFront; the API handles filtered search and recommendations. |
| 25 | Health path | `/api/health`. |
| 26 | Online classes | Kept, marked `"online": true`. |
| 27 | NUS-ISS all-day courses | Dropped (faculty `NUS-ISS`). |

Defaults chosen during implementation — **confirm or change**:

| Topic | Default |
|---|---|
| Class meets twice on one date at different times (13 classes in Sem 1, e.g. CG2028 Tue 14:00 online + 15:00 in SDE3-LT424) | Both sessions get the start time appended: `CG2028-LEC-01@2026-08-11-1400`. Same pattern as decision 10. |
| Cross-listed codes (`CE2112T/CE2112`) | `moduleCode` is the first code; the others go in a `crossListed` list. Keeps `/` out of IDs, which would break `/api/sessions/{id}/posts`. |
| Slot listed twice with different end times | Keep the longer one. |
| Lecture-theatre buildings | Derived from NUSMods room coordinates (nearest building code). LT3, LT4 and LT16 had no building close enough and are left `null`. Someone who knows campus should check the map. |
| NUS Well-Being Day (Fri 9 Oct 2026 in one version of the Registrar calendar) | **Not** treated as a holiday; lectures that day are kept. |

## Output

```
lectures/current.json                          {"acadYear", "semester", "path"}: semester being served
lectures/2026-2027/sem-1/index.json            days, weeks, counts, lesson-type codes
lectures/2026-2027/sem-1/days/2026-10-13.json
lectures/2026-2027/sem-1/weeks/week-09.json
lectures/2026-2027/sem-1/modules.json          {"items": [...]} with descriptions
```

Day file (week files are the same with `week`, `startDate`, `endDate` instead of
`date`):

```json
{
  "generatedAt": "2026-10-18T19:00:00Z",
  "acadYear": "2026-2027",
  "semester": 1,
  "date": "2026-10-13",
  "week": "week-09",
  "sessions": [
    {
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
      "online": false,
      "size": 40
    }
  ]
}
```

Sizes for Sem 1 (25,220 sessions): 83 day files (median ~140 KB), 17 week files
(up to ~775 KB), `modules.json` ~1.2 MB, all before compression. CloudFront
should have compression on.

## How a run works

1. Pick the semester from today's Singapore date (or `{"date": "YYYY-MM-DD"}` in
   the invoke event). Scheduled runs that aren't due stop here.
2. Download moduleInfo and venueInformation.
3. Keep `Lecture` classes, drop NUS-ISS, expand weeks to dates, drop holidays
   and dates outside the semester, and de-duplicate.
4. Refuse to publish if the session count is zero or below 50% of the last run.
5. Write day, week and module files whose content changed. The content hash
   (excluding `generatedAt`) is stored as S3 metadata, so unchanged data writes
   nothing.
6. Write `index.json` after the files it lists; then delete day and week files
   that are no longer listed; then `current.json`.

A full Sem 1 run against live NUSMods takes about 5 s (S3 mocked).

## Infra still needed (`infra/template.yaml`, workstream 7)

- `IngestFunction`: `CodeUri: ../backend`, `Handler: handlers.ingest.handler`,
  `Runtime: python3.14`, 1024 MB, timeout 300 s, env `WEB_BUCKET`.
- `ScheduleV2` **every Monday**, `cron(0 19 ? * SUN *)` (Mon 03:00 SGT); the
  handler decides whether the run is due, so the schedule never changes per semester.
- Policy `S3CrudPolicy` on the web bucket. `S3WritePolicy` (as in the guide)
  isn't enough: the change check needs `GetObject`/`HeadObject`, and cleanup
  needs `DeleteObject`.
- A CloudWatch alarm on the function's `Errors` metric → SNS topic → team email.
- `backend/requirements.txt` exported from Poetry (no runtime dependencies for
  ingest; `boto3` is in the Lambda runtime).

## Before each new semester or academic year

Add the semester to `SEMESTERS` and that year's holidays to `PUBLIC_HOLIDAYS` in
`ingest/academic_calendar.py`. Without a calendar entry the run fails with a
clear error rather than guessing.
