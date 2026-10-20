# AWS deployment guide

From a working local setup (README sections 4 and 5) to Insightly running on AWS, one service
at a time, with a check after every step. Every command runs from the **VS Code integrated
terminal** (`` Ctrl+` ``) at the repository root unless a step says `cd infra`.

Region used throughout: **ap-south-1 (Mumbai)**. To use another region, replace it everywhere
and pass `-c region=<region>` to CDK.

| Step | AWS service | Time |
|---|---|---|
| 0 | IAM Identity Center + AWS CLI profile | 15 min |
| 1 | AWS Budgets + cost allocation tags | 5 min |
| 2 | CDK bootstrap (CloudFormation, S3, ECR, IAM) | 5 min |
| 3 | S3, Glue Data Catalog, Athena | 5 min |
| 4 | Load data into the lakehouse | 5 min |
| 5 | VPC, NAT gateway, S3 gateway endpoint | 5 min |
| 6 | Aurora PostgreSQL Serverless v2 | 10 min |
| 7 | Secrets Manager (OpenAI key) | 2 min |
| 8 | ECR, ECS Fargate, ALB, Cognito | 10 min |
| 9 | Cognito user and token | 5 min |
| 10 | Smoke test and evaluation against AWS | 10 min |
| 11 | CloudWatch dashboard, alarms, SNS, Budgets | 5 min |
| 12 | GitHub Actions deploys with OIDC | 15 min |
| 13 | Optional hardening (HTTPS, WAF, Lake Formation) | - |
| 14 | Teardown | 10 min |

Cost while running: roughly $3 to $4 per day for the always-on parts (NAT gateway, ALB,
one Fargate task), plus model usage. Destroy the stack after a demo (step 14). See
[cost-management.md](cost-management.md).

---

## Step 0. Account access and the AWS CLI

Never use the root user or long-lived access keys for daily work.

1. Sign in to the AWS console as the account owner. Turn on MFA for the root user
   (IAM → Security recommendations).
2. Open **IAM Identity Center** → **Enable** (choose the region you will work in).
3. **Users → Add user**: your email. **Permission sets → Create** → predefined
   `AdministratorAccess` (fine for a personal learning account; use least privilege at work).
4. **AWS accounts** → select the account → **Assign users** → your user + the permission set.
5. Note the **AWS access portal URL** shown on the Identity Center dashboard.

In the VS Code terminal:

```bash
aws configure sso
#  SSO session name: insightly
#  SSO start URL: <your access portal URL>
#  SSO region: ap-south-1
#  CLI default client Region: ap-south-1
#  CLI default output format: json
#  CLI profile name: insightly

export AWS_PROFILE=insightly                 # Windows PowerShell: $env:AWS_PROFILE="insightly"
aws sso login
aws sts get-caller-identity                  # shows your account id and role
```

Optional: in the **AWS Toolkit** sidebar choose *Connect to AWS* → profile `insightly`, so you can
browse S3, CloudWatch logs and ECS from VS Code.

Save these for later:

```bash
export AWS_REGION=ap-south-1
export ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
```

## Step 1. Budget first

Create the alarm before creating anything that costs money.

1. Console → **Billing and Cost Management → Budgets → Create budget** → *Use a template* →
   **Monthly cost budget**, amount e.g. `$30`, your email → Create.
2. **Billing → Cost allocation tags** → find `project` (appears after step 3 deploys) →
   **Activate**. CDK tags every resource `project=insightly`, so Cost Explorer can show this
   project alone. Activation takes up to 24 hours.

Check: Budgets lists your budget with status *OK*.

## Step 2. Bootstrap CDK

CDK needs a staging bucket, an ECR repository and deployment roles in the account, once per
account and region.

```bash
uv sync --group infra                     # installs aws-cdk-lib into .venv
cd infra
uv run --group infra npx -y aws-cdk@2 bootstrap aws://$ACCOUNT/ap-south-1
uv run --group infra npx -y aws-cdk@2 synth --quiet     # renders all 5 stacks, no deploy
```

Check: CloudFormation console shows a `CDKToolkit` stack in *CREATE_COMPLETE*.

> Tip: add `alias cdk="uv run --group infra npx -y aws-cdk@2"` to your shell. The rest of
> this guide writes `cdk` for short.

## Step 3. Data lake: S3, Glue Data Catalog, Athena

```bash
cdk deploy InsightlyData
```

What it creates (`infra/stacks/data_stack.py`):

| Resource | Setting | Why |
|---|---|---|
| S3 `insightly-data-<account>-ap-south-1` | private, SSE-S3, TLS only, staging/ expires in 30 days | lakehouse storage |
| S3 `insightly-athena-results-...` | objects expire in 7 days | query results are disposable |
| Glue databases `insightly_raw`, `insightly_curated` | | table metadata |
| Athena workgroup `insightly` | engine v3, enforced settings, **1 GB scanned per query cap**, CloudWatch metrics | cost and safety guardrail |

Check in the console:
* **S3**: both buckets exist and are not public.
* **Glue → Databases**: `insightly_raw` and `insightly_curated`.
* **Athena → Workgroups → insightly**: *Data usage control* shows the 1 GB per-query limit.

## Step 4. Load the data

From the repository root (`cd ..` if you are in `infra`). If you have not already:

```bash
uv run insightly data synthetic --users 20000     # or copy the real CSVs to data/raw/
uv run insightly data curate
```

Publish to AWS:

```bash
export INSIGHTLY_DATA_BUCKET=insightly-data-$ACCOUNT-ap-south-1
export INSIGHTLY_ATHENA_WORKGROUP=insightly
uv run insightly data publish --bucket $INSIGHTLY_DATA_BUCKET
```

For each table this uploads Parquet to `s3://.../staging/<table>/`, creates an external table in
`insightly_raw`, then runs a CTAS into an **Apache Iceberg** table in `insightly_curated`
(`events` partitioned by month, `order_items` by year, so time-filtered queries scan less).

Check: **Athena → Query editor**, workgroup `insightly`, database `insightly_curated`:

```sql
SELECT status, COUNT(*) AS orders FROM orders GROUP BY status ORDER BY orders DESC;
```

The query details show *Data scanned* in KB/MB. That number drives Athena cost ($5 per TB).

Now run the agent **on your laptop against Athena** (proves IAM, SQL dialect and data before any
compute is deployed):

```bash
INSIGHTLY_QUERY_ENGINE=athena uv run insightly ask "Return rate by order month in 2023"
```

## Step 5. Network: VPC, NAT gateway, S3 endpoint

```bash
cd infra && cdk deploy InsightlyNetwork
```

| Resource | Setting | Why |
|---|---|---|
| VPC | 2 AZs, public + private subnets | tasks and database stay private |
| NAT gateway | **1** (not one per AZ) | outbound HTTPS to OpenAI; one NAT halves the fixed network cost |
| S3 gateway endpoint | free | Athena results and data traffic avoid NAT data charges |
| VPC flow logs | rejected traffic only | security visibility at low log volume |

Check: **VPC console** → `InsightlyNetwork/Vpc` with 4 subnets, 1 NAT gateway, endpoint `com.amazonaws.ap-south-1.s3`.

## Step 6. Database: Aurora PostgreSQL Serverless v2

```bash
cdk deploy InsightlyDatabase
```

| Setting | Value | Why |
|---|---|---|
| Engine | Aurora PostgreSQL 17 | pgvector extension available |
| Capacity | 0 to 2 ACU, **auto-pause after 15 min** | costs storage only when idle |
| Credentials | generated, stored in Secrets Manager | no password in code |
| Network | private subnets, its own security group | reachable only from the API tasks |
| Backups | 7 days, snapshot on delete | |

Used for: the semantic-layer vectors (`semantic_docs` table with an HNSW index and a full-text
index) and LangGraph checkpoints (conversation state per thread). Tables are created by the
application on startup.

Check: **RDS → Databases** shows the cluster *Available*. The first connection after a pause
takes about 15 seconds while it resumes. That is expected.

## Step 7. Secrets Manager: the OpenAI key

Create the secret yourself so the key never appears in code, templates or CI logs:

```bash
read -s OPENAI_KEY          # paste the key, press Enter (input is hidden)
aws secretsmanager create-secret --name insightly/openai-api-key \
  --description "OpenAI API key for Insightly" --secret-string "$OPENAI_KEY"
unset OPENAI_KEY
```

Rotate later with `aws secretsmanager put-secret-value --secret-id insightly/openai-api-key
--secret-string ...`, then force a new ECS deployment (runbook).

In the **OpenAI dashboard** for this key's project, also set a monthly **usage limit** and enable
email alerts. That limit is the last line of defence for model spend.

## Step 8. The service: ECR, ECS Fargate, ALB, Cognito

Docker must be running (CDK builds the image locally and pushes it to ECR).

```bash
cdk deploy InsightlyService
```

| Resource | Setting | Why |
|---|---|---|
| ECR image | built from `Dockerfile`, **linux/arm64** | Graviton Fargate costs about 20% less than x86 |
| ECS Fargate service | 1 vCPU, 2 GB, 1 to 3 tasks, CPU target 60% | scales with load |
| Deployment | circuit breaker with rollback, min healthy 100% | a bad image never replaces a good one |
| ALB | public, health check `/healthz` | entry point |
| Task role | Athena on workgroup `insightly`, Glue read on `insightly_curated`, S3 read `curated/*`, **explicit deny** on `users_pii` | least privilege; PII unreachable even if the SQL firewall were bypassed |
| Secrets | `OPENAI_API_KEY` injected from Secrets Manager, DB secret read at runtime | |
| Cognito | user pool (admin-created users only, 12-char passwords), app client, `admin` group | authentication |
| Logs | `/insightly/api`, JSON, 14 days retention, CloudWatch EMF metrics | observability at low cost |

Outputs printed at the end (copy them):

```
InsightlyService.ApiUrl = http://Insigh-ApiLB-....ap-south-1.elb.amazonaws.com
InsightlyService.UserPoolId = ap-south-1_XXXX
InsightlyService.UserPoolClientId = xxxxxxxx
```

```bash
export API_URL=<ApiUrl>  POOL=<UserPoolId>  CLIENT=<UserPoolClientId>
```

Check: **ECS → Clusters → InsightlyService-Cluster → Services**: 1/1 tasks running.
**CloudWatch → Log groups → /insightly/api**: a `startup` log line with `indexed_docs`.
`curl $API_URL/healthz` returns `{"status":"ok"}`.

## Step 9. Cognito: create a user and get a token

```bash
EMAIL=you@example.com
aws cognito-idp admin-create-user --user-pool-id $POOL --username $EMAIL \
  --user-attributes Name=email,Value=$EMAIL Name=email_verified,Value=true \
  --message-action SUPPRESS
aws cognito-idp admin-set-user-password --user-pool-id $POOL --username $EMAIL \
  --password 'Choose-A-Long-Passw0rd!' --permanent
aws cognito-idp admin-add-user-to-group --user-pool-id $POOL --username $EMAIL --group-name admin

export TOKEN=$(aws cognito-idp initiate-auth --client-id $CLIENT --auth-flow USER_PASSWORD_AUTH \
  --auth-parameters USERNAME=$EMAIL,PASSWORD='Choose-A-Long-Passw0rd!' \
  --query AuthenticationResult.IdToken --output text)
```

Tokens last 1 hour. Re-run the last command to refresh.

## Step 10. Smoke test and evaluate on AWS

```bash
curl -s $API_URL/v1/ask -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"question":"Net revenue by category group in 2023"}' | jq '.status, .answer, .sql, .cost.total_usd'

curl -s $API_URL/v1/ask -H 'content-type: application/json' -d '{"question":"x"}'   # 401 without a token
```

Point the console at AWS:

```bash
INSIGHTLY_API_URL=$API_URL INSIGHTLY_API_TOKEN=$TOKEN uv run --extra ui streamlit run ui/streamlit_app.py
```

Run the evaluation against the AWS data plane from your laptop (same golden set, Athena engine):

```bash
INSIGHTLY_QUERY_ENGINE=athena uv run insightly eval run && uv run insightly eval gate
uv run insightly cost report --questions-per-day 500
```

## Step 11. Operations: CloudWatch, SNS, AWS Budgets

```bash
cdk deploy InsightlyOps -c alertEmail=$EMAIL -c monthlyBudgetUsd=50
```

* Confirm the **SNS subscription** email you receive.
* **CloudWatch → Dashboards → Insightly**: questions by outcome, p50/p95 latency, cost per 5 min,
  SQL attempts, tokens, ALB 5xx. All application metrics come from EMF log lines (no extra API calls).
* Alarms: p95 latency > 12 s (3 periods), > 10 failed questions in 5 min, > $2 model spend in 1 h.
* A project-tagged monthly **AWS Budget** alerts at 80% actual and 100% forecast.

## Step 12. Deploy from GitHub Actions with OIDC (no access keys)

1. IAM → **Identity providers → Add provider** → OpenID Connect, URL
   `https://token.actions.githubusercontent.com`, audience `sts.amazonaws.com`.
2. Create role `insightly-github-deploy` with this trust policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Federated": "arn:aws:iam::<ACCOUNT>:oidc-provider/token.actions.githubusercontent.com"},
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com"},
      "StringLike": {"token.actions.githubusercontent.com:sub": "repo:Pradipwasre/Insightly:*"}
    }
  }]
}
```

   and this permission policy (CDK deploys through its own bootstrap roles):

```json
{"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "sts:AssumeRole",
  "Resource": "arn:aws:iam::<ACCOUNT>:role/cdk-*"}]}
