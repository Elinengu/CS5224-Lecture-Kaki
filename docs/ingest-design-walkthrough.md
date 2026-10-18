# Designing the ingest pipeline yourself — a walkthrough

How you would plan this pipeline with no AI help, in the order you'd think about
it. Each step gives the question to ask, how to answer it, what we found for
LectureKaki, the alternatives, and how to say it in an interview.

The finished design is in `ingest-pipeline-plan.md`; the code is in
`backend/ingest/`. Try answering each **Your turn** before reading on.

---

## The shape of every ingestion pipeline

```
 source ──► EXTRACT ──► TRANSFORM ──► VALIDATE ──► LOAD ──► consumers
              │            │             │           │
          how, how      clean, join,   is it      where, in what
          often, what   expand, key    sane?      order, idempotent?
          if it fails
```

Wrapped around it: **orchestration** (when it runs), **observability** (how you
know it worked), and **testing**. Every design question below fits one of these
boxes. In an interview, draw this first, then fill in each box.

---

## Step 0 — Requirements: who reads the data, and what do they need?

Start at the consumer, not the source.

| Question | LectureKaki answer |
|---|---|
| Who reads it? | The React app (browse by day/week), the lecture API (search), recommendations (module descriptions). |
| Read pattern? | "Lectures on this date", "lectures this week". Almost never "one lecture by ID". |
| How fresh? | Timetables change a few times a semester. A day old is fine. |
| How much? | ~2,200 weekly lecture slots → ~25,000 dated sessions per semester. |
| How correct? | Wrong room or a cancelled lecture shown = a student walks to an empty hall. Correctness beats freshness. |

**Why it matters:** the read pattern decides the storage layout (step 4) and
freshness decides batch vs streaming (step 6). Small data + daily freshness
means a simple batch job — no Kafka, no database needed.

**Your turn:** if students wanted live "lecture cancelled" alerts, what changes?
*(Freshness becomes minutes → you'd need a push source or frequent polling, and
a notification path. NUSMods doesn't offer that, so it's out of scope.)*

---

## Step 1 — Profile the source before writing code

The most skipped step and the one that saves the most time. Download the real
data and **count things**.

What to do:

1. List the endpoints. NUSMods has `moduleList`, `moduleInfo`, per-module
   files, and per-semester `venueInformation`.
2. Download each, check size, print one record.
3. For every field you'll use, count distinct values and shapes:
   - `lessonType` values → found 12 types; `Lecture` is 2,235 of them.
   - `weeks` → 9,335 lists and 127 dicts. **Two formats** — you'd have missed
     the dict form if you'd only looked at one record.
   - `moduleCode` → 89 codes like `CE2112T/​CE2112` (cross-listed, with a
     hidden zero-width space).
4. Test your intended key for uniqueness. `module-type-class@date` collided for
   classes meeting twice a day and for one lecture in two rooms.
5. Check coverage: 4,239 modules offered in Sem 1, only 2,524 in the venue file.

**Interview line:** "Before designing I profiled the source: counted value
distributions, checked every shape a field can take, and tested my key for
uniqueness on real data. That found two week formats, cross-listed codes,
duplicate rows and key collisions — all before writing pipeline code."

**Your turn:** what's the cheapest check that would have caught the key
collision? *(Group by the proposed key and count rows with n > 1.)*

---

## Step 2 — Extract: how do you get the data?

| Decision | Options | We chose | Why |
|---|---|---|---|
| Which endpoint | 6,800 per-module files vs 2 bulk files | 2 bulk files | 3,400× fewer requests, 5 s run, no rate-limit risk. Cost: classes without a room are missing — acceptable, you can't walk into them. |
| Full or incremental | Re-download everything vs only what changed | Full | 20 MB a day is nothing. Incremental (ETags, `If-Modified-Since`, change feeds) is worth it only when full loads are expensive. |
| Pull or push | We call them vs they notify us | Pull on a schedule | NUSMods has no webhooks. |
| Failure | Fail, retry, fall back | 3 attempts, 2 s / 4 s backoff, 60 s timeout | Transient network errors are common; a real outage should fail loudly. |

**Interview line:** "Full refresh is simplest and self-healing — every run
rebuilds the truth from the source, so a bad run is fixed by the next good one.
I'd switch to incremental only when volume made full loads slow or costly."

**Your turn:** at 1,000× the data, what changes? *(Fan out: a queue of
per-module jobs processed in parallel — SQS + Lambda or Step Functions Map — and
incremental fetches.)*

