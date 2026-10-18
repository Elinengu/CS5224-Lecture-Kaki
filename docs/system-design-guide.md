# LectureKaki — system design guide

How to design the whole system as if you were building it yourself. Each part
lists what it does, the contract it exposes, the questions you must answer
before coding, and how you'd know it works. The questions are yours to decide;
suggestions are only starting points.

Companion docs: `team-agreements-and-aws-setup.md` (contracts),
`infra-and-cicd-guide.md` (AWS), `implementation-plan.md` (owners, weeks),
`ingest-pipeline-plan.md` (workstream 0, built).

---

## 1. How to think about it: follow the data

Every feature is data moving between a few boxes. Design the boxes by asking
what goes in, what comes out, and where it's stored.

```
                         daily
  NUSMods API ──────► Ingest Lambda ──────► S3: lectures/…json ──┐
                                                                  │ CloudFront
  Browser (React) ◄───────────────────────────────────────────────┘
     │   ▲
     │   └── sign in ──► Cognito (NUS email only) ── ID token (JWT)
     │
     ├── REST + token ──► API Gateway (HTTP) ──► FastAPI Lambda ──► DynamoDB main table
     │                                                               (profiles, timetables,
     │                                                                posts, views)
     └── WebSocket ─────► API Gateway (WS) ──► connect / disconnect / send Lambdas
                                                    └──► DynamoDB connections table
```

Four kinds of data, each with one owner:

| Data | Changes | Stored in | Written by | Read by |
|---|---|---|---|---|
| Lecture sessions | daily | S3 JSON | ingest | browser, API |
| User profile + timetable | when the user edits | DynamoDB `USER#<sub>` | API | API |
| Forum posts | constantly, expire in 24 h | DynamoDB `ROOM#<sessionId>` | API | API, WebSocket |
| Live connections | per browser tab | connections table | WS Lambdas | WS Lambdas |

If a feature needs data that isn't in this table, that's a design decision to
make before coding (see §4.3 for one that already exists).

---

## 2. Design checklist for any component

Answer these in a few lines each before writing code. They're also most of
your report's architecture section.

1. **Purpose:** one sentence on what it does for the user.
2. **Contract:** inputs and outputs, written down (JSON shapes, URLs, status codes).
3. **Data:** what it stores, the key it's looked up by, how long it lives.
4. **Who calls it, and how often:** that decides Lambda vs static file, and the cost.
5. **Auth:** who is allowed, and where identity comes from.
6. **Failure:** what happens when a dependency is down or the input is bad.
7. **Test:** the one test proving it works, and the one proving it fails safely.
8. **Measure:** the number you'll report in the evaluation.

---

## 3. Components

### 3.1 Data pipeline (workstream 0) — built

Done: see `ingest-pipeline-plan.md`. Still to decide: the five defaults listed
there. Still to build: its AWS resources (§3.2).

### 3.2 Infrastructure + CI/CD (workstream 7) — nothing built yet

**Purpose:** every AWS resource comes from `infra/template.yaml`; merging to
`main` deploys dev.

**Decide:**
- **Real AWS account or AWS Academy Learner Lab?** This changes a lot: Learner
  Lab can't create IAM roles (use `LabRole`), can't do GitHub OIDC, and its
  credentials expire. Find out first.
- **One bucket or two for the website and lecture data?** Watch out: the
  guide's deploy step runs `aws s3 sync frontend/dist s3://<bucket> --delete`,
  which **deletes everything not in `dist/`, including `lectures/`**. Either
  use a separate data bucket behind the same CloudFront distribution
  (`/lectures/*` → data bucket), or add `--exclude "lectures/*"`.
  *Suggestion: two buckets, one distribution.*
- **Cache lifetimes:** lecture JSON changes at most daily; the site's
  `index.html` changes every deploy. *Suggestion: 5 minutes for JSON, no-cache
  for `index.html`, long for hashed assets.*
- **CORS:** if the site and API are on different domains, the API must allow
  the CloudFront origin. Alternatively route `/api/*` through CloudFront too,
  so it's same-origin and CORS disappears.
- **Alerts:** where ingest failures go (an SNS email topic).

**Build order:** health endpoint on Lambda → bucket + CloudFront serving the
React build → ingest function + schedule → DynamoDB → Cognito → WebSocket.
Deploy after each step.

