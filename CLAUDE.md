# LectureKaki (Lecture Kaki Finder)

CS5224 group project: help NUS students find lectures outside their modules and
companions to attend with. React + FastAPI on AWS (Lambda, API Gateway,
DynamoDB, S3 + CloudFront, Cognito, EventBridge), deployed with SAM in
`ap-southeast-1`. Feature freeze 30 Oct 2026; submission 13 Nov 2026.

## Conventions
- Never create or change AWS resources in the console — everything goes in
  `infra/template.yaml`. The console is read-only.
- No credentials, account IDs or console URLs in the repo.
- Dates are Singapore local (`Asia/Singapore`); DynamoDB timestamps are UTC
  ISO-8601; times in lecture JSON are 24-hour `HH:MM`.
- DynamoDB: single main table with `pk`/`sk`; TTL attribute `ttl` holds Unix
  epoch **seconds**. New item types must be added to the table in
  `docs/team-agreements-and-aws-setup.md` §1.4.
- JSON fields are camelCase; Python is snake_case. Lists are `{"items": [...]}`;
  errors are `{"error": {"code": ..., "message": ...}}`.
- User identity is the Cognito `sub` from the verified token, never from a
  request body.
- Lesson types: NUSMods values, shortened in IDs (`LEC`, `TUT`, …) via one
  shared mapping.
- Branch from `main`, open a PR; nobody pushes to `main` directly.

## Lecture data (decided; details in `docs/ingest-pipeline-plan.md`)
- Session ID: `<module>-<code>-<classNo>@<YYYY-MM-DD>`, e.g. `SC3210-LEC-1@2026-10-13`;
  a room or start-time suffix is added only when a class has two sessions that date
- Files: `lectures/<acadYear>/sem-<n>/days/<date>.json`, `weeks/<label>.json`,
  `index.json`, `modules.json`; `lectures/current.json` names the semester served
- Only NUSMods `Lecture` lessons; Python 3.14 on Lambda; health check is `/api/health`
  (the app still serves `/health`; not yet moved)
- Design choices belong to the team: propose options, don't decide them in code

## Commands
- Backend (from `backend/`, Python 3.14 + Poetry): `poetry install`,
  `poetry run pytest`, `poetry run ruff check .`, `poetry run ruff format --check .`
- Frontend (from `frontend/`, Node 24): `npm ci`, `npm run lint`,
  `npm run format:check`, `npm run build`
- Infra (from `infra/`): `sam validate --lint`, `sam build`,
  `sam deploy --config-env dev --parameter-overrides Env=dev AlertEmail=<email>`

## Reference (read when relevant)
- `docs/team-agreements-and-aws-setup.md` — IDs, JSON contracts, API, DynamoDB, auth
- `docs/infra-and-cicd-guide.md` — SAM template, OIDC bootstrap, deploy workflow
- `docs/implementation-plan.md` — workstreams, owners, week plan
- `docs/ingest-pipeline-plan.md` — NUSMods ingest design and decisions
- `docs/ingest-design-walkthrough.md` — how to design the ingest from scratch; interview prep
- `docs/ingest-deploy-runbook.md` — deploy the ingest to AWS and test it
- `docs/system-design-guide.md` — whole-system design questions and build order
