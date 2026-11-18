# Lift and shift guide: moving MATRIX into a new AWS account

Same region as the source account, same ServiceNow instance. Everything is done from the AWS console. One CloudFormation template builds the whole product.

## The short path

### Before you start: collect from the source account (read-only, into a private note)
- The source Lambda's environment variables (Configuration, Environment variables), especially `USERS` (the sign-in accounts) and the ServiceNow settings.
- Anything the source role has that `infra/matrix-core.yaml` lacks (compare the role's policy JSON).
- The runbooks in the source `OPS_BUCKET`.
- Any OTHER Lambda in that account with an SNS trigger: the alarm ingest function (`INGEST_URL`). It is not in this repo. Download its code (Lambda, Code tab, Download).

### Step 1: put the code where AWS can read it
1. S3 console, **Create bucket**. Any unique name, same region. Leave the defaults.
2. Upload `dist\matrix-lambda.zip` to that bucket. To rebuild it: `Compress-Archive -Path lambda\*.py -DestinationPath dist\matrix-lambda.zip -Force` (the `.py` files must sit at the top level of the zip).

### Step 2: create the stack (one upload, one form)
1. CloudFormation console, **Create stack**, **With new resources**, **Upload a template file**, choose `infra\matrix-all.yaml`.
2. Stack name: `matrix`. Fill the form (parameters are grouped):
   - **Code:** `CodeBucket` = your bucket from step 1. Leave `CodeKey` as `matrix-lambda.zip`. `Environment` = dev, test or prod.
   - **ServiceNow:** `SnBase` (https://devXXXXXX.service-now.com, no trailing slash), `SnUser`, `SnPass`.
   - **Sign-in:** a NEW `TokenSecret` (32+ random characters), `UsersJson` (copy from the source), a NEW `AgentKey`.
   - **LLM:** `LlmApiKey` (NVIDIA `nvapi-...`) and `LlmModel` (the exact model ID from the NVIDIA page). Standby keys and models are optional: a slot works only if it has both a key and a model.
   - **AWS operations:** `SubnetId` and `SecurityGroupId` (for servers the agent deploys). Leave the rest as is.
   - **Agent behaviour:** set `LearnScan` = `DISABLED` for now (see cutover).
3. Tick the box that says CloudFormation may create IAM resources with custom names, then **Submit**. It takes about 5 to 10 minutes. Wait for `CREATE_COMPLETE`.
4. Open the **Outputs** tab and copy `FunctionUrl`.

### Step 3: open the web page
Double-click `frontend\matrix-ui.html` on your PC (use Chrome or Edge). Paste the `FunctionUrl` into the sign-in screen and sign in with a user from `UsersJson`.
This works because `WebsiteUrl` defaults to `*`. If you later host the page in S3 for a team, deploy `infra/matrix-s3.yaml` and set `WebsiteUrl` to that address.

### Step 4: the pieces the template cannot create
- Upload the runbooks to the ops bucket (Outputs, `OpsBucketName`).
- A test server (for example `matrix-linux-01`): tag `matrix-managed=true` and `environment=<your Environment value>`, attach the instance profile from Outputs (`InstanceProfileName`), SSM agent running.
- The alarm ingest function and its SNS topic (see "Before you start"). Put its URL in the stack's `IngestUrl` parameter (Update stack, Use existing template).
- Enable Cost Explorer once (Billing console).
- Optional: a CodeBuild project named `matrix-...` for Terraform (`TfProject`), and an operator role for the chat tool `aws_write` (`OperatorRoleArn`). Without it `aws_write` stays off.

### Step 5: cutover (same ServiceNow, so only one agent may act at a time)
1. Test the new stack while `LearnScan` is `DISABLED` and the old account's agent is still running.
2. When the checks below pass, disable the old account's EventBridge rule and its Function URL.
3. Update the new stack with `LearnScan` = `ENABLED`.
4. Keep the old account untouched for a soak period, then retire it.
Never reuse the old `TokenSecret`, `AgentKey` or passwords.

### Verify
1. Lambda, Test tab, send `{"matrix_task":"nothing"}`. The CloudWatch log shows no import error.
2. Dashboard: no "ServiceNow is not connected" banner; incidents load.
3. Chat: "health check matrix-linux-01" works with no LLM error. Observability shows traces and the LLM chain (primary plus standbys).
4. "scan matrix-linux-01 for missing patches", then ask for a patch install: the agent raises a CHG, waits for approval in ServiceNow, then shows Confirm.
5. "plan a new server called test-01, 2 vCPU 4 GB" shows a plan; decommission assess on a throwaway server shows warnings; terminate refuses without the backup, the hold period and the human tag.
6. Work notes appear on tickets; the audit log group has entries; the Dashboard cost card fills in.

### Rollback
Delete the `matrix` stack (empty the ops bucket first; it is kept on purpose). The source account is untouched.

## Keeping the one template up to date
`infra/matrix-all.yaml` is generated from the separate templates. After changing any of them run
`python tools/build-all-template.py`, then `cfn-lint infra/matrix-all.yaml`.

## Appendix: the six-stack route (one piece at a time)
Use this to debug a single piece, or if you prefer separate stacks. Same region, in this order:
| # | Template | Needs | Gives you |
|---|---|---|---|
| 1 | `matrix-table.yaml` | nothing | projects, sessions and usage tables |
| 2 | `matrix-core.yaml` | nothing | trace table, ops and artifact buckets, log group, Lambda role |
| 3 | `matrix-iam-executor.yaml` | `TrustedLambdaRoleArn` from #2 | executor role, instance profile, audit log |
| 4 | `matrix-playbook.yaml` | nothing | SSM playbooks |
| 5 | `matrix-s3.yaml` | a unique bucket name | website bucket |
| 6 | `matrix-app.yaml` | outputs of #2, #3, #5 and your secrets | the Lambda, Function URL and schedule |
Upload `matrix-lambda.zip` to the artifact bucket from #2 before #6.

## Tests and lint in this repo
`python -m unittest discover -s tests -v` (offline; AWS and ServiceNow are stubbed) and `cfn-lint infra/*.yaml`.
