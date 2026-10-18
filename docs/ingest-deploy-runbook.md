# Deploying and testing the ingest on AWS

Step-by-step: deploy the ingest Lambda to `dev`, check it works, and know where to
look when it doesn't. Resources are in `infra/template.yaml`; nothing is created
in the console. Commands assume macOS/Linux and region `ap-southeast-1`.

## What gets created

| Resource | Why |
|---|---|
| `WebBucket` (`lecturekaki-dev-web-<accountId>`) | Holds the site and `lectures/…json`. Private; CloudFront comes later. |
| `IngestFunction` | Python 3.14, 1 GB, 5 min timeout, `handlers.ingest.handler`. |
| IAM role (made by SAM) | `S3CrudPolicy` on the web bucket only: read (for the unchanged-file check), write, delete. |
| EventBridge Scheduler schedule | Every Monday 03:00 Singapore time. The code decides if the run is due. |
| Log group | `/aws/lambda/<function>`, kept 30 days. |
| SNS topic + email subscription | Where alerts go. |
| CloudWatch alarm | Fires when the function errors at least once in 5 minutes. |

Cost: a few seconds of Lambda a week and ~100 small S3 writes per real run — well
inside the free tier.

---

## 1. One-time setup on your laptop

```bash
brew install awscli aws-sam-cli       # or the AWS installers for Windows/Linux
aws configure                         # your IAM user's access key; region ap-southeast-1; output json
aws sts get-caller-identity           # prints the account and your user -> credentials work
sam --version                         # must support python3.14; tested with 1.169
```

Your IAM user needs permission to create CloudFormation stacks, Lambda, S3,
IAM roles (SAM creates one per function and one for the schedule), EventBridge
Scheduler, SNS, CloudWatch and Logs. `PowerUserAccess` plus the IAM role actions
in `infra-and-cicd-guide.md` §4 covers it.

**Set the budget alert first** if nobody has (team agreements §2.1).

---

## 2. Check and build locally

From the repo root:

```bash
cd backend && poetry run pytest && cd ..    # 51 tests, no AWS needed
cd infra
sam validate --lint                         # "is a valid SAM Template"
sam build                                   # packages ../backend into .aws-sam/
```

