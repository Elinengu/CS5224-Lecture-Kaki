# Ingest pipeline plan (workstream 0)

Plan for the scheduled Lambda that turns NUSMods data into the per-day lecture
JSON the frontend and lecture service read. Builds on §1.1–1.2 of
`team-agreements-and-aws-setup.md` and step 0 of `implementation-plan.md`.

Status: **plan only — no code yet.** Items marked _Open_ need a team decision
before implementation.

## What NUSMods actually gives us (checked 16 Oct 2026, AY2026-2027)

| Endpoint | Size | Contains |
|---|---|---|
| `/v2/2026-2027/moduleInfo.json` | ~19 MB, 21k entries | title, faculty, department, description, semesters offered — **no timetable** |
| `/v2/2026-2027/semesters/1/venueInformation.json` | 599 venues | every scheduled class per venue per day: `moduleCode`, `lessonType`, `classNo`, `startTime`, `endTime`, `weeks`, `size` |
| `/v2/2026-2027/modules/<code>.json` | 1 per module | full timetable for one module (6.8k modules → 6.8k requests) |

So the implementation plan's two-file approach works: **venueInformation gives
the timetable, moduleInfo gives title and faculty — two requests per run**,
instead of thousands of per-module fetches.

Known gap: a class with no venue (online, TBA) is not in venueInformation.
4,239 modules are offered in Sem 1 but only 2,524 appear in the venue file. For
an app about walking into a lecture, venue-less classes are not useful, so we
accept the gap and note it in the report.

### Shapes to handle

- Times are `"HHMM"` strings (`"1000"`) → normalise to `"HH:MM"`.
- `weeks` comes in two forms (9,335 list / 127 dict in Sem 1):
  - **List** `[1, 2, …, 13]` — teaching-week numbers. Needs the academic
    calendar: week 1 Monday, plus the recess week inserted after week 6.
  - **Dict** `{"start": "2026-08-13", "end": "2026-11-19", "weeks": [1..6, 8..15]}`
    — calendar weeks counted from `start` (recess is just a skipped number).
    `weeks` may be absent (every week from start to end; honour
    `weekInterval` if present), and start may equal end (one-off).
- `lessonType` values seen in Sem 1 with "lecture" in them: `Lecture` (2,235),
  `Packaged Lecture` (46), `Design Lecture` (41). Also `Sectional Teaching`
  (969), which is lecture-like in some faculties.

### Academic calendar (AY2026-2027 Sem 1)

Inferred from the data (a dict-form week-1 lecture on Thu 13 Aug): **week 1
starts Mon 10 Aug 2026**; recess week 19–27 Sep; teaching weeks 7–13 from
Mon 28 Sep. Verify against the NUS Registrar calendar and keep it in one small
config table in code, keyed by `(acadYear, semester)`.

## Design

### Code layout

```
backend/handlers/ingest.py   # Lambda entry point (Handler: handlers.ingest.handler)
backend/ingest/
  nusmods.py                 # fetch the two files (httpx, timeout + retry)
  calendar.py                # (acadYear, sem) → week-1 Monday, recess; week → date
  lesson_types.py            # the ONE lessonType ↔ short-code mapping (LEC, TUT, …)
  transform.py               # pure functions: raw classes → per-day session lists
  writer.py                  # S3 writes, hash compare, index
backend/tests/ingest/        # fixtures trimmed from real NUSMods files; no network
```

Ingest stays out of `app/` so the API Lambda and ingest Lambda share a code
URI without one importing the other's dependencies at startup.

### Steps per run

1. Fetch moduleInfo + venueInformation for the configured `ACAD_YEAR` and
   `SEMESTER` (environment variables, so next semester is a config change).
2. Keep classes whose `lessonType` is in the lecture allowlist.
3. De-duplicate (a class can appear under more than one venue entry).
4. Expand `weeks` into Singapore-local dates using the calendar.
5. Join title + faculty from moduleInfo; add `building` (derived from the
   venue code prefix where possible, else omitted — _Open_: is a venue→building
   map worth it?).
6. Group by date; sort each day by `startTime`, then `moduleCode`.
7. For each day, serialise deterministically; compare a SHA-256 of the
   `sessions` array with the hash stored as S3 object metadata; write only
   when it changed (re-running changes nothing — the plan's "done when").
8. Write `index.json` last (list of dates + `generatedAt`), so the frontend
   never sees an index pointing at a missing file.
9. Log counts (classes in, sessions out, files written/unchanged); return
   them as the Lambda result so `aws lambda invoke` shows them.

### Output (per §1.2)

```json
{
  "generatedAt": "2026-10-16T03:00:00Z",
  "date": "2026-10-13",
  "sessions": [
    {
      "id": "<see Open decision 1>",
      "moduleCode": "SC3210",
      "moduleTitle": "…",
      "faculty": "…",
      "lessonType": "Lecture",
      "classNo": "1",
      "startTime": "10:00",
      "endTime": "12:00",
      "venue": "UTSRC-GLR",
      "building": "…"
    }
  ]
}
```

### Infra (in `infra/template.yaml`, owned by workstream 7)

- `IngestFunction`: `CodeUri: ../backend`, `Handler: handlers.ingest.handler`,
  1024 MB, timeout 300 s (two downloads + ~100 small writes is well inside it).
- `ScheduleV2` event: `cron(0 19 ? * SUN *)` (Mon 03:00 SGT), as in the guide.
- Policy: `S3CrudPolicy` on the web bucket (the hash compare needs
  `GetObject`/`HeadObject`, which `S3WritePolicy` lacks; deleting stale day
  files needs `DeleteObject`).
- Env: `WEB_BUCKET`, `ACAD_YEAR`, `SEMESTER`.
- Runtime/packaging must match the repo — see Open decision 4.

### Tests

- `calendar`: list weeks across recess; dict weeks with and without `weeks`;
  one-off date; week 13 → correct November date.
- `transform`: lecture filter, de-dup across venues, time normalisation, ID
  format, a class with two lectures on the same day.
- `writer`: unchanged hash → no write; index written last (S3 stubbed with
  `moto` or botocore `Stubber`).
- One end-to-end test on the trimmed SC3210 fixture.

## Open decisions

1. **Session ID format.** The agreements doc proposes
   `CS2040-LEC-1@2026-10-14`. That **collides**: 26 Sem 1 lecture classes meet
   twice on the same day (e.g. `CS2103T-LEC-G01` on Mondays), so two sessions
   would share an ID and a forum room. Options: append start time
   (`CS2103T-LEC-G01@2026-10-12-1000`), or use the CLAUDE.md-draft form
   `<module>-<type>-<classNo>-<date>-<startTime>`. Recommend the first: it
   keeps the agreed shape and only adds a suffix.
2. **File path.** Agreements doc: `lectures/2026-2027/sem-1/<date>.json`.
   An earlier draft: `data/lectures/<date>.json` + `index.json`. Recommend the
   agreements-doc path plus an `index.json` in the same folder.
3. **Lesson types counted as lectures.** `Lecture` + `Packaged Lecture` +
   `Design Lecture` (recommended), with or without `Sectional Teaching`.
4. **Python version and packaging.** Docs say Python 3.12 +
   `backend/requirements.txt`; the repo is Python 3.14 + Poetry. Lambda
   supports `python3.14`, so recommend keeping 3.14 and exporting
   `requirements.txt` from Poetry for `sam build` (or `poetry-plugin-export`
   in CI).
5. **Health path.** Docs say `GET /api/health`; the app has `GET /health`.
   Not an ingest issue, but the deploy smoke test depends on it.
