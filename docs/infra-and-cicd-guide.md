# Infrastructure + CI/CD guide

For the person owning workstream 7. Goal: **every AWS resource is created from a file in the repo**, and merging to `main` deploys it. Nobody clicks in the console to change anything.

---

## 1. The rule, and the exceptions

**Rule:** the AWS console is read-only. Use it to look at logs, metrics, a DynamoDB table's contents, or a Lambda's configuration — never to change anything.

**Why it matters:** CloudFormation (the service that reads your template) remembers what it created. If you change something by hand, your next deploy either silently overwrites it or fails with a confusing conflict. That difference between "what's deployed" and "what the code says" is called drift, and it's how teams lose a working environment the night before a demo.

**The genuinely manual parts** (once, at the start):

| Step | Why it can't be code |
|---|---|
| Create the AWS account | Nothing exists yet |
| Create your first IAM user + access key | Need credentials to deploy anything |
| Turn on MFA | Security, and it's a console action |
| Add GitHub repo secrets/variables | That's GitHub, not AWS |

Everything else — including the budget alert — goes in a template.

> **If your course uses AWS Academy Learner Lab:** you cannot create IAM roles or an OIDC provider, and credentials rotate when the lab restarts. Skip the bootstrap stack in §4, use the provided `LabRole` as every function's role, and put the lab's temporary credentials in GitHub secrets, refreshing them when they expire. Note this constraint in the report — it's a legitimate finding about managed teaching environments.

---

## 2. Tools

```bash
brew install awscli aws-sam-cli      # macOS; see AWS docs for Windows/Linux
aws configure                        # key, secret, region ap-southeast-1, json
aws sts get-caller-identity          # must print your account id
```

Also Python 3.12 and Node 20.

## 3. Repo layout

```
/infra
  bootstrap.yaml      deployed once from your laptop
  template.yaml       everything else
  samconfig.toml      per-environment deploy settings
/backend
  app/main.py         FastAPI + Mangum
  handlers/           presignup.py ingest.py ws_connect.py ws_disconnect.py ws_send.py
  requirements.txt
/frontend             React app (build output in dist/)
/.github/workflows
  ci.yml              runs on pull requests
  deploy.yml          runs on merge to main, and manually for prod
```

---

## 4. Bootstrap stack (once, from your laptop)

This creates the things CI/CD itself needs: a trust relationship letting GitHub Actions log in without passwords, and the budget alarm.

`infra/bootstrap.yaml`:

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Description: One-time bootstrap - GitHub OIDC trust and budget alert

Parameters:
  GitHubRepo:
    Type: String
    Description: owner/repo, e.g. elinengu/lecture-kaki
  AlertEmail:
    Type: String

Resources:
  GitHubOIDCProvider:
    Type: AWS::IAM::OIDCProvider
    Properties:
      Url: https://token.actions.githubusercontent.com
      ClientIdList: [sts.amazonaws.com]
      ThumbprintList: ["6938fd4d98bab03faadb97b34396831e3780aea1"]

  DeployRole:
    Type: AWS::IAM::Role
    Properties:
      RoleName: lecturekaki-github-deploy
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal: { Federated: !Ref GitHubOIDCProvider }
            Action: sts:AssumeRoleWithWebIdentity
            Condition:
              StringEquals:
                token.actions.githubusercontent.com:aud: sts.amazonaws.com
              StringLike:
                token.actions.githubusercontent.com:sub: !Sub "repo:${GitHubRepo}:*"
      ManagedPolicyArns:
        - arn:aws:iam::aws:policy/PowerUserAccess      # tighten later if you have time
      Policies:
        - PolicyName: iam-for-sam
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action: [iam:CreateRole, iam:DeleteRole, iam:AttachRolePolicy,
                         iam:DetachRolePolicy, iam:PutRolePolicy, iam:DeleteRolePolicy,
                         iam:GetRole, iam:PassRole, iam:TagRole]
                Resource: "*"

  Budget:
    Type: AWS::Budgets::Budget
    Properties:
      Budget:
        BudgetName: lecturekaki-monthly
        BudgetType: COST
        TimeUnit: MONTHLY
        BudgetLimit: { Amount: 20, Unit: USD }
      NotificationsWithSubscribers:
        - Notification:
            NotificationType: ACTUAL
            ComparisonOperator: GREATER_THAN
            Threshold: 50
          Subscribers: [{ SubscriptionType: EMAIL, Address: !Ref AlertEmail }]

Outputs:
  DeployRoleArn:
    Value: !GetAtt DeployRole.Arn
```

Deploy it:

```bash
aws cloudformation deploy \
  --template-file infra/bootstrap.yaml \
  --stack-name lecturekaki-bootstrap \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides GitHubRepo=owner/repo AlertEmail=you@u.nus.edu
