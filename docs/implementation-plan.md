# Lecture Kaki Finder — implementation plan

How the work splits across people, what each person does step by step, and what blocks what.
Companion to `team-agreements-and-aws-setup.md`. Dates assume a **feature freeze on 30 Oct** and submission on **13 Nov 2026**.

## Workstreams and owners

| # | Workstream | Owner | Depends on |
|---|---|---|---|
| 0 | Data pipeline (ingest + schedule) | **unassigned** | IDs + JSON shape agreed |
| 1 | Frontend | Qf | API contract |
| 2 | Auth (Cognito) | MJ | — |
| 3 | Lecture service (search + recommendations) | jx | #0 |
| 5 | My timetable | **unassigned** | IDs, #2 |
| 6 | Forum | **unassigned** | #2, #7 (WebSocket resources) |
| 7 | Infrastructure + CI/CD | **unassigned** | — |
| 8 | Evaluation + report + slides | **unassigned** | things to measure exist |

Workstreams 0, 5, 6, 7 and 8 have nobody on them. 0 and 7 must start first; 8 must start before November.

---

## 0. Data pipeline

1. Fetch NUSMods `venueInformation.json` and `moduleInfo.json` for the semester; print the shapes before writing code against them.
2. Keep lecture-type lessons only; join each to its module title and faculty.
3. Convert week numbers (and date ranges, which some lessons use instead) into real dates, accounting for recess week.
4. Write one JSON file per day in the agreed shape to `s3://<web-bucket>/lectures/...`.
5. Skip the write when a hash of the source data is unchanged.
6. Add the EventBridge weekly schedule; confirm a scheduled run actually fires.
7. Hand the frontend one real file early, so everyone else can build against real data.

**Done when:** a full week of real lecture JSON is in S3 and re-running changes nothing.

## 1. Frontend

1. Create the React app, routing and a basic layout; pick a component approach and stick to it.
2. Build the lecture search page against a local copy of the lecture JSON — no backend needed.
3. Filters: free-now / time range, faculty, venue or building.
4. Wire login (from #2) and show signed-in state.
5. Profile and preferences page; timetable page (from #5).
6. Forum room UI: list, composer, auto-scroll, "connecting…" state.
7. Swap the local JSON for the real API, one screen at a time.
8. Mobile layout pass — the demo will be shown on a phone-sized window.

**Done when:** every screen works against the deployed dev environment.

## 2. Auth (Cognito)

1. Create the user pool and app client in `template.yaml` (not the console).
2. Write and attach the pre-sign-up Lambda that rejects non-NUS emails; test with a Gmail address.
3. Confirm the verification-code email flow end to end.
4. Add sign-up / login / logout in React; store tokens; handle refresh before expiry.
5. Attach `Authorization: Bearer <token>` to every API call from one place in the code.
6. Turn on the JWT authorizer on the API so protected routes reject unauthenticated calls.
7. Write the Lambda authorizer for the WebSocket `$connect` (token arrives in the query string) and hand it to #6.
8. Document for the team: how to get a test token, and which field is the user ID.

**Done when:** a non-NUS email cannot sign up, and a protected endpoint returns 401 without a token.

## 3. Lecture service

1. Endpoint `GET /api/lectures` reading the ingest output, with the agreed filters.
2. Decide and document where filtering happens: in the browser from the day's JSON (fast, simple) or server-side.
3. Keyword and faculty recommendations first — no ML. Ship this.
4. Record what each user opens (`VIEW#` items) to feed recommendations.
5. Then semantic recommendations: generate an embedding per module from title plus description during ingest, store the vector, and rank by cosine similarity to the user's interests.
6. Compare the two in the evaluation: do semantic suggestions actually look better to testers?

**Done when:** keyword recommendations work for a signed-in user; semantic is a bonus.

## 5. My timetable

1. Endpoints `GET` / `PUT /api/me/timetable` storing the user's classes in their profile item.
2. Manual entry UI: add a class by module, type and slot.
3. NUSMods import: paste a share link, parse the modules and class numbers out of the URL, map to our session IDs.
4. Compute free gaps for a given day from the saved timetable.
5. Feed those gaps into search: "lectures during your free time today".
6. Handle the awkward cases: no timetable saved, overlapping classes, a module the ingest doesn't know.

**Done when:** importing a real share link produces a correct timetable and correct gaps.

## 6. Forum

1. `GET` / `POST /api/sessions/{id}/posts` with TTL set on write, plus the already-expired filter on read.
2. Make it work with simple polling first — this is your fallback and your comparison baseline.
3. Request the WebSocket resources from #7: API, three routes, connections table, push permission.
4. Write `$connect` (verify token, store connection), `$disconnect` (delete row), and the broadcast path (query the room, push to each connection, delete dead ones).
5. React side: open the socket on entering a room, close on leaving, reconnect with backoff, ping every few minutes to beat the 10-minute idle timeout.
6. Keep polling behind a feature flag so the demo has a fallback.
7. Measure both modes for the evaluation: requests and messages for N tabs over 5 minutes.

**Done when:** two browsers see each other's posts within a second, and posts vanish a day later.

## 7. Infrastructure + CI/CD

1. Repo, branch rules, folder layout.
2. `template.yaml` with one FastAPI health endpoint deployed to `dev` — day one.
3. Add resources as others need them: DynamoDB tables, Cognito, S3 + CloudFront, EventBridge, WebSocket API.
4. GitHub Actions: test, `sam deploy`, build frontend, sync to S3, invalidate CloudFront.
5. Two environments (`dev` auto, `prod` manual); document how to deploy and how to roll back.
6. Budget alert, and a short runbook: where the logs are (CloudWatch), how to re-run ingest, how to tear down.

**Done when:** merging to `main` puts the change live in dev without anyone running a command.

## 8. Evaluation + report + slides

1. **System evaluation:** response times for search and posting; polling vs WebSocket request counts; a small load test; measured cost for a day of use; where it breaks as users grow.
2. **User evaluation:** 8–12 students use it during a real gap between classes, then a short questionnaire (would you use it, did you find a lecture, what confused you). Book these sessions early.
3. **Report sections:** motivation, business model, architecture (with the service-by-service justification the TA asked for), evaluation, conclusion, code explanation with the repo link, group member details.
4. **Slides + demo script**, with a recorded backup demo in case the live one fails.

**Done when:** submitted, with everyone having presented a part.

---

## Parallel-work rules

- **Nothing starts before the decision log in part 1 of the agreements doc is filled in.** One meeting, one hour.
- **Fake what you're blocked on.** Hardcode a user ID until auth lands; serve a checked-in sample JSON until ingest lands; return sample posts until the forum API lands.
- **Integrate weekly, not at the end.** Every Friday, everything merged to `main` must work together in dev.
- **One owner per AWS resource file.** Others request changes; nobody clicks in the console.

## Week plan

| Week | Everyone | Watch out for |
|---|---|---|
| 13–19 Oct | Decisions agreed; repo + CI/CD; ingest producing real JSON; Cognito pool up; frontend search page on sample data | Don't start the forum yet |
| 20–26 Oct | Search API, timetable CRUD + import, forum over REST + polling, login wired into React | Book user-testing volunteers now |
| 27–30 Oct | WebSocket upgrade, recommendations, integration, **feature freeze 30 Oct** | Anything unfinished gets cut, not extended |
| 31 Oct–6 Nov | User testing, system measurements, report draft | Measurements need a working prod |
| 7–13 Nov | Report final, slides, rehearse, present | Record a backup demo |
