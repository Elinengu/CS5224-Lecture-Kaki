# Lecture Data (ingest output)

The ingest Lambda (`backend/handlers/ingest.py`) turns NUSMods timetables into
static JSON files in the web bucket. The frontend reads these files directly;
there is no API endpoint for lecture data.

Only **lectures** are included (no tutorials/labs), and NUS-ISS courses are left
out. NUS holidays are already removed from the dates.

## Files

Everything lives under `lectures/` in the web bucket:

```text
lectures/
  current.json                      Which semester to show (start here)
  <acadYear>/sem-<n>/               e.g. 2026-2027/sem-1/
    index.json                      Days, weeks and counts for the semester
    days/<YYYY-MM-DD>.json          All sessions on one date
    weeks/<label>.json              All sessions in one Mon-Sun week
    modules.json                    Module descriptions (for recommendations)
```

Week labels: `week-01` ... `week-06`, `recess`, `week-07` ... `week-13`,
`reading`, `exam-1`, `exam-2`. A day or week file exists only when it has at
least one session, so always use `index.json` to find what's available instead
of guessing file names.

Rough sizes (AY2026/27 Sem 1, ~24.9k sessions): `index.json` ~3 KB, a day
~170 KB, a week ~780 KB, `modules.json` ~1.2 MB. Prefer day files for normal
views.

## How to read them

1. Fetch `lectures/current.json` and take its `path`.
2. Fetch `<path>index.json` to get the list of days and weeks.
3. Fetch `<path>days/<date>.json` or `<path>weeks/<label>.json` as needed.

```ts
const BASE = "/lectures/"; // same origin as the site (CloudFront in front of the web bucket)

const current = await fetch(`${BASE}current.json`).then((r) => r.json());
const index = await fetch(`/${current.path}index.json`).then((r) => r.json());

const today = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Singapore" }); // YYYY-MM-DD
if (index.days.includes(today)) {
  const day = await fetch(`/${current.path}days/${today}.json`).then((r) => r.json());
  console.log(day.sessions);
}
```

Files are served with `Cache-Control: public, max-age=86400`, so browsers and
CloudFront reuse a copy for up to a day and updates can take up to a day to show.
Data refreshes on Mondays (weekly in weeks 1-3, otherwise on the first Monday of
the month).

## Schemas

Every file has these common fields:

| Field | Type | Example |
|---|---|---|
| `generatedAt` | string (UTC ISO) | `"2026-10-20T13:59:37Z"` |
| `acadYear` | string | `"2026-2027"` |
| `semester` | number | `1` |

`current.json` is the exception: it has the common fields plus `path`.

### `current.json`

```json
{
  "generatedAt": "2026-10-20T13:59:37Z",
  "acadYear": "2026-2027",
  "semester": 1,
  "path": "lectures/2026-2027/sem-1/"
}
```

### `index.json`

```json
{
  "generatedAt": "...", "acadYear": "2026-2027", "semester": 1,
  "sessionCount": 24858,
  "days": ["2026-08-11", "2026-08-12", "..."],
  "weeks": [
    { "week": "week-01", "startDate": "2026-08-10", "endDate": "2026-08-16", "sessionCount": 1573 }
  ],
  "lessonTypes": { "Lecture": "LEC" }
}
```

- `days`: every date that has a day file, sorted.
- `weeks`: every week that has a week file, in calendar order.
- `lessonTypes`: lesson type -> short code used in session ids.

### `days/<date>.json`

```json
{
  "generatedAt": "...", "acadYear": "2026-2027", "semester": 1,
  "date": "2026-10-20",
  "week": "week-10",
  "sessions": [ /* Session, sorted by startTime then moduleCode */ ]
}
```

### `weeks/<label>.json`

```json
{
  "generatedAt": "...", "acadYear": "2026-2027", "semester": 1,
  "week": "week-10",
  "startDate": "2026-10-19",
  "endDate": "2026-10-25",
  "sessions": [ /* Session, sorted by date, startTime, moduleCode */ ]
}
```