```

Copy the printed role ARN into GitHub → Settings → Secrets and variables → Actions → **variable** `AWS_DEPLOY_ROLE`. (A role ARN isn't secret, but keeping it as a variable is tidy.)

The OIDC thumbprint above is the long-standing GitHub one; if the role fails to assume, check the current value in GitHub's docs.

---

## 5. The main template

`infra/template.yaml`. Build it up in this order, deploying after each addition so a failure has one obvious cause.

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31

Parameters:
  Env: { Type: String, Default: dev, AllowedValues: [dev, prod] }

Globals:
  Function:
    Runtime: python3.12
    Timeout: 20
    MemorySize: 512
    Environment:
      Variables:
        ENV: !Ref Env
        MAIN_TABLE: !Ref MainTable
        WEB_BUCKET: !Ref WebBucket

Resources:

  # ---------- data ----------
  MainTable:
    Type: AWS::DynamoDB::Table
    Properties:
      TableName: !Sub "lecturekaki-${Env}-main"
      BillingMode: PAY_PER_REQUEST
      AttributeDefinitions:
        - { AttributeName: pk, AttributeType: S }
        - { AttributeName: sk, AttributeType: S }
      KeySchema:
        - { AttributeName: pk, KeyType: HASH }
        - { AttributeName: sk, KeyType: RANGE }
      TimeToLiveSpecification: { AttributeName: ttl, Enabled: true }

  ConnectionsTable:
    Type: AWS::DynamoDB::Table
    Properties:
      TableName: !Sub "lecturekaki-${Env}-connections"
      BillingMode: PAY_PER_REQUEST
      AttributeDefinitions:
        - { AttributeName: room, AttributeType: S }
        - { AttributeName: connectionId, AttributeType: S }
      KeySchema:
        - { AttributeName: room, KeyType: HASH }
        - { AttributeName: connectionId, KeyType: RANGE }

  # ---------- auth ----------
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
      LambdaConfig: { PreSignUp: !GetAtt PreSignUpFunction.Arn }

  PreSignUpPermission:
    Type: AWS::Lambda::Permission
    Properties:
      FunctionName: !Ref PreSignUpFunction
      Action: lambda:InvokeFunction
      Principal: cognito-idp.amazonaws.com
      SourceArn: !GetAtt UserPool.Arn

  UserPoolClient:
    Type: AWS::Cognito::UserPoolClient
    Properties:
      UserPoolId: !Ref UserPool
      ExplicitAuthFlows: [ALLOW_USER_SRP_AUTH, ALLOW_REFRESH_TOKEN_AUTH]

  # ---------- REST API ----------
  HttpApi:
    Type: AWS::Serverless::HttpApi
    Properties:
      StageName: !Ref Env
      Auth:
        Authorizers:
          CognitoAuth:
            IdentitySource: "$request.header.Authorization"
            JwtConfiguration:
              issuer: !Sub "https://cognito-idp.${AWS::Region}.amazonaws.com/${UserPool}"
              audience: [!Ref UserPoolClient]
        DefaultAuthorizer: CognitoAuth

  ApiFunction:
    Type: AWS::Serverless::Function
    Properties:
      CodeUri: ../backend
      Handler: app.main.handler
      Policies:
        - DynamoDBCrudPolicy: { TableName: !Ref MainTable }
        - DynamoDBCrudPolicy: { TableName: !Ref ConnectionsTable }
      Events:
        Public:                      # routes anyone may call
          Type: HttpApi
          Properties:
            ApiId: !Ref HttpApi
            Path: /api/lectures
            Method: GET
            Auth: { Authorizer: NONE }
        Everything:                  # the rest require a token
          Type: HttpApi
          Properties:
            ApiId: !Ref HttpApi
            Path: /{proxy+}
            Method: ANY

  # ---------- ingest ----------
  IngestFunction:
    Type: AWS::Serverless::Function
    Properties:
      CodeUri: ../backend
      Handler: handlers.ingest.handler
      Timeout: 300
      MemorySize: 1024
      Policies:
        - S3WritePolicy: { BucketName: !Ref WebBucket }
      Events:
        Weekly:
          Type: ScheduleV2
          Properties:
            ScheduleExpression: "cron(0 19 ? * SUN *)"   # Mon 03:00 Singapore

  # ---------- website hosting ----------
  WebBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !Sub "lecturekaki-${Env}-web-${AWS::AccountId}"

  # CloudFront distribution + Origin Access Control + bucket policy go here.
  # Check the current CloudFront OAC syntax in the AWS docs - it changed in 2022
  # and most examples online still show the older Origin Access Identity.
```

