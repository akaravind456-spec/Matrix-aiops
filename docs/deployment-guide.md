# Lift and shift guide: moving MATRIX into a new AWS account

Same region as the source account, same ServiceNow instance. Everything is done from the AWS console (CloudFormation, S3, Lambda).
Do the steps in order. Each "stack" is a file in `infra/` that you upload in CloudFormation, Create stack, With new resources.

## 0. Collect from the source account (read-only, into a private note)
In the source Lambda, Configuration tab: environment variables, timeout and memory, the execution role's policy JSON, Function URL and CORS.
Also note: the EventBridge rule that sends `{"matrix_task":"learn_scan"}`, the `OPS_BUCKET` runbooks, the CodeBuild project named in `TF_PROJECT`,
and any OTHER Lambda in that account with an SNS trigger. That one is the alarm ingest function (`INGEST_URL`). It is not in this repo, so download its code
from the source console (Lambda, Code tab, Download) and keep a copy.
Compare the source role's policy with `infra/matrix-core.yaml`; add any permission the template misses.

## 1. Build the zip
`Compress-Archive -Path lambda\*.py -DestinationPath dist\matrix-lambda.zip -Force` (the .py files must be at the top level of the zip).

## 2. Create the stacks (same region, in this order)
| # | Template | Needs | Gives you |
|---|---|---|---|
| 1 | `matrix-table.yaml` | nothing | projects, sessions and usage tables |
| 2 | `matrix-core.yaml` | nothing | trace table, ops bucket, artifact bucket, log group, **Lambda role** |
| 3 | `matrix-iam-executor.yaml` | `TrustedLambdaRoleArn` = role from #2 | executor role, instance profile, audit log. Leave `EnableDecommissionRole=false` |
| 4 | `matrix-playbook.yaml` | nothing | SSM playbooks |
| 5 | `matrix-s3.yaml` | a unique bucket name | the website bucket. Note its WebsiteURL |
| 6 | `matrix-app.yaml` | outputs of #2, #3 and #5, plus your secrets | the Lambda, its Function URL, the learning schedule |

Between #2 and #6:
- Upload `dist/matrix-lambda.zip` to the artifact bucket (the `ArtifactBucketName` output of #2).
- Upload the runbooks copied from the source to the ops bucket (`OpsBucketName`).
- Upload `frontend/matrix-ui.html` to the website bucket from #5 as `index.html`.

In #6 you type the secrets into the NoEcho parameters: ServiceNow password, a NEW `TokenSecret` (32+ characters), a NEW `AgentKey`, the LLM keys.
The `FunctionUrl` output is what you paste into the console sign-in page.

## 3. Things the templates do not create
- A test EC2 server (for example `matrix-linux-01`): tag `matrix-managed=true` and `environment=<ENVIRONMENT>`, attach the instance profile from #3, SSM agent running.
- The alarm ingest function and its SNS topic (see step 0). Set its URL in the app stack's `IngestUrl`.
- Optional: a CodeBuild project named `matrix-...` for Terraform (`TfProject`); an operator role for the chat tool `aws_write` (`OperatorRoleArn`). Without it `aws_write` stays off.
- Cost Explorer: enable it once in the new account (Billing console).

## 4. Cutover safety
- The same ServiceNow instance means the old and new agents would both act on incidents. Deploy the new app with `LearnScan=DISABLED`, finish testing,
  then disable the old account's EventBridge rule and Function URL and set `LearnScan=ENABLED`.
- New `TokenSecret`, `AgentKey` and passwords. Never reuse the old ones.
- Rollback: delete the new stacks (empty the buckets first). The source account is untouched until you retire it after a soak period.

## 5. Verify
1. Lambda, Test tab, send `{"matrix_task":"nothing"}`; the CloudWatch log shows no import error.
2. Open the website URL, sign in with the Function URL and a user from `UsersJson`.
3. Dashboard: no "ServiceNow is not connected" banner, incidents load.
4. Chat: "health check matrix-linux-01" works with no LLM error. Observability shows traces and the LLM chain (primary plus standbys).
5. "scan matrix-linux-01 for missing patches", then ask for a patch install: the agent raises a CHG, waits for approval in ServiceNow, then shows Confirm.
6. "plan a new server called test-01, 2 vCPU 4 GB" shows a plan; decommission assess on a throwaway server shows warnings;
   `decommission_terminate` refuses without the backup, the hold period and the human tag.
7. Work notes appear on tickets; the audit log group receives entries; the Dashboard cost card fills in.

## 6. Tests and lint in this repo
`python -m unittest discover -s tests -v` (offline; AWS and ServiceNow are stubbed) and `cfn-lint infra/*.yaml`.
