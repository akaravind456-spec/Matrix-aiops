# MATRIX: Deployment Model

| Field | Value |
|---|---|
| Document ID | DEP-001 |
| Owner | MATRIX product owner |
| Approver | `[to be named]` |
| Version / status | 0.1 / Draft |
| Classification | Internal; shareable after review |
| Effective date | 18 November 2026 |
| Review frequency | At every release, and after any change to the templates or settings |
| Applicable product version | MATRIX AIOps (this repository, `main`) |
| Related | PRD-001 (overview), ARC-001 (architecture), RSK-001 (stop procedure), SUP-001 (support), `deployment-guide.md` (click-by-click steps), `env-template.md` (settings) |

**Status.** Figures marked `[to be measured]` have not been measured on a production-sized system. The one-template install
(`matrix-all.yaml`) has been linted and unit-checked offline; the live deployment in the dev account was built from the
separate stacks plus hand-edited Lambda code, so a clean-account install from the single template is still to be rehearsed.

## 1. Deployment options

| | One template (recommended) | Separate stacks | Hand-built |
|---|---|---|---|
| What you use | `infra/matrix-all.yaml` | The six files in `infra/` in order | Lambda, roles and rules created in the console |
| Effort | One upload, one form | Six uploads | Most work, easiest to get wrong |
| Best for | A new account or a clean rebuild | Debugging one piece | Not advised |
| Optional add-on | `infra/matrix-alarm-events.yaml` for alarm triggers | Same | Same |

The code is one zip (`dist/matrix-lambda.zip`, all `.py` files at the top level) read from an S3 bucket you create first.

## 2. What runs where

| Component | Location | Notes |
|---|---|---|
| MATRIX Lambda | Your account, one region | Python 3.12, handler `lambda_function.handler`, Function URL (public address, app-level sign-in), 512 MB, timeout of 300 seconds recommended |
| DynamoDB tables | Same region | Trace table (traces, inbox, approvals, learning drafts, with expiry) plus projects, sessions and usage tables |
| Ops bucket | S3 | Runbooks and the knowledge index (`kb/index.json`); kept on stack delete on purpose |
| Executor role and instance profile | IAM | Scoped by tags; the role MATRIX assumes to act on servers |
| Audit log group | CloudWatch Logs | One entry for every action taken |
| SSM documents | Systems Manager | The `MATRIX_*` playbooks, plus learned (`MATRIX-LEARNED-*`) and uploaded (`MATRIX-PB-*`) ones |
| EventBridge rules | Same region | Alarm-to-incident, five-minute sweep, optional learning scan |
| Web console | `frontend/matrix-ui.html` | Opened from a PC, or hosted in S3 for a team (`matrix-s3.yaml`) |
| Model APIs | The providers you choose | Prompts and tool output are sent to them |
| ServiceNow | Your instance | Needs an integration user |

## 3. Network connections

| From | To | Purpose |
|---|---|---|
| MATRIX Lambda | Model APIs (HTTPS 443) | Prompts and answers |
| MATRIX Lambda | ServiceNow (HTTPS 443) | Tickets, CMDB, knowledge |
| MATRIX Lambda | AWS APIs | EC2, SSM, CloudWatch, DynamoDB, S3, Cost Explorer |
| Servers | AWS Systems Manager | The SSM agent calls out; **no inbound port is opened** |
| Browser | Function URL (HTTPS) | Console API |
| EventBridge | MATRIX Lambda | Alarm events and schedules |

There is no VPC attachment, so the Lambda reaches ServiceNow over the internet. If your ServiceNow instance is private, a different network design is needed.

## 4. Requirements

| Item | Requirement |
|---|---|
| AWS | One account, one region, an administrator to run CloudFormation with IAM permissions; Cost Explorer enabled once in the Billing console |
| ServiceNow | An integration user (incident read/write, CMDB read, knowledge write if uploads are used); the assignment groups `MATRIX-AI-L1` and the L2 group; a knowledge base named in `KB_NAME` |
| Models | A primary API key and model ID. At least one standby on a different key or provider is strongly advised |
| Managed servers | Linux, SSM agent running, instance profile from the stack, tags `matrix-managed=true` and `environment=<your Environment value>`, and a `Name` tag that matches the CMDB CI name |
| Secrets | A new `TokenSecret` and `AgentKey` (32 or more random characters each); never reuse another account's values |