**Measure:** time from merge to live; monthly cost (Cost Explorer).

### 3.3 Auth (workstream 2)

**Purpose:** only NUS students can sign in; every API call knows who they are.

**Contract:** the frontend gets an ID token from Cognito and sends
`Authorization: Bearer <token>`. API Gateway rejects bad tokens before
FastAPI runs. FastAPI reads `sub` from the request context.

**Decide:**
- **Which emails count:** `@u.nus.edu` only, or also `@nus.edu.sg` (staff)?
- **When the profile item is created:** a Cognito post-confirmation trigger,
  or lazily on the first `GET /api/me`? *Suggestion: lazily; one fewer Lambda.*
- **What other users see:** a display name, or anonymous? It drives whether
  you store a name at all (privacy and PDPA in the report).
- **Token storage and refresh:** the Amplify Auth library handles both, or
  write it by hand with `amazon-cognito-identity-js`. *Suggestion: Amplify Auth
  only, not the whole Amplify framework.*
- **WebSocket auth:** a token in the connect URL, checked by a Lambda
  authorizer.

**Test:** a Gmail signup is rejected; a protected route without a token
returns 401.

### 3.4 Lecture browsing and search (workstreams 1 + 3)

**Purpose:** "what lectures can I walk into today, now, or this week?"

**Already decided:** browsing reads `lectures/current.json` →
`index.json` → `days/<date>.json` straight from CloudFront; no Lambda involved.

**Decide:**
- **Where filtering happens.** A day file is about 140 KB raw (~15 KB
  compressed), so filtering by faculty, time, building or level in the browser
  is instant. *Suggestion: in the browser, so `GET /api/lectures` may not be
  needed at all; drop it from the contract or keep it as a thin server-side
  copy for the report's comparison.*
- **What "free now" means:** starting in the next N minutes, or already running?
- **Which filters ship by 30 Oct:** e.g. date, time range, faculty, level,
  building, hide online.
- **The session page:** what it shows (details, map link?, forum) and its URL
  (`/sessions/<id>`).

**Measure:** time to first result on a phone; bytes downloaded per page view.

### 3.5 My timetable (workstream 5)

**Purpose:** know when the user is busy, so the app can suggest lectures in
their gaps.

**Contract:** `GET/PUT /api/me/timetable`, `POST /api/timetable/import`.

**The gap you must design around:** the ingest publishes **lectures only**. To
know when a user is busy, you also need their tutorial and lab times, and
those aren't in our files. Options:
- (a) At import, the API fetches `modules/<code>.json` from NUSMods for the
  user's modules and stores the resolved slots (day, start, end, weeks) in the
  profile. *Suggestion.*
- (b) The ingest also publishes every lesson type per module.
- (c) The user types their busy times in by hand.

**Decide:**
- **What to store:** the raw NUSMods choices (`CS2103T: LEC G01, TUT 05`) or
  resolved time slots, or both. Resolved slots make gap computation trivial.
  Keep the raw choices too, so the import can be re-run.
- **The NUSMods share-link format:** check against a real link; it looks like
  `nusmods.com/timetable/sem-1/share?CS2103T=LEC:G01,TUT:05`.
- **What a "gap" is:** minimum length (e.g. at least 60 minutes)? Travel time?
  Only between 08:00 and 22:00?
- **Edge cases:** no timetable saved; clashing classes; a module that isn't in
  NUSMods; the semester changing.

**Test:** import a real share link → correct classes → correct gaps for a known day.

### 3.6 Recommendations (workstream 3)

**Purpose:** a short list of sessions this user might like, preferably in
their free time.

**Contract:** `GET /api/recommendations?date=` → `{"items": [{session, score, reason}]}`.

**Decide (keyword version first):**
- **Inputs:** preferred faculties, keywords, modules already taken (to
  exclude), free gaps, view history.
- **A scoring formula you can explain in one line**, e.g. +3 for a matching
  faculty, +2 per matching keyword in title or description, +2 if it fits a
  gap, −∞ if it clashes or it's the user's own module.
- **Showing why:** "matches 'AI', fits your 2–4 pm gap". It makes the
  evaluation easier.
- **Semantic version (bonus):** where embeddings come from (Amazon Bedrock?),
  when they're computed (in ingest, once per module, from `modules.json`), and
  where vectors live (a small file in S3 is enough for about 4k modules).