### Session

```json
{
  "id": "BT1101-LEC-1@2026-10-20",
  "moduleCode": "BT1101",
  "crossListed": [],
  "moduleTitle": "Introduction to Business Analytics",
  "faculty": "Computing",
  "department": "Information Systems and Analytics",
  "level": 1000,
  "lessonType": "Lecture",
  "classNo": "1",
  "date": "2026-10-20",
  "startTime": "08:00",
  "endTime": "10:00",
  "venue": "LT11",
  "building": "AS2",
  "online": false,
  "size": 400
}
```

| Field | Type | Notes |
|---|---|---|
| `id` | string | Unique and stable across runs. See [Session ids](#session-ids). |
| `moduleCode` | string | Primary code. |
| `crossListed` | string[] | Other codes for the same class, e.g. `PR3152` -> `["PR2157"]`. Usually empty. |
| `moduleTitle`, `faculty`, `department` | string \| null | From NUSMods module info. |
| `level` | number \| null | `1000`, `2000`, ... from the code (`SC3210` -> `3000`). |
| `lessonType` | string | Currently always `"Lecture"`. |
| `classNo` | string | Keep as string: `"1"` and `"01"` both occur. |
| `date` | string | `YYYY-MM-DD`, Singapore local date. |
| `startTime`, `endTime` | string | `HH:MM`, 24h, Singapore time. |
| `venue` | string | NUSMods venue code, e.g. `COM1-0207`, `LT11`, `E-Learn_A`. |
| `building` | string \| null | Derived building code (`COM1-0207` -> `COM1`, `LT11` -> `AS2`). `null` for online and unmapped venues. |
| `online` | boolean | `true` for `E-Learn*` / `E-Hybrid*` venues. |
| `size` | number \| null | Class capacity from NUSMods. |

### `modules.json`

Only modules that have at least one session this semester, sorted by code.

```json
{
  "generatedAt": "...", "acadYear": "2026-2027", "semester": 1,
  "items": [
    {
      "moduleCode": "ABM5003",
      "title": "Biomedical Innovation & Enterprise",
      "faculty": "Yong Loo Lin Sch of Medicine",
      "department": "NUS Medicine Dean's Office",
      "level": 5000,
      "moduleCredit": "4",
      "description": "This elective aims to ..."
    }
  ]
}
```

`moduleCredit` is a string (NUSMods format). Join with sessions on `moduleCode`.

## Session ids

Format: `<moduleCode>-<lessonTypeCode>-<classNo>@<date>`, e.g.
`BT1101-LEC-1@2026-10-20`.

When one class has more than one session on the same day, a suffix keeps the
ids unique:

- Different start times: `-HHMM` (`CG2028-LEC-01@2026-08-11-1400`).
- Same start time in different rooms: `-<venue>`.

Ids depend only on the timetable, so they stay the same across ingest runs and
are safe to store, e.g. for a user's saved sessions.

## Working with the data locally

Generate the real files without AWS (live NUSMods data, in-memory S3):

```bash
cd backend && poetry run python scripts/ingest_local.py
```

The files are written to `backend/out/ingest/lectures/`, which is git-ignored.
Use `--date YYYY-MM-DD` to pick another semester. To serve them to the frontend
during development, point a static server at that folder:

```bash
cd backend/out/ingest && python3 -m http.server 8001
```

Then `http://localhost:8001/lectures/current.json` works like the deployed path.
The server sends no CORS headers, so use a dev-server proxy (e.g. Vite
`server.proxy` for `/lectures`) rather than fetching it cross-origin.

## Changing the format

The output is produced by `backend/ingest/transform.py` (session and module
fields) and `backend/ingest/publish.py` (file layout). Adding a field is safe;
renaming or removing one breaks the frontend, so update this doc and the
frontend in the same PR.