## 5. Sizing and capacity

MATRIX has no servers to size. What scales is the model traffic and the Lambda time.

| Observed in the dev account over 7 days | Value |
|---|---|
| Model calls | 129 across three models |
| Tokens sent / received | about 439,000 / 25,800 |
| One observed agent run | about 3 minutes from ticket creation to escalation (it included a human approval) |
| Other AWS services in the whole account | about $0.94 gross (CloudWatch, Cost Explorer, Secrets Manager, S3, DynamoDB, API Gateway); Lambda did not appear, so it stayed in the free tier |

Planning points:
- A run makes several model calls. Burst traffic, not the daily total, is what hits rate limits. The NVIDIA free tier allows about 40 requests a minute, so a storm of alarms needs a standby model.
- The alarm sweep processes at most `ALARM_MAX_PER_RUN` (default 5) new incidents per run to prevent a flood.
- Lambda timeout must cover the post-fix wait and the model calls; 300 seconds is the documented setting.
- Larger fleets: `[to be measured]`.

## 6. Environments

| Environment | Guidance |
|---|---|
| Dev | The `Environment` value `dev`. Low-risk fixes (service restart, log cleanup) may run automatically here |
| Test / prod | Use a separate stack per environment. Fixes on non-dev servers wait for human Confirm; planned work needs a ticket |
| New AWS account | Follow `deployment-guide.md` (lift and shift). Same region and ServiceNow, so only one agent may act at a time during cutover |
| Never | Share `TokenSecret`, `AgentKey` or tables between two stacks |

## 7. Installing, upgrading and removing

**Install.** Create the S3 bucket and upload the zip; create the stack from `matrix-all.yaml` and fill the form; copy the
`FunctionUrl`; open `matrix-ui.html` and sign in; tag a test server; add alarm triggers with `matrix-alarm-events.yaml`
(or the two EventBridge rules by hand). Full steps are in `deployment-guide.md`.

**Settings.** Environment variables are listed in `env-template.md`. Set `CHANGE_MODE=incident` if ServiceNow has no Change module.

**Upgrade.** Replace the Lambda code (upload the new zip, or paste the changed files with every new file included) and
click Deploy; update the stack when `infra/` changed. Roll back by uploading the previous zip. Always run the Test event
and check the log for an import error. A missing module breaks every request and the console shows "API fetch failed".

**Remove.** Disable the EventBridge rules first. Delete the stack. Empty the ops bucket first if you want it removed. The
learning drafts and traces expire on their own.

## 8. Backup, recovery and availability

- **State.** Nearly everything lives in DynamoDB, S3 and ServiceNow, all managed services. The Lambda holds no state.
- **Recovery.** Redeploy the stack and the code; settings are in the stack parameters. Learning drafts, approvals and traces
  expire after 30 days by design; the ServiceNow tickets and work notes are the permanent record.
- **Availability.** Lambda runs across the region's zones. If MATRIX is down, alarms and tickets still exist and the sweep
  recovers missed alarms when it is back; nothing is lost. There is no multi-region failover.
- **Point-in-time recovery** is switched on for the trace table. A restore rehearsal has not been done `[to be decided]`.

## 9. Securing the deployment

1. Use new secrets in every account and rotate any key that has been pasted into chat, tickets or a repository.
2. Keep secrets out of the repository; today they are Lambda environment variables (see SEC-001 for the stronger option).
3. Give the ServiceNow integration user only the roles it needs.
4. Leave `EnableDecommissionRole` off unless a decommission is planned.
5. Set `ALLOWED_ORIGIN` to the console's address once it is hosted, instead of `*`.
6. Restrict who can edit the Lambda and its role in AWS.
7. Send alerts for Lambda errors to a monitored place.

## 10. Responsibilities

| | Platform owner | Service owner / engineers |
|---|---|---|
| Lambda code, templates, settings, model keys | Yes | |
| AWS account, IAM, budgets and alarms | Yes | |
| ServiceNow groups, integration user, knowledge base | Shared | Shared |
| Runbooks and knowledge quality | | Yes |
| Tagging servers as managed | | Yes |
| Approving fixes and reviewing learning drafts | | Yes |

## Change history
| Version | Date | Author | Summary | Approval |
|---|---|---|---|---|
| 0.1 | 18 Nov 2026 | Product owner | First draft | Pending |