**WebSocket API** (plain CloudFormation; SAM has no shortcut). Repeat the integration/route pair for `$connect`, `$disconnect` and your `sendPost` route:

```yaml
  WebSocketApi:
    Type: AWS::ApiGatewayV2::Api
    Properties:
      Name: !Sub "lecturekaki-${Env}-ws"
      ProtocolType: WEBSOCKET
      RouteSelectionExpression: "$request.body.action"

  ConnectFunction:
    Type: AWS::Serverless::Function
    Properties:
      CodeUri: ../backend
      Handler: handlers.ws_connect.handler
      Environment:
        Variables: { CONNECTIONS_TABLE: !Ref ConnectionsTable }
      Policies:
        - DynamoDBCrudPolicy: { TableName: !Ref ConnectionsTable }

  ConnectIntegration:
    Type: AWS::ApiGatewayV2::Integration
    Properties:
      ApiId: !Ref WebSocketApi
      IntegrationType: AWS_PROXY
      IntegrationUri: !Sub "arn:aws:apigateway:${AWS::Region}:lambda:path/2015-03-31/functions/${ConnectFunction.Arn}/invocations"

  ConnectRoute:
    Type: AWS::ApiGatewayV2::Route
    Properties:
      ApiId: !Ref WebSocketApi
      RouteKey: "$connect"
      Target: !Sub "integrations/${ConnectIntegration}"

  ConnectPermission:
    Type: AWS::Lambda::Permission
    Properties:
      FunctionName: !Ref ConnectFunction
      Action: lambda:InvokeFunction
      Principal: apigateway.amazonaws.com

  WebSocketDeployment:
    Type: AWS::ApiGatewayV2::Deployment
    DependsOn: [ConnectRoute]          # list every route here
    Properties: { ApiId: !Ref WebSocketApi }

  WebSocketStage:
    Type: AWS::ApiGatewayV2::Stage
    Properties:
      ApiId: !Ref WebSocketApi
      DeploymentId: !Ref WebSocketDeployment
      StageName: !Ref Env
```

The function that broadcasts posts also needs permission to push back out:

```yaml
      Policies:
        - Statement:
            Effect: Allow
            Action: execute-api:ManageConnections
            Resource: !Sub "arn:aws:execute-api:${AWS::Region}:${AWS::AccountId}:${WebSocketApi}/*"
```

**Outputs** — the frontend needs these, so print them:

```yaml
Outputs:
  ApiUrl:        { Value: !Sub "https://${HttpApi}.execute-api.${AWS::Region}.amazonaws.com/${Env}" }
  WebSocketUrl:  { Value: !Sub "wss://${WebSocketApi}.execute-api.${AWS::Region}.amazonaws.com/${Env}" }
  UserPoolId:    { Value: !Ref UserPool }
  UserPoolClientId: { Value: !Ref UserPoolClient }
  WebBucketName: { Value: !Ref WebBucket }
```

## 6. Deploying by hand (what CI/CD will automate)

`infra/samconfig.toml`:

```toml
version = 0.1

[dev.deploy.parameters]
stack_name = "lecturekaki-dev"
region = "ap-southeast-1"
capabilities = "CAPABILITY_IAM"
parameter_overrides = "Env=dev"
resolve_s3 = true

[prod.deploy.parameters]
stack_name = "lecturekaki-prod"
region = "ap-southeast-1"
capabilities = "CAPABILITY_IAM"
parameter_overrides = "Env=prod"
resolve_s3 = true
```

```bash
cd infra
sam build
sam deploy --config-env dev
sam logs -n ApiFunction --stack-name lecturekaki-dev --tail   # live logs
```

---

## 7. What CI/CD needs from everyone else

Agree these once; the pipeline depends on them and breaks silently when someone changes one:

| Thing | Agreed value |
|---|---|
| Handler paths | `app.main.handler`, `handlers.ingest.handler`, … |
| Backend dependency file | `backend/requirements.txt` |
| Test command | `pytest backend/tests` (must exist, even with one trivial test) |
| Frontend build command + output | `npm run build` → `frontend/dist` |
| How the frontend learns URLs | build-time env vars written from stack outputs |
| Health endpoint | `GET /api/health` returning 200 |
| Branch rules | PR into `main`, no direct pushes |

The frontend-URL point matters: the React build needs the API URL, WebSocket URL and Cognito IDs. The pipeline reads them from the stack outputs and writes them as `VITE_*` environment variables before building, so nothing is hardcoded and dev and prod differ only by deployment.

## 8. The workflows

`.github/workflows/ci.yml` — runs on every pull request:

