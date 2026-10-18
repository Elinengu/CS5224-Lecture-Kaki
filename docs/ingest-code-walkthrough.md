# Ingest code walkthrough

A guided tour of the ingest code, explained as your own design. It follows one
real lecture — **SC3210 (AI and Society), Tuesday 10:00–12:00 at UTSRC-GLR** —
from NUSMods all the way into S3.

Companion docs: `ingest-pipeline-plan.md` (decisions), `ingest-design-walkthrough.md`
(how to design it from scratch; interview prep), `ingest-deploy-runbook.md`
(deploy and test on AWS). Line numbers refer to the code as of this commit.

---

## 1. The big picture

The pipeline has one job: **once in a while, download NUSMods' timetable, keep
only the lectures, turn them into dated sessions, and save them as JSON files the
website can read.**

Four steps, each in its own file:

```
 AWS schedule (every Monday 03:00 SGT)
        │  calls
        ▼
 handlers/ingest.py ── the "boss": runs the 4 steps in order
        │
        ├─ 1. DECIDE     ingest/academic_calendar.py   which semester? is a run due today?
        ├─ 2. EXTRACT    ingest/nusmods.py             download 2 JSON files from NUSMods
        ├─ 3. TRANSFORM  ingest/transform.py           raw classes → clean lecture sessions
        │                  uses academic_calendar.py   (week numbers → real dates)
        │                  uses venues.py              (room → building, online?)
        │                  uses lesson_types.py        ("Lecture" → "LEC")
        └─ 4. LOAD       ingest/publish.py             write JSON files to S3, safely
```

(All paths are under `backend/`.)

**Why you split it this way:** each file does one kind of work.

- Only `nusmods.py` talks to the internet.
- Only `publish.py` talks to S3.
- Everything in the middle is pure logic: data in, data out. That's why you can
  test it in milliseconds with no network and no AWS.

---

## 2. Who starts it: `handlers/ingest.py`

AWS Lambda doesn't run a script top to bottom. It calls **one function** you name
in `infra/template.yaml` (`Handler: handlers.ingest.handler`). That's
`handler(event, context)` at `handlers/ingest.py:26`.

- `event` is whatever the caller sent. The Monday schedule sends nothing; a
  manual test can send `{"date": "2026-10-19"}`.
- `context` is Lambda information you don't use.

Read the function top to bottom:

| Lines | What happens | Why you designed it so |
|---|---|---|
| 27–32 | Work out "today". If the event has a `date`, use it (a manual run). Otherwise take the current time converted to Singapore time (`SINGAPORE = UTC+8`, line 20). | Lambda's clock is UTC. At 03:00 Singapore time it's still the previous day in UTC, so without converting you'd pick the wrong date. |
| 33 | `semester_for(today)` picks the semester. | Automatic, so nobody has to remember to switch semesters. |
| 35–38 | If this is a scheduled run and it isn't due, log "skipped" and stop. | Your rule: weekly in weeks 1–3, monthly after that. |
| 40 | **Extract:** download the two files. | |
| 41–42 | **Transform:** build sessions, then module descriptions. | |
| 44–51 | **Load:** publish to S3. The bucket name comes from an environment variable set in the template. | No bucket names hard-coded in the code; dev and prod differ only in configuration. |
| 52–53 | Log the result and return it. | The summary shows up in the logs and in the `aws lambda invoke` output. |

The `s3=None, now=None` parameters exist **only for tests**. Tests pass in a fake
S3 and a fixed clock, while real Lambda uses the defaults.

---

## 3. Step 1 — Decide: `ingest/academic_calendar.py`

This file holds everything about **time**. NUSMods only says "week 7"; this file
knows what date week 7 actually is.

**The data you hand-entered:**

- **`SEMESTERS`** (lines 28–31): for each semester, the Monday of week 1 and the
  last day of exams. Sem 1 runs from Mon 10 Aug 2026 to Sat 5 Dec 2026.
- **`PUBLIC_HOLIDAYS`** (lines 34–49): holiday dates, including days observed in
  lieu.
