# Lecture Kaki Finder — team agreements & AWS setup

CS5224 group project. Two parts:

- **Part 1 — decisions to lock in** before anyone writes real code. Each has a proposed default so the meeting is "agree or change", not "design from scratch".
- **Part 2 — AWS from zero**, assuming nobody has used AWS before.

Final report, slides and presentation are due **13 Nov 2026**. Aim to freeze features by **~30 Oct** so there is time for evaluation and writing.

---

# Part 1 — Decisions to lock in

## 1.1 Identifiers

Everything else keys off this. Get it wrong and the forum, recommendations and timetable silently fail to line up.

**Proposed:**

| Thing | Format | Example |
|---|---|---|
| Module | module code as NUSMods spells it | `CS2040` |
| Class | `<module>-<lessonType>-<classNo>` | `CS2040-LEC-1` |
| Session (one occurrence) | `<class>@<YYYY-MM-DD>` | `CS2040-LEC-1@2026-10-14` |
| Forum room | one room per **session** | `CS2040-LEC-1@2026-10-14` |
| User | Cognito `sub` (a UUID), never the email | `9a3f…` |

**Rules:**
- Dates are Singapore local dates (`Asia/Singapore`), not UTC. Timestamps stored in DynamoDB are UTC ISO-8601 (`2026-10-14T06:00:00Z`).
- Lesson types use NUSMods' own values (`Lecture`, `Tutorial`, …) but are uppercased and shortened in IDs (`LEC`, `TUT`). Write the mapping down once, in one file, used by both ingest and frontend.

**Decide:** is the forum room per session (new room each week) or per class (one room all semester)? Per session fits "posts expire in a day".

## 1.2 Lecture data file format

The ingest Lambda writes these; the browser reads them. This is a contract too.

**Proposed:** one file per academic week per day, in the web bucket:

```
lectures/2026-2027/sem-1/2026-10-14.json
```

```json
{
  "generatedAt": "2026-10-07T12:00:00Z",
  "date": "2026-10-14",
  "sessions": [
    {
      "id": "CS2040-LEC-1@2026-10-14",
      "moduleCode": "CS2040",
      "moduleTitle": "Data Structures and Algorithms",
      "faculty": "Computing",
      "lessonType": "Lecture",
      "classNo": "1",
      "startTime": "10:00",
      "endTime": "12:00",
      "venue": "LT19",
      "building": "COM1"
    }
  ]
}
```

**Rules:**
- Times are 24-hour local `HH:MM` strings. No timezones inside the file; the date is in the filename and the `date` field.
- Only lessons whose `lessonType` is a lecture are included.
- The frontend never calls NUSMods directly. If a field is missing, ingest adds it.

**Decide:** one file per day (simple, small) or one per week (fewer requests)? Per day is proposed.

## 1.3 API contract

Write this first, as empty FastAPI endpoints returning hardcoded sample data. The frontend then works against the real URLs from day one, and FastAPI publishes an interactive page at `/docs` for free.

**Proposed endpoints:**

| Method | Path | Login? | Purpose |
|---|---|---|---|
| GET | `/api/health` | no | deployment check |
| GET | `/api/lectures?date=&faculty=&from=&to=` | no | search sessions (may just read the S3 JSON) |
| GET | `/api/recommendations` | yes | suggested sessions for this user |
| GET | `/api/me` | yes | profile + preferences |
| PUT | `/api/me/preferences` | yes | save faculty/module interests |
| GET | `/api/me/timetable` | yes | saved timetable |
| PUT | `/api/me/timetable` | yes | save timetable (manual or imported) |
| POST | `/api/timetable/import` | yes | parse a NUSMods share link into our format |
| GET | `/api/sessions/{sessionId}/posts` | no | recent posts (also the WebSocket fallback) |
| POST | `/api/sessions/{sessionId}/posts` | yes | write a post |