`sam build` says "requirements.txt file not found … continuing without
dependencies". That's expected: the ingest only uses the standard library and
`boto3`, which the Lambda runtime already has. (The API function will need a
`backend/requirements.txt` exported from Poetry when it's added.)

---

## 3. Deploy to dev

```bash
sam deploy --config-env dev --parameter-overrides Env=dev AlertEmail=you@u.nus.edu
```

- It shows a **changeset** (what will be created) and asks to confirm. Read it:
  first time, everything is `Add`. Later, a `Remove` or `Replace` on the bucket
  deserves a pause.
- Takes 1–3 minutes. On failure CloudFormation rolls back by itself; the error
  is in the output (or console → CloudFormation → stack → Events, read-only).
- **Confirm the SNS email** ("AWS Notification - Subscription Confirmation").
  Until you click it, alerts go nowhere.

Save the outputs into shell variables for the next steps:

```bash
STACK=lecturekaki-dev
out() { aws cloudformation describe-stacks --stack-name $STACK \
        --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
FN=$(out IngestFunctionName); BUCKET=$(out WebBucketName)
echo $FN $BUCKET
```

---

## 4. Test 1 — manual run writes the data

```bash
aws lambda invoke --function-name $FN \
  --cli-binary-format raw-in-base64-out \
  --payload '{"date": "2026-10-19"}' out.json && cat out.json
```

Expected (numbers change as NUSMods updates):

```json
{"semester": "2026-2027/sem-1", "sessions": 25220, "files": 99, "written": 100, "unchanged": 0, "deleted": 0}
```

If the command prints `"FunctionError": "Unhandled"`, `out.json` holds the
error; see the logs (step 9).

## 5. Test 2 — the files are right

```bash
P=s3://$BUCKET/lectures/2026-2027/sem-1
aws s3 ls $P/days/ | wc -l                                   # ~83 day files
aws s3 ls $P/weeks/                                          # 15 files: week-01 … week-13, recess, reading
aws s3 cp s3://$BUCKET/lectures/current.json -               # {"acadYear": "2026-2027", "semester": 1, "path": ...}
```

Spot-check facts you can verify against NUSMods by hand:

```bash
# SC3210 lecture on Tue 13 Oct: 10:00-12:00 at UTSRC-GLR
aws s3 cp $P/days/2026-10-13.json - | python3 -c '
import json,sys; d=json.load(sys.stdin)
print(d["week"], [s for s in d["sessions"] if s["moduleCode"]=="SC3210"])'

# Deepavali (observed) Mon 9 Nov: no lectures that day
aws s3 cp $P/index.json - | python3 -c '
import json,sys; d=json.load(sys.stdin)
print(d["sessionCount"], "2026-11-09" in d["days"], d["lessonTypes"])'
```

Expect `week-09` with one SC3210 session, then a count, `False`, and
`{"Lecture": "LEC"}`.

## 6. Test 3 — running again changes nothing (idempotency)

Run step 4 again. Expect `"written": 0, "unchanged": 100`. Then:

```bash
aws s3api head-object --bucket $BUCKET --key lectures/2026-2027/sem-1/index.json \
  --query 'Metadata'                       # {"content-sha256": "..."}
```

## 7. Test 4 — a scheduled run that isn't due skips

```bash
aws lambda invoke --function-name $FN \
  --cli-binary-format raw-in-base64-out --payload '{}' out.json && cat out.json
```

Unless today is a Monday in weeks 1–3 or the first Monday of a month:
`{"semester": "2026-2027/sem-1", "skipped": "not due on <today>"}`. Nothing is
downloaded or written.

Check the schedule exists and points at the function:

```bash
aws scheduler list-schedules --query 'Schedules[].Name'
aws scheduler get-schedule --name <name from above> \
  --query '{cron: ScheduleExpression, tz: ScheduleExpressionTimezone, target: Target.Arn}'
```

The real proof is the next Monday after 03:00 SGT: the logs (step 9) show a
`skipped` line, or — on Mon 2 Nov 2026, the first Monday of November — a full
run.

## 8. Test 5 — failures alert you

Make it fail safely, with a date that has no calendar entry (it fails before
downloading or writing anything):

```bash
aws lambda invoke --function-name $FN \
  --cli-binary-format raw-in-base64-out \
  --payload '{"date": "2028-09-01"}' out.json; cat out.json      # KeyError: No calendar entry …
```

Within about 5 minutes the alarm goes to `ALARM` and you get an email:

```bash
aws cloudwatch describe-alarms --alarm-names lecturekaki-dev-ingest-errors \
  --query 'MetricAlarms[0].StateValue'
```

It returns to `OK` by itself after a quiet 5 minutes. The files from step 4 are
untouched — check `sessionCount` in `index.json` again.

(The circuit breaker — refusing to publish when sessions fall below half the last
run — is covered by unit tests; there's no safe way to make NUSMods send bad
data on demand.)

## 9. Logs

```bash
sam logs -n IngestFunction --stack-name $STACK --tail      # live
sam logs -n IngestFunction --stack-name $STACK -s '1day ago'
```

Each run logs one JSON line with the result: counts, or `skipped`. Duration and
memory used are in the `REPORT` line — expect a few seconds and well under 1 GB.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `Runtime python3.14 not supported` in build/deploy | Old SAM CLI — upgrade. |
| `AccessDenied` creating the stack | Your IAM user lacks a permission; the message names the action. |
| `... already exists` on the bucket | A bucket with that name exists outside the stack. Don't delete blindly; rename or ask who made it. |
| `Task timed out after 300 seconds` | NUSMods slow or down. The next run retries; nothing was written. |
| `AccessDenied` on `HeadObject`/`PutObject` | Policy not applied — check the stack deployed the latest template. |
| `SuspiciousDataError` | Sessions dropped by over half. Look at NUSMods before forcing anything; yesterday's files are still served. |
| `KeyError: No calendar entry` | New semester: add it to `backend/ingest/academic_calendar.py`. |
| No alarm email | SNS subscription not confirmed. |

## Tear down

```bash
aws s3 rm s3://$BUCKET --recursive        # the stack can't delete a non-empty bucket
sam delete --config-env dev
```

## What's next

CloudFront in front of the bucket (so the browser can read `lectures/…`), then
the API function and the GitHub Actions deploy in `infra-and-cicd-guide.md`.