- **Why by hand:** it's only about 3 dates per semester, and NUS publishes them a
  year ahead. Writing code to scrape them wouldn't be worth it.

**The functions:**

**`semester_for(today)`**, lines 52–63:

- August–December gives Semester 1 of `"2026-2027"`.
- January–July gives Semester 2, which also covers June and July, so the Sem 2
  data keeps being served.
- If the semester isn't in the table, it **raises an error on purpose**. Guessing
  a calendar would quietly produce wrong dates; a loud failure triggers the alarm
  email instead.

**`teaching_week_monday(semester, week)`**, lines 66–69: the key piece of maths.

```
week 1–6  → week1_monday + (week − 1) weeks
week 7–13 → week1_monday + week weeks          ← +1 extra because recess week sits after week 6
```

Example: week 7 = 10 Aug + 7 weeks = **Mon 28 Sep**. (Recess is 21–27 Sep.)

**`week_label(semester, day)`**, lines 72–85: does the reverse. Given a date, it
returns which week it falls in (`"week-09"`, `"recess"`, `"reading"`,
`"exam-1"`). This names the weekly files and decides whether a run is due.

**`ingest_due(semester, today)`**, lines 91–94: your schedule rule in one line.
Run if today is in week 1–3, **or** it's the first Monday of the month
(`today.day <= 7`).

**`class_dates(semester, day_name, weeks)`**, lines 97–127: turns NUSMods'
`weeks` field into real dates. NUSMods uses two formats, and you found both by
counting before writing any code:

- **A list** `[1, 2, …, 13]` (the usual one). For each week number, take that
  week's Monday and add the weekday offset (Tuesday is +1).
- **A dict** `{"start": "2026-08-13", "end": "2026-11-19", "weeks": [1..6, 8..15]}`
  (127 classes). These count calendar weeks from `start`, so it's just
  `start + (n − 1) weeks`. Without a `weeks` list, it steps from start to end
  every `weekInterval` weeks.
- **At the end** (lines 123–127): drop dates outside the semester and dates on
  public holidays, then sort.

**For SC3210:** day `"Tuesday"`, weeks `[1..13]`. The first date is
10 Aug + 0 weeks + 1 day = **Tue 11 Aug**. Week 9 is 10 Aug + 9 weeks + 1 day =
**Tue 13 Oct**. That gives 13 dates in total; no holiday falls on a Tuesday.

---

## 4. Step 2 — Extract (calling the API): `ingest/nusmods.py`

The "NUSMods API" is just **static JSON files served over HTTPS**: no login, no
key. Calling it means doing a GET request to a URL and parsing the JSON that
comes back.

**`fetch_semester`** (lines 23–29) downloads two URLs:

```
https://api.nusmods.com/v2/2026-2027/moduleInfo.json                       → module titles, faculty, description
https://api.nusmods.com/v2/2026-2027/semesters/1/venueInformation.json     → every class, grouped by room and day
```

**`fetch_json`** (lines 11–20) is a GET with retries:

- `urllib.request.urlopen(url, timeout=60)` makes the request; it gives up if no
  answer comes within 60 s.
- `json.load(response)` turns the text into Python lists and dicts.
- If it fails (`OSError` covers network errors, timeouts and HTTP errors), it
  waits 2 s and retries, then 4 s and retries, then gives up and raises. The
  failed Lambda triggers your alarm email.

**Your design choices here:**

- **Two big files, not 6,800 small ones.** There's also a per-module endpoint
  (`modules/SC3210.json`), but you'd need about 6,800 requests.
  `venueInformation.json` already holds every class in one file. The trade-off:
  classes with no room aren't in it, and you decided you don't want those anyway.
- **`urllib` instead of a library like `requests`.** It's built into Python, so
  the Lambda package needs no extra dependencies.
- **Download everything every run.** About 20 MB a few times a month costs
  nothing, and every run rebuilds the full truth. A bad run gets fixed by the
  next good one.

**What the downloaded data looks like for SC3210:**