---

## Step 3 — Transform: turn source rows into your model

Break it into small named operations. Each one is a pure function you can test
alone (`ingest/transform.py`, `ingest/academic_calendar.py`).

| Operation | Example | Design question |
|---|---|---|
| **Filter** | Keep `Lecture`; drop NUS-ISS | Business rule — who decides? (the team) |
| **Normalise** | `"1000"` → `"10:00"`; strip zero-width space | One canonical format per field |
| **Enrich / join** | Add title, faculty from moduleInfo | What if the join misses? (field becomes null; tests check it doesn't happen) |
| **Expand** | Week numbers → real dates | Needs reference data: the academic calendar and holidays |
| **De-duplicate** | Same slot twice with different end times → keep the longer | What's "the same"? Define the key first |
| **Key** | `SC3210-LEC-1@2026-10-13` | Natural key (built from data) vs surrogate (random ID) |

**Key design is the big one.** We used a *natural key*: anyone can rebuild it
from the data, it's readable, and it's stable across runs — so forum posts
attached to a session still match tomorrow. A random UUID would change every
run and break those links. The trade-off: natural keys collide when your
assumption about uniqueness is wrong, hence the `-1400` / `-SDE3-LT424`
suffixes only where needed.

**Reference data** (calendar, holidays, building map) is hand-maintained and
versioned in code. That's a deliberate choice: 3 dates a semester don't justify
a scraper, but it's an operational task someone must remember — so a missing
semester fails loudly instead of guessing.

**Interview line:** "I kept transforms pure — data in, data out, no I/O — so
they're unit-tested on trimmed real fixtures in milliseconds. I/O lives only at
the edges: fetch at the start, publish at the end."

**Your turn:** a lecture moves room from week 7. If you attach the room per
weekly slot instead of per date, what breaks? *(Weeks 7–13 show the old room.
Expand to dates first, then attach the room.)*

---

## Step 4 — The output contract and storage

Design from the read pattern in step 0.

| Decision | Options | We chose | Why |
|---|---|---|---|
| Store | DynamoDB / RDS / static files on S3 | S3 JSON behind CloudFront | Read-only, whole-day reads, same data for every user → a static file is the cheapest and fastest thing possible. No database to run. |
| Partitioning | One big file / per day / per week | Per day **and** per week | Matches the two screens. Duplicated data, but it's 2 MB — storage is cheap, extra requests aren't. |
| Shape | Normalised (session points to module) / denormalised (title copied in) | Denormalised | The browser renders one file with no extra lookups. Descriptions are big and rarely needed, so they're split into `modules.json`. |
| Discovery | Client guesses file names / index file | `index.json` + `current.json` | The app learns which dates and semester exist instead of guessing and hitting 404s. |

**Interview line:** "Lecture data is read-heavy, identical for every user and
changes daily, so I precomputed it into static files partitioned by the
access pattern and served them from a CDN. The API only handles per-user
data."

**Your turn:** when would you move this into DynamoDB? *(When reads become
per-user or query-shaped — e.g. "lectures matching my free slots" across
weeks — or when you need to update single sessions often.)*

---

## Step 5 — Load: write safely

Three properties to get right:

1. **Idempotent.** Running twice gives the same result. We hash each file's
   content (excluding `generatedAt`), store the hash as S3 metadata, and skip
   writes when it's unchanged. Retries are safe, and a second run writes 0 files.
2. **Ordered.** Write the files first, then `index.json` that lists them, then
   delete old ones. A reader never follows the index to a file that isn't there.
3. **Reconciled.** A cancelled lecture's date file must disappear, so after
   writing, list what's in S3 and delete what the new run didn't produce.

**Known gap (good interview material):** this isn't a fully atomic snapshot.
Mid-run, a reader could see a new day file with an old index. The standard fix
is **write-then-swap**: write the whole run under `lectures/runs/<runId>/`,
then flip one pointer (`current.json`) to it. Readers see either all-old or
all-new. We already have the pointer, so it's a small change if needed.

**Your turn:** Lambda retries a failed async run twice. Is that safe here?
*(Yes — writes are idempotent and the run is a full rebuild.)*

---

## Step 6 — Orchestration: when and where it runs

| Decision | We chose | Alternatives |
|---|---|---|
| Trigger | EventBridge schedule, daily 03:00 SGT | Weekly (misses early-semester changes); on demand only |
| Compute | One Lambda, 1024 MB, 300 s timeout | ECS/Fargate task (for runs > 15 min), Step Functions (multi-step with retries per step), Airflow (many pipelines with dependencies) |
| Which semester | Derived from today's date; override with `{"date": ...}` | Config variable changed by hand each semester |
| Backfill / re-run | Invoke with a date | — |

**Interview line:** "The run is 5 seconds and stateless, so a scheduled Lambda
is enough. I'd move to Step Functions if it grew into several steps that need
their own retries, or Fargate if it outgrew Lambda's 15-minute limit."

---

## Step 7 — Data quality and failure

Ask: *what's the worst thing a bad run can do?* Here: wipe every lecture
because NUSMods returned an empty or half-empty file.

Defences, from cheapest to richest:

| Layer | What we do |
|---|---|
| Fail on transport errors | Retries, then the Lambda errors — nothing written |
| **Circuit breaker** | Zero sessions, or fewer than 50% of the last run → abort, keep yesterday's files |
| Last-known-good | Old files stay until a good run replaces them |
| Alerting | Lambda `Errors` alarm → email (to build in infra) |
| Logs | Each run logs sessions in, files written/unchanged/deleted |

Not done yet, worth mentioning: schema checks on the source (fail if a field
disappears), CloudWatch custom metrics for counts over time, and a
`schemaVersion` field in the output so consumers can detect breaking changes.

**Interview line:** "Pipelines fail silently more often than loudly. I added a
volume check against the previous run so a bad upstream file can't wipe
production data — the job fails, alerts, and users keep yesterday's data."

---

## Step 8 — Testing

| Level | What | Where |
|---|---|---|
| Unit | Calendar maths, filters, keys, de-dup — each edge case found in profiling | `tests/ingest/test_ingest_calendar.py`, `test_ingest_transform.py` |
| Fixtures | Trimmed **real** NUSMods records (SC3210, LAJ1201, ID3041, BMI5102…), not invented ones | `tests/ingest/fixtures/` |
| Integration | Full publish against a fake S3 (moto): first run, re-run writes nothing, deletion, circuit breaker | `test_ingest_publish.py` |
| Real-data dry run | Whole pipeline on live NUSMods with fake S3; check counts and file sizes | done manually (25,220 sessions, 5 s) |

Each bug found in profiling became a test. That's the habit to describe.

---

## Step 9 — Operations and change over time

- **New semester / year:** add calendar dates and holidays. Missing entry → loud failure.
- **Source schema change:** tests on fixtures won't catch it; the volume check
  and a schema check on live data would.
- **Output schema change:** adding fields is safe; renaming or removing breaks
  the frontend — coordinate, or version the files.
- **Cost:** one 5 s Lambda a day and ~100 small S3 writes at most — effectively free.

---

## Interview practice

Answer out loud in 1–2 minutes each, then compare with the steps above.

1. Walk me through your data pipeline. *(Draw the shape; one line per box.)*
2. Why batch and not streaming? *(Step 0 freshness, step 6.)*
3. Why S3 files instead of a database? *(Step 4.)*
4. How did you choose the key, and what went wrong with the first one? *(Steps 1, 3.)*
5. What happens if the job fails halfway? Runs twice? *(Step 5.)*
6. What if NUSMods sends bad data? *(Step 7.)*
7. How do you know the output is correct? *(Steps 1, 8.)*
8. How would it scale to every university in Singapore? *(Step 2 fan-out,
   partition by source, incremental loads, per-source circuit breakers.)*
9. What would you improve with more time? *(Atomic snapshots, schema checks,
   metrics, schema version, automated calendar.)*
10. What trade-off are you least sure about? *(Have a real answer, e.g.
    skipping venue-less classes, or hand-maintained holidays.)*

---

## One-page design doc template

Use this for the next pipeline you design.

```
Purpose         one sentence, from the user's point of view
Consumers       who reads it, read pattern, freshness needed
Source          endpoints, size, shapes, edge cases found by profiling
Extract         full / incremental, pull / push, retries, rate limits
Transform       filter, normalise, enrich, expand, de-dup, key
Output          storage, partitioning, shape, discovery (index)
Load            idempotency, write order, deletions
Orchestration   trigger, compute, backfill
Quality         validation, circuit breaker, alerting, last-known-good
Tests           unit, fixtures, integration, real-data run
Open questions  decisions someone else must make
```