```

3. GitHub repo → Settings → **Environments** → `production` (add yourself as required reviewer).
   **Variables**: `AWS_DEPLOY_ROLE_ARN`, `AWS_REGION=ap-south-1`, `ALERT_EMAIL`.
   **Secrets**: `OPENAI_API_KEY` (for the nightly evaluation), optional `LANGSMITH_API_KEY`.
4. Actions → **deploy** → Run workflow.

## Step 13. Optional hardening for a real company

| Control | How |
|---|---|
| HTTPS | request an ACM certificate for your domain, pass `certificate` + `domain_name` to the ALB pattern, redirect HTTP |
| AWS WAF | attach a web ACL with AWS managed rules to the ALB (about $5/month + requests) |
| Lake Formation | register the data bucket, grant `SELECT` on `insightly_curated` tables to the task role, add data-cell filters per business unit for row-level security |
| Interface VPC endpoints | Secrets Manager, ECR, CloudWatch Logs, Athena endpoints remove NAT traffic (each costs about $7–8/month per AZ) |
| Private API | internal ALB + VPN / AWS Verified Access instead of a public ALB |
| Macie | scheduled discovery job on the data bucket to catch PII landing outside `users_pii` |

## Step 14. Teardown

```bash
cd infra
cdk destroy --all
aws secretsmanager delete-secret --secret-id insightly/openai-api-key --force-delete-without-recovery
aws rds describe-db-cluster-snapshots --query "DBClusterSnapshots[?contains(DBClusterSnapshotIdentifier,'insightly')].DBClusterSnapshotIdentifier"
aws rds delete-db-cluster-snapshot --db-cluster-snapshot-identifier <id>   # snapshot kept on delete
```

The `CDKToolkit` stack can stay (it costs cents). Check **Billing → Bills** the next day.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `cdk deploy InsightlyService` stuck on the service | open the ECS service *Events* tab and the task's *Logs*. Usually the secret from step 7 is missing or misnamed |
| `ResourceInitializationError: unable to pull secrets` | secret name must be exactly `insightly/openai-api-key` in the same region |
| Tasks healthy but answers fail with 401 from OpenAI | wrong key in the secret: `put-secret-value`, then `aws ecs update-service --cluster <c> --service <s> --force-new-deployment` |
| `AccessDeniedException` from Athena/Glue | table outside `insightly_curated` or a Glue permission missing in `service_stack.py` |
| First question after idle is slow | Aurora resuming from auto-pause (about 15 s). Raise min ACU to 0.5 to avoid it, at extra cost |
| `exec format error` in task logs | image built for the wrong CPU. Keep `Platform.LINUX_ARM64` and Docker Desktop's default emulation |