```python
venue_info = {
  "UTSRC-GLR": [                               # room
    { "day": "Tuesday",
      "classes": [
        { "moduleCode": "SC3210", "lessonType": "Lecture", "classNo": "1",
          "startTime": "1000", "endTime": "1200", "weeks": [1,2,...,13], "size": 40 }
      ] }
  ], ... 599 rooms ...
}
module_info = [ {"moduleCode": "SC3210", "title": "AI and Society",
                 "faculty": "Arts and Social Science", "department": "...", ...}, ... ]
```

---

## 5. Step 3 — Transform: `ingest/transform.py`

This is the heart of the pipeline. The main function is **`build_sessions`**
(lines 34–82). It works in three phases.

### Phase A — Walk every class, filter it, and expand it to dates (lines 38–63)

```python
modules = {m["moduleCode"]: m for m in module_info}      # line 38
```

- This turns the module list into a lookup table, so `modules["SC3210"]` gives
  that module's title and faculty instantly.
- Without it, the code would have to search through about 21,000 modules for
  every class.

Then three nested loops: **for each room → for each day → for each class**
(lines 44–46).

For each class, in order:

1. **Line 47, filter by type:** skip anything that isn't a `Lecture`
   (decision 2). SC3210's tutorials are dropped here.
2. **Line 49, clean the module code:** `split_module_code` (lines 23–26).
   - Some classes are shared by two modules and arrive as
     `"CE2112T/​CE2112"`; the `​` is an invisible character.
   - It strips the invisible character, splits on `/`, and keeps `CE2112T` as
     the main code with `["CE2112"]` as cross-listed.
   - For SC3210 the result is just `("SC3210", [])`.
3. **Line 50, filter by faculty:** skip NUS-ISS courses (decision 27).
4. **Line 52, expand to dates:** `class_dates(...)` from the calendar gives
   SC3210 its 13 Tuesdays.
5. **Lines 53–63, store each date once (de-duplication):**
   - Each dated occurrence becomes a **key**:
     `(module, type, classNo, date, start, room)`.
   - The rest becomes the **value**: `(end, size, crossListed)`.
   - It goes into the `slots` dictionary. A dictionary can hold each key only
     once, so duplicates collapse automatically.
   - NUSMods sometimes lists the same slot twice with different end times
     (BMI5102: 20:00 and 21:30). Line 62 keeps the larger value, which is the
     later end time, because Python compares tuples left to right.

After Phase A, SC3210 has 13 entries like:

```
("SC3210","Lecture","1", 2026-10-13, "1000", "UTSRC-GLR")  →  ("1200", 40, ())
```

### Phase B — Group by "same class, same date" and build the ID (lines 65–79, 85–95)

```python
groups[key[:4]].append(key + value)     # key[:4] = (module, type, classNo, date)
```

This collects every occurrence of one class on one date. Usually a group has
exactly one item.

The ID is built at line 71:

```
f"{module_code}-{LESSON_TYPE_CODES[lesson_type]}-{class_no}@{date}"   →  "SC3210-LEC-1@2026-10-13"
```

`LESSON_TYPE_CODES` comes from `lesson_types.py` (`"Lecture"` → `"LEC"`). You
kept it in one file so the codes are defined in exactly one place, and the
mapping is also published in `index.json` so the frontend uses the same codes.

`_session_id` (lines 85–95) handles the rare collisions you found by testing the
ID on real data:

- **Two start times on the same date** (e.g. CG2028 at 14:00 and 15:00): add
  the start time, giving `…@2026-08-11-1400`.
- **Two rooms at the same time** (e.g. ID3041 in LT424 and LT425): add the
  room, giving `…@2026-10-15-SDE3-LT424`. This was your decision 10b.
- **Otherwise:** no suffix. SC3210 stays `SC3210-LEC-1@2026-10-13`.

**Why you use an ID built from the data rather than a random one:** it's the
same every time the pipeline runs. Forum posts are stored under the session ID,
so tomorrow's run must produce the same ID for the same lecture or the posts
would be lost. A random UUID would change on every run.

