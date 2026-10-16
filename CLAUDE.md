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

## Not yet decided — ask before implementing
Session ID format, lecture file path, which lesson types count as lectures,
Python 3.12 vs 3.14 for Lambda, `/health` vs `/api/health`. See "Open
decisions" in `docs/ingest-pipeline-plan.md`.

## Commands
- Backend (from `backend/`, Python 3.14 + Poetry): `poetry install`,
  `poetry run pytest`, `poetry run ruff check .`, `poetry run ruff format --check .`
- Frontend (from `frontend/`, Node 24): `npm ci`, `npm run lint`,
  `npm run format:check`, `npm run build`
- Infra (from `infra/`, once it exists): `sam build && sam deploy --config-env dev`

## Reference (read when relevant)
- `docs/team-agreements-and-aws-setup.md` — IDs, JSON contracts, API, DynamoDB, auth
- `docs/infra-and-cicd-guide.md` — SAM template, OIDC bootstrap, deploy workflow
- `docs/implementation-plan.md` — workstreams, owners, week plan
- `docs/ingest-pipeline-plan.md` — NUSMods ingest design and open decisions