**Rules:**
- Every response is JSON. Errors use `{"error": {"code": "...", "message": "..."}}` with a sensible HTTP status.
- Lists are returned as `{"items": [...]}`, never a bare array, so pagination can be added later.
- Field names are `camelCase` in JSON (the frontend's convention) even though Python uses `snake_case` internally.

## 1.4 DynamoDB design

**Proposed:** one table, `lecturekaki-main`, on-demand billing, plus a second small table for WebSocket connections.

Main table: partition key `pk` (string), sort key `sk` (string).

| Item | pk | sk | Notes |
|---|---|---|---|
| User profile | `USER#<sub>` | `PROFILE` | preferences, timetable |
| Forum post | `ROOM#<sessionId>` | `POST#<timestamp>#<uuid>` | has `ttl` |
| View history | `USER#<sub>` | `VIEW#<timestamp>` | feeds recommendations, has `ttl` |

Connections table `lecturekaki-connections`: pk `room` (`ROOM#<sessionId>`), sk `connectionId`.

**Rules:**
- The TTL attribute is named `ttl` and holds a **Unix epoch in seconds** (not ISO text, not milliseconds). DynamoDB will not delete items otherwise.
- Posts set `ttl` to 24 hours after creation. Deletion can lag by a few hours, so read queries must also filter out anything already expired.
- Nobody adds a new item type without adding a row to this table.

## 1.5 How auth travels

1. React signs the user in against Cognito and receives an **ID token** (a JWT).
2. REST calls send it as a header: `Authorization: Bearer <token>`.
3. API Gateway verifies it before your Lambda runs; the Lambda reads the user from the request context.
4. The WebSocket cannot send headers, so the token goes in the connect URL: `wss://…?token=<jwt>&session=<sessionId>`, and a small Lambda authorizer verifies it at `$connect`.
5. The user's identity everywhere else is the Cognito `sub`.

**Rules:**
- Never trust a user ID sent in a request body. It comes from the verified token only.
- Tokens expire (default 1 hour). The frontend refreshes them; agree who implements that (auth owner) so each feature doesn't reinvent it.

## 1.6 Repo and environments

**Proposed:** one repository, so one pull request can change the frontend, backend and infrastructure together.

```
/frontend          React app
/backend           FastAPI app + Lambda handlers
  /app             FastAPI routes
  /handlers        presignup.py, ws_connect.py, ws_disconnect.py, ws_send.py, ingest.py
/infra             template.yaml (all AWS resources)
/docs              this file, API notes, decision log
```

Two environments: `dev` (deployed from `main` automatically) and `prod` (deployed manually for the demo). Resource names carry the environment: `lecturekaki-dev-main`, `lecturekaki-prod-main`.

**Rules:**
- Branch from `main`, open a PR, someone else merges.
- No credentials in the repo, ever. Configuration comes from environment variables set by the deployment.

## 1.7 Forum posting path

**Proposed:** posting is a normal REST call (`POST /api/sessions/{id}/posts`); the WebSocket is used only to deliver new posts to everyone in the room. Simpler, reuses existing auth, and the REST endpoint doubles as the fallback if sockets fail.

## Decision log

Copy this into your meeting notes and fill the last two columns.

| # | Decision | Proposed | Owner | Agreed on |
|---|---|---|---|---|
| 1 | Identifier formats | §1.1 | | |
| 2 | Lecture JSON shape | §1.2 | | |
| 3 | API contract | §1.3 | | |
| 4 | DynamoDB keys + TTL | §1.4 | | |
| 5 | Auth flow | §1.5 | | |
| 6 | Repo + environments | §1.6 | | |
| 7 | Forum posting path | §1.7 | | |

---

# Part 2 — AWS from zero

## 2.0 Vocabulary

| Term | Meaning |
|---|---|
| **Region** | A physical location where your resources live. Use `ap-southeast-1` (Singapore). |
| **IAM** | The permission system. An **IAM user** is a person's login; a **role** is an identity a service assumes; a **policy** lists what is allowed. |
| **Stack** | A group of resources created together from one file, by CloudFormation. Delete the stack, everything in it goes. |
| **IaC** | Infrastructure as code: the file describing your resources, kept in the repo. |
| **SAM** | AWS Serverless Application Model. A friendlier syntax over CloudFormation for Lambda/API work, plus a CLI to deploy it. |

## 2.1 Account setup and safety first

> If your course gives you an **AWS Academy Learner Lab**, read its notes before this section: those accounts cannot create IAM roles (you must use the provided `LabRole`), restrict some services, and reset periodically. Confirm this with your TA before building.

1. One person creates the AWS account (or you use the course account). That first login is the **root user**: turn on MFA, then never use it for daily work.
2. Create an **IAM user for each member** with console access and MFA. For a student project, attaching `PowerUserAccess` plus permission to manage IAM roles is pragmatic.
3. **Set a budget before you deploy anything.** Billing → Budgets → monthly cost budget, e.g. US$20, with email alerts at 50% and 80%. This is the single most important step for a student project.
4. Everyone works in **ap-southeast-1**. Resources are region-specific, and a resource created in the wrong region is invisible from the right one.

## 2.2 Tools to install

```bash
# AWS CLI v2 and SAM CLI (macOS example; see AWS docs for Windows/Linux)
brew install awscli aws-sam-cli

aws --version
sam --version

# Log in: paste the access key from your IAM user, region ap-southeast-1, output json
aws configure

# Check it works — prints your account and user
aws sts get-caller-identity
```

Also: Python 3.12 and Node 20 for the app itself.

## 2.3 First deployment: the smallest thing that works

Goal for day one: a FastAPI endpoint running on Lambda, reachable over HTTPS, deployed from a file in your repo.

`/backend/app/main.py`:

```python
from fastapi import FastAPI
from mangum import Mangum           # pip install mangum

app = FastAPI()

@app.get("/api/health")
def health():
    return {"ok": True}

handler = Mangum(app)               # Lambda calls this
```

`/infra/template.yaml`:

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31

Parameters:
  Env:
    Type: String
    Default: dev

Globals:
  Function:
    Runtime: python3.12
    Timeout: 20
    MemorySize: 512

Resources:
  ApiFunction:
    Type: AWS::Serverless::Function
    Properties:
      CodeUri: ../backend
      Handler: app.main.handler
      Events:
        Api:
          Type: HttpApi            # creates an API Gateway HTTP API
          Properties:
            Path: /{proxy+}        # send every path to FastAPI
            Method: ANY

Outputs:
  ApiUrl:
    Value: !Sub "https://${ServerlessHttpApi}.execute-api.${AWS::Region}.amazonaws.com"
```

Deploy:

```bash
cd infra
sam build
sam deploy --guided      # stack name: lecturekaki-dev, region: ap-southeast-1
```

The output prints a URL. Open `<url>/api/health`. That is your backend live on AWS. `sam deploy` afterwards (no `--guided`) redeploys.

## 2.4 Adding the rest, one resource at a time

Add these to the same `template.yaml`, deploying after each so you know what broke.

**DynamoDB tables**

```yaml
  MainTable:
    Type: AWS::Serverless::SimpleTable
    Properties:
      TableName: !Sub "lecturekaki-${Env}-main"
      PrimaryKey: { Name: pk, Type: String }
  # Note: SimpleTable has no sort key — switch to AWS::DynamoDB::Table
  # with KeySchema pk/sk and TimeToLiveSpecification { AttributeName: ttl, Enabled: true }
```

Then give the function access and tell it the table name:

```yaml
  ApiFunction:
    Properties:
      Environment:
        Variables:
          MAIN_TABLE: !Ref MainTable
      Policies:
        - DynamoDBCrudPolicy: { TableName: !Ref MainTable }
```

**Cognito with the NUS-email rule**

```yaml
  PreSignUpFunction:
    Type: AWS::Serverless::Function
    Properties:
      CodeUri: ../backend
      Handler: handlers.presignup.handler

  UserPool:
    Type: AWS::Cognito::UserPool
    Properties:
      UserPoolName: !Sub "lecturekaki-${Env}"
      UsernameAttributes: [email]
      AutoVerifiedAttributes: [email]
      LambdaConfig:
        PreSignUp: !GetAtt PreSignUpFunction.Arn

  PreSignUpPermission:            # lets Cognito call the function
    Type: AWS::Lambda::Permission
    Properties:
      FunctionName: !Ref PreSignUpFunction
      Action: lambda:InvokeFunction
      Principal: cognito-idp.amazonaws.com
      SourceArn: !GetAtt UserPool.Arn

  UserPoolClient:                 # what the React app uses
    Type: AWS::Cognito::UserPoolClient
    Properties:
      UserPoolId: !Ref UserPool
      ExplicitAuthFlows: [ALLOW_USER_SRP_AUTH, ALLOW_REFRESH_TOKEN_AUTH]
```

`/backend/handlers/presignup.py`:

```python
def handler(event, context):
    email = (event["request"]["userAttributes"].get("email") or "").lower()
    if not email.endswith("@u.nus.edu"):
        raise Exception("Please sign up with your NUS email address.")
    return event
```

**Ingest Lambda on a schedule**

```yaml
  IngestFunction:
    Type: AWS::Serverless::Function
    Properties:
      CodeUri: ../backend
      Handler: handlers.ingest.handler
      Timeout: 300
      Environment:
        Variables:
          WEB_BUCKET: !Ref WebBucket
      Policies:
        - S3WritePolicy: { BucketName: !Ref WebBucket }
      Events:
        Weekly:
          Type: ScheduleV2                       # EventBridge Scheduler
          Properties:
            ScheduleExpression: "cron(0 19 ? * SUN *)"   # UTC = Mon 03:00 SGT
```

You can also run it on demand while developing:

```bash
aws lambda invoke --function-name <name> out.json
```

**WebSocket API** — SAM has no shortcut for this, so these are plain CloudFormation resources:

```yaml
  WebSocketApi:
    Type: AWS::ApiGatewayV2::Api
    Properties:
      Name: !Sub "lecturekaki-${Env}-ws"
      ProtocolType: WEBSOCKET
      RouteSelectionExpression: "$request.body.action"

  ConnectRoute:
    Type: AWS::ApiGatewayV2::Route
    Properties:
      ApiId: !Ref WebSocketApi
      RouteKey: "$connect"
      Target: !Sub "integrations/${ConnectIntegration}"

  ConnectIntegration:
    Type: AWS::ApiGatewayV2::Integration
    Properties:
      ApiId: !Ref WebSocketApi
      IntegrationType: AWS_PROXY
      IntegrationUri: !Sub "arn:aws:apigateway:${AWS::Region}:lambda:path/2015-03-31/functions/${ConnectFunction.Arn}/invocations"
  # repeat for $disconnect, and a Stage + Deployment resource
```

The function that pushes messages out needs permission to talk back through the API:

```yaml
      Policies:
        - Statement:
            Effect: Allow
            Action: execute-api:ManageConnections
            Resource: !Sub "arn:aws:execute-api:${AWS::Region}:${AWS::AccountId}:${WebSocketApi}/*"
```

**Frontend hosting** — an S3 bucket plus a CloudFront distribution in the same template. Deploy the built site with:

```bash
cd frontend && npm run build
aws s3 sync dist/ s3://<bucket-name> --delete
aws cloudfront create-invalidation --distribution-id <id> --paths "/*"
```

## 2.5 CI/CD (item 7)

A GitHub Actions workflow on every push to `main`:

1. Install Python deps, run backend tests.
2. `sam build && sam deploy --no-confirm-changeset` into `dev`.
3. `npm ci && npm run build`, sync to S3, invalidate CloudFront.

For credentials, prefer **GitHub OIDC**: create an IAM role that trusts your GitHub repo, so no long-lived keys sit in GitHub secrets. If that proves fiddly (or your Learner Lab forbids creating roles), fall back to an IAM user's access key stored in GitHub secrets, and say so in the report.

## 2.6 Cost guardrails

- Budget alert already set in §2.1.
- DynamoDB tables on **on-demand** billing — no idle cost.
- Keep load tests short, and check the Cost Explorer page after each one.
- `sam delete` removes the whole stack when you're done. Keep `prod` alive until marks are released, since the report must link to a working code base.

## 2.7 First-week checklist

- [ ] AWS account, IAM users with MFA, budget alert
- [ ] Everyone's `aws sts get-caller-identity` works in `ap-southeast-1`
- [ ] Repo created with the layout in §1.6
- [ ] `template.yaml` deploying one FastAPI health endpoint
- [ ] GitHub Actions deploying `dev` on merge
- [ ] Decision log in §1 filled in and agreed
- [ ] Empty endpoints from §1.3 live and returning sample data
- [ ] Ingest writing one real day of lecture JSON to S3