### Phase C — Shape the output and sort it (lines 98–117, 81)

`_session` builds the final dictionary. Here's where each field comes from:

| Output field | Comes from |
|---|---|
| `id` | built in Phase B |
| `moduleCode`, `classNo`, `lessonType`, `size` | the venueInformation class |
| `crossListed` | `split_module_code` |
| `moduleTitle`, `faculty`, `department` | **joined** from moduleInfo via the `modules` lookup |
| `level` | `module_level` (lines 17–20): first digit of the code × 1000, so SC3210 → 3000 |
| `date` | `class_dates` |
| `startTime`, `endTime` | `hhmm` (lines 29–31): `"1000"` → `"10:00"` |
| `venue` | the room name the class was listed under |
| `building` | `venues.py` `building_for`: `"UTSRC-GLR"` → `"UTSRC"` (text before the dash); lecture theatres like `LT19` use the hand-made map |
| `online` | `venues.py` `is_online`: true if the room starts with `E-Learn` or `E-Hybrid` |

Line 81 sorts everything by date, then time, then module. Sorting makes the
output **identical every run**, which the "skip unchanged files" trick in step 4
depends on.

**`build_modules`** (lines 120–135) makes a separate list of module
descriptions, only for modules that actually have lectures. Descriptions are
long and only the recommendations feature needs them, so you kept them out of
the daily files.

**`group_by_date`** (lines 138–142) groups sessions into `{date: [sessions]}`.
Publishing uses it.

---

## 6. Step 4 — Load: `ingest/publish.py`

`publish` (lines 37–117) writes the files. Read it as six steps.

**1. Safety check first (line 49 → `_check_counts`, lines 133–140).**

- If there are 0 sessions, or fewer than half of last run's count (read from the
  existing `index.json`), raise `SuspiciousDataError` and **write nothing**.
- *Your reasoning:* the worst thing a bad run could do is wipe every lecture
  because NUSMods had a hiccup. Stopping keeps yesterday's good files online and
  sends the alarm email.

**2. Build every file in memory (lines 51–72).**

- `documents` is a dictionary of **S3 path → file content**:
  - `lectures/2026-2027/sem-1/days/2026-10-13.json`: that date's sessions, plus
    `"week": "week-09"`.
  - `lectures/2026-2027/sem-1/weeks/week-09.json`: that week's sessions
    (`_group_by_week`, lines 120–130).
  - `lectures/2026-2027/sem-1/modules.json`: the descriptions.
- *Why both day and week files:* they match the app's two views, so the browser
  downloads exactly one file per screen.

**3. Write only what changed (lines 74–79 → `_put_if_changed`, lines 148–170).**

- Compute a **fingerprint (SHA-256 hash)** of the content (lines 143–145).
- Ask S3 for the existing file's stored fingerprint with `head_object`. This
  reads only the file's metadata, not its contents.
- If they're the same, skip the upload. If they differ, or the file doesn't
  exist yet (S3 replies "404"), upload it with the new fingerprint attached as
  metadata.
- `generatedAt` is left out of the fingerprint, because it changes every run and
  would otherwise make every file look "changed".
- *Result:* a second run on the same data writes 0 files. That's
  **idempotency**: it's safe to retry or run twice.

**4. Then the index, then cleanup (lines 81–100).**

- `index.json` lists all dates and weeks and the total count. It's written
  **after** the files it points to, so the app never follows the index to a file
  that doesn't exist yet.
- `_delete_stale` (lines 182–195) lists everything in `days/` and `weeks/` and
  deletes files this run didn't produce, for example a date whose only lecture
  was cancelled.

**5. `current.json` last (lines 102–108).**

- It says "the live semester is `lectures/2026-2027/sem-1/`", so the frontend
  never has to guess which semester folder to read.

**6. Return a summary (lines 110–117).**

- Sessions, files, written, unchanged and deleted. This is what you see in the
  logs.

---

