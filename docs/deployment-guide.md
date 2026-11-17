# Lift and shift guide: moving MATRIX into a new AWS account

Same region as the source account, same ServiceNow instance. Do the steps in order.

## 0. Collect from the source account (console, read-only)
In the source Lambda, Configuration tab:
1. Environment variables: copy into a private note (see `env-template.md`).
2. General configuration: runtime, memory, timeout, handler (`lambda_function.handler`), architecture.
3. Permissions: the execution role and its policy JSON.
4. Function URL: auth type and CORS.
Also note: the EventBridge rule that sends `{"matrix_task":"learn_scan"}`, the `OPS_BUCKET` contents (runbooks), the CodeBuild project
named in `TF_PROJECT`, and the DynamoDB table names.

## 1. Build the package
Zip the contents of `lambda/` (the files at the top level of the zip, not the folder). On Windows PowerShell:
`Compress-Archive -Path lambda\*.py -DestinationPath matrix-lambda.zip`

## 2. Deploy in the new account
1. CloudFormation: `infra/matrix-table.yaml`. Note the output `PolicyArn` and the table names.
2. S3 bucket for `OPS_BUCKET`. Upload the runbooks copied from the source bucket.
3. Lambda execution role: attach the policy JSON copied in step 0 plus `PolicyArn`. Keep it to what the code needs.
4. Create the Lambda (Python runtime from the source, handler `lambda_function.handler`), upload `matrix-lambda.zip`, set the env vars.
5. CloudFormation: `infra/matrix-iam-executor.yaml` with `TrustedLambdaRoleArn` = the role from step 3.
   Put `ExecutorRoleArn`, `InstanceProfileName`, `AuditLogGroupName` into the Lambda env vars.
   Leave `EnableDecommissionRole=false` unless you want the agent to terminate servers (see `tool-catalog.md`).
6. CloudFormation: `infra/matrix-playbook.yaml` (SSM documents).
7. CodeBuild project for `TF_PROJECT` (only if you use Terraform deployment).
8. Lambda Function URL: auth NONE (the app signs users in itself); set CORS to the website URL.
9. Front end: CloudFormation `infra/matrix-s3.yaml`, then upload `frontend/matrix-ui.html` as `index.html`.
10. EventBridge schedule for the learning scan.
11. A test EC2 server (for example `matrix-linux-01`) tagged `matrix-managed=true`, `environment=<ENVIRONMENT>`, with the new instance profile and the SSM agent.
12. Enable Cost Explorer for the Dashboard cost card.
13. Tag every server MATRIX should manage with `matrix-managed=true` and `environment=<ENVIRONMENT>`.

## 3. Cutover safety
- The same ServiceNow instance means the old and new Lambdas would both act on incidents. Disable the old EventBridge rule and the old
  agent's polling at cutover. Retire the old Lambda after a soak period.
- Generate new `TOKEN_SECRET`, `AGENT_KEY` and user passwords in the new account. Do not reuse the old ones.
- Keep keys in Lambda environment variables or Secrets Manager. Never commit them.
- Rollback: the old account stays untouched until the new one passes the checks below.

## 4. Verify
1. Open the S3 website URL, sign in with the Function URL and a `USERS` login.
2. Dashboard: no "ServiceNow is not connected" banner, incidents load.
3. Chat: "health check matrix-linux-01" works with no LLM error. Observability shows the primary and the standbys.
4. Chat: "scan matrix-linux-01 for missing patches" then a patch install request. The agent raises a CHG, waits for human approval in
   ServiceNow, then reaches the Confirm button.
5. Chat: "plan a new server called test-01, 2 vCPU 4 GB" shows a plan; decommission assess on a throwaway server shows warnings.
   `decommission_terminate` must refuse without the backup, the hold period and the human tag.
6. Work notes appear on the tickets, and the audit log group receives entries.
7. The Dashboard cost card fills in. The Lambda's CloudWatch logs show no errors.

## 5. Tests in this repo
From the repo root: `python -m unittest discover -s tests -v`. They run offline (AWS and ServiceNow are stubbed) and check the
change gate, the decommission safety rules, tool registration, tool routing and LLM key failover.
