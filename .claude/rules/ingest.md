---
paths:
  - "backend/handlers/ingest.py"
  - "backend/ingest/**"
  - "backend/tests/ingest/**"
---

# Ingest rules

Read `docs/ingest-pipeline-plan.md` before changing ingest code.

- Source data: NUSMods `moduleInfo.json` (titles, faculty) and
  `semesters/<n>/venueInformation.json` (timetable). Two requests per run; do
  not fetch per-module files.
- `weeks` is either a list of teaching-week numbers (needs the academic
  calendar, recess after week 6) or a dict with `start`/`end` dates and
  optional `weeks`/`weekInterval`. Handle both.
- Output is deterministic: sorted sessions, stable JSON, and an unchanged hash
  means no S3 write. Write `index.json` after the files it lists.
- The lessonType ↔ short-code mapping lives in one module and is the only
  place those codes are defined.
- Tests use trimmed real fixtures and never hit the network.
- The decisions table in the plan is the contract; change it there first.