## 7. Where AWS fits: `infra/template.yaml`

This file is the code-defined description of the AWS resources that run all of
the above:

- **`IngestFunction`:** "run `handlers.ingest.handler` on Python 3.14, 1 GB
  memory, up to 5 minutes, with `WEB_BUCKET` set to our bucket".
- **`Events: EveryMonday`:** the schedule that calls it every Monday at 03:00
  Singapore time.
- **`S3CrudPolicy`:** permission to read, write and delete in that one bucket.
  It needs read because of the fingerprint check and delete because of the
  stale-file cleanup.
- **`IngestErrorsAlarm` → `AlertTopic` → email:** any error in the handler
  (download failure, suspicious data, missing calendar entry) emails you.

---

## 8. How to learn it hands-on (read-only)

**Read the files in this order:**

1. `backend/handlers/ingest.py`
2. `backend/ingest/academic_calendar.py`
3. `backend/ingest/nusmods.py`
4. `backend/ingest/transform.py`
5. `backend/ingest/publish.py`

**Run the tests and read their names.** Each one is a design rule written as
code:

```bash
cd backend
poetry run pytest tests/ingest -v
```

For example, `test_room_change_by_week_keeps_plain_id`,
`test_duplicate_slot_keeps_longer_entry` and
`test_rerun_on_same_data_writes_nothing`.

**Poke at the transform yourself, using the saved sample data.** No internet or
AWS needed:

```bash
cd backend
poetry run python -c '
import json
from ingest.academic_calendar import SEMESTERS, class_dates, teaching_week_monday
from ingest.transform import build_sessions
sem = SEMESTERS[("2026-2027", 1)]
print("week 7 Monday:", teaching_week_monday(sem, 7))
print("SC3210 dates:", class_dates(sem, "Tuesday", list(range(1, 14)))[:3], "...")
mi = json.load(open("tests/ingest/fixtures/moduleInfo.json"))
vi = json.load(open("tests/ingest/fixtures/venueInformation-sem1.json"))
s = build_sessions(mi, vi, sem)
print(len(s), "sessions"); print(json.dumps(s[0], indent=2))
'
```

---

## 9. Check yourself

Try each question before opening the answer.

<details>
<summary>1. Why does the handler convert to Singapore time before picking "today"?</summary>

Lambda's clock is UTC. The schedule fires at 03:00 Singapore time, which is
19:00 UTC the previous day, so without converting, "today" would be Sunday
instead of Monday and the due-date check and semester choice could be wrong.
</details>

<details>
<summary>2. LAJ1201 moves from LT19 to LT14 in week 7. Why does each date still show the right room?</summary>

Rooms are attached after expanding to dates. venueInformation lists LAJ1201
under LT19 with weeks 1–6 and under LT14 with weeks 7–13; each entry is expanded
to its own dates, so each date carries the room it was listed under.
</details>

<details>
<summary>3. What stops two copies of the same BMI5102 slot from both appearing?</summary>

The `slots` dictionary in `build_sessions`. Both copies have the same key
(module, type, class, date, start, room), so only one survives; line 62 keeps
the one with the later end time.
</details>

<details>
<summary>4. If you run the Lambda twice in a row, why does the second run write nothing?</summary>

`_put_if_changed` compares each file's content hash with the hash stored on the
existing S3 object. The data is the same and the output is sorted, so the hashes
match and every upload is skipped.
</details>

<details>
<summary>5. NUSMods returns half-empty data. Which line stops it, and what does the app keep showing?</summary>

`_check_counts` (called at `publish.py:49`) raises `SuspiciousDataError` before
anything is written. The Lambda fails, the alarm emails you, and the app keeps
reading the previous run's files.
</details>

<details>
<summary>6. Why is index.json written after the day files?</summary>

So the app never follows the index to a file that doesn't exist yet. If the run
fails halfway, the old index still points only at files that are there.
</details>

Once you can answer these, you can explain the whole pipeline in an interview as
your own design. `ingest-design-walkthrough.md` has the interview-style
questions.