```yaml
name: ci
on: pull_request

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -r backend/requirements.txt
      - run: pytest backend/tests
      - uses: aws-actions/setup-sam@v2
      - run: sam validate -t infra/template.yaml --lint
      - run: sam build -t infra/template.yaml
      - uses: actions/setup-node@v4
        with: { node-version: '20', cache: npm, cache-dependency-path: frontend/package-lock.json }
      - run: npm ci --prefix frontend && npm run build --prefix frontend
```

`.github/workflows/deploy.yml` — merge to `main` deploys dev; the manual button deploys prod:

```yaml
name: deploy
on:
  push: { branches: [main] }
  workflow_dispatch:
    inputs:
      environment:
        description: Environment to deploy
        default: prod
        type: choice
        options: [dev, prod]

permissions:
  id-token: write
  contents: read

jobs:
  deploy:
    runs-on: ubuntu-latest
    env:
      ENV_NAME: ${{ github.event.inputs.environment || 'dev' }}
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ vars.AWS_DEPLOY_ROLE }}
          aws-region: ap-southeast-1
      - uses: aws-actions/setup-sam@v2
      - run: sam build -t infra/template.yaml
      - run: sam deploy --config-env $ENV_NAME --no-confirm-changeset --no-fail-on-empty-changeset
        working-directory: infra

      - name: Read stack outputs
        id: out
        run: |
          STACK=lecturekaki-$ENV_NAME
          get() { aws cloudformation describe-stacks --stack-name $STACK \
                  --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
          echo "api=$(get ApiUrl)"            >> $GITHUB_OUTPUT
          echo "ws=$(get WebSocketUrl)"       >> $GITHUB_OUTPUT
          echo "pool=$(get UserPoolId)"       >> $GITHUB_OUTPUT
          echo "client=$(get UserPoolClientId)" >> $GITHUB_OUTPUT
          echo "bucket=$(get WebBucketName)"  >> $GITHUB_OUTPUT

      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - name: Build frontend
        working-directory: frontend
        env:
          VITE_API_URL: ${{ steps.out.outputs.api }}
          VITE_WS_URL: ${{ steps.out.outputs.ws }}
          VITE_USER_POOL_ID: ${{ steps.out.outputs.pool }}
          VITE_USER_POOL_CLIENT_ID: ${{ steps.out.outputs.client }}
        run: npm ci && npm run build

      - name: Publish frontend
        run: |
          aws s3 sync frontend/dist "s3://${{ steps.out.outputs.bucket }}" --delete
          aws cloudfront create-invalidation --distribution-id ${{ vars.CF_DIST_ID }} --paths "/*"

      - name: Smoke test
        run: curl -fsS "${{ steps.out.outputs.api }}/api/health"
```

**What the pipeline therefore does:** blocks a broken PR from merging; on merge, updates every AWS resource that changed, rebuilds the site with the right URLs for that environment, publishes it, clears the CDN cache, and fails loudly if the deployed API doesn't answer. Deploying to prod is the same pipeline, triggered by a button.

## 9. Rollback, teardown, troubleshooting

- **Rollback:** CloudFormation rolls back automatically if a deploy fails. To undo a bad but successful deploy, revert the commit and merge — the pipeline redeploys the previous state.
- **Teardown:** `sam delete --config-env dev`. Empty the S3 bucket first or it refuses. Keep `prod` alive until marks are out.
- **Common errors:**
  - `CREATE_FAILED ... already exists` — a resource with that name exists outside the stack. Rename it or import it; don't delete things in the console blindly.
  - `Role cannot be assumed` in Actions — the OIDC `sub` condition doesn't match your repo, or the thumbprint is stale.
  - `AccessDenied` on `s3 sync` — the deploy role lacks bucket permissions.
  - Site unchanged after deploy — CloudFront cache; check the invalidation ran.
  - Lambda errors — `sam logs --tail`, or CloudWatch → Log groups → `/aws/lambda/<function>`.

## 10. Checklist

- [ ] Bootstrap stack deployed; `AWS_DEPLOY_ROLE` variable set in GitHub
- [ ] Budget alert email received as a test
- [ ] `template.yaml` deploying a health endpoint to dev
- [ ] CI failing on a deliberately broken test, and passing once fixed
- [ ] Merge to `main` deploys without anyone running a command
- [ ] Stack outputs feeding the frontend build
- [ ] `prod` deployed once, well before the demo
- [ ] One-page runbook in `/docs` (deploy, rollback, logs, re-run ingest)

**Effort:** 18–28 hours, front-loaded. Expect the OIDC role and the first CloudFront configuration to take the longest. If OIDC resists for more than an hour, use an IAM user's access key in GitHub secrets, note the trade-off in the report, and move on.