**Measure:** tester ratings of keyword vs semantic suggestions.

### 3.7 Forum and companions (workstream 6)

**Purpose:** the core idea: find someone to attend with.

**Contract:** `GET/POST /api/sessions/{sessionId}/posts`; WebSocket pushes new posts.

**Decide:**
- **Is "finding a companion" only the forum, or also an "I'm going" button**
  with a count or list on each session? A going list is simpler for users than
  reading posts, and costs one more item type:
  `pk=ROOM#<sessionId>`, `sk=GOING#<sub>`, with `ttl`.
- **Who can read and post:** read public, post signed-in (as agreed)?
- **Post rules:** maximum length, rate limit (e.g. 5 per minute), delete own
  post, report button?
- **When a room opens and closes:** only on the session's date? Posts expire
  24 hours after creation, so a room for a Tuesday lecture opened on Monday
  still shows Monday's posts.
- **Reading:** newest N posts, and filter `ttl > now` because DynamoDB deletes
  late.
- **Real time:** polling first (every 5–10 s), then WebSocket. Keep polling as
  the fallback.

**Measure:** request counts for polling vs WebSocket with N tabs over 5
minutes; time for a post to reach another browser.

### 3.8 Frontend (workstream 1)

**Decide:**
- **Pages and routes:**
  - `/` today
  - `/sessions/:id`
  - `/me` (profile, preferences, timetable)
  - `/login`
- **Data fetching:** plain `fetch` + React state, or a cache library (TanStack
  Query). *Suggestion: TanStack Query; it does caching and polling for free,
  which the forum fallback needs.*
- **Where config comes from:** `VITE_*` variables from stack outputs (as agreed).
- **Mobile first:** the demo is phone-sized.
- **Display labels:** faculty names and lesson types.

---

## 4. Cross-cutting decisions

1. **Identity everywhere:** session ID (decided), user = Cognito `sub`,
   module = NUSMods code.
2. **Time:** all user-facing dates and times are Singapore local; stored
   timestamps are UTC. Decide one helper on each side (Python and TypeScript),
   so nobody does timezone maths by hand.
3. **Missing data** (decide this explicitly):
   - Tutorials and labs for gap computation (§3.5).
   - Display names for posts (§3.3).
   - A "going" list (§3.7).
4. **Errors:** `{"error": {"code", "message"}}` everywhere; the frontend shows
   `message`.
5. **Security:**
   - Never trust IDs from request bodies.
   - Validate lengths.
   - Rate-limit posting.
   - Keep the console read-only.
6. **Cost:** everything is on-demand. Name the 2–3 things that grow with
   users (API calls, WebSocket messages, DynamoDB writes) and estimate them for
   the report.
7. **Observability:** structured JSON logs from every Lambda, and one alarm
   (ingest failure).

---

## 5. Order of work (today 18 Oct → freeze 30 Oct)

Build thin vertical slices: each one works end to end before the next starts.

| Days | Slice | Done when |
|---|---|---|
| 18–20 Oct | Infra skeleton: health Lambda, bucket + CloudFront, ingest deployed and scheduled | real lecture JSON at a CloudFront URL |
| 19–22 Oct | Browse: today's lectures with filters, from CloudFront | works on a phone against dev |
| 20–23 Oct | Auth: sign up / in, protected `/api/me` | Gmail rejected, 401 without a token |
| 22–25 Oct | Timetable: import link → slots → gaps | correct gaps for a real link |
| 22–26 Oct | Forum v1: REST + polling (+ "going"?) | two browsers see each other's posts |
| 25–28 Oct | Recommendations (keyword) | sensible list with reasons |
| 27–30 Oct | WebSocket upgrade, polish, prod deploy | feature freeze |

Book user testers now; the evaluation needs prod working by about 31 Oct.

---

## 6. Decisions needed next (in the order they block work)

1. Real AWS account or Learner Lab? (blocks all infra)
2. One or two buckets, given the `s3 sync --delete` problem (§3.2)
3. Browser-side filtering, and whether `/api/lectures` stays (§3.4)
4. How busy times are known: tutorials and labs (§3.5 a/b/c)
5. Companion feature: forum only, or forum plus "I'm going" (§3.7)
6. Display names or anonymous (§3.3)
7. Recommendation scoring formula (§3.6)
8. The five ingest defaults in `ingest-pipeline-plan.md`
