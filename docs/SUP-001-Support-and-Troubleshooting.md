# MATRIX: Support and Troubleshooting

| Field | Value |
|---|---|
| Document ID | SUP-001 |
| Owner | MATRIX product owner |
| Approver | `[to be named]` |
| Version / status | 0.1 / Draft |
| Classification | Internal |
| Effective date | 18 November 2026 |
| Review frequency | Monthly for the first quarter, then every quarter, and after every new kind of fault |
| Applicable product version | MATRIX AIOps (this repository, `main`) |
| Related | DEP-001 (deployment), RSK-001 (stop procedure), ARC-001 (architecture), `env-template.md` |

## 1. Who supports what

| Level | Who | Handles |
|---|---|---|
| 1 | Console users (L1/L2 engineers) | How to use the console, approving, taking ownership, reading the dashboard |
| 2 | Platform owner | The Lambda, settings, models, EventBridge, IAM, deploys, ServiceNow integration |
| 3 | Developer of the code | Bugs in the code, new tools, design changes |

Targets for response and fix times are not committed yet: `[to be decided]`. Suggested severities:

| Severity | Meaning | Example |
|---|---|---|
| 1 | MATRIX acts wrongly or cannot be stopped | A wrong fix was applied: use RSK-001 first |
| 2 | MATRIX is down, no alarms become incidents | "API fetch failed" for everyone |
| 3 | A feature fails or a model is down but work continues | Dashboard cost empty, one standby model failing |
| 4 | A question or a request | How to add a runbook |

## 2. Where to look first

| What | Where |
|---|---|
| The Lambda's own log | CloudWatch, log group `/aws/lambda/<function name>`, newest stream |
| Alarm intake results | The same log, lines starting `MATRIX-ALARM-INTAKE` or `MATRIX-ALARM-SWEEP` |
| What the agent did | The incident's work notes in ServiceNow |
| Every action taken | The CloudWatch audit log group (`/matrix/executor-audit-<env>`) |
| Model calls, tokens, errors | Console, Observability |
| Which models are healthy | Console, Observability, the LLM chain (shows cooling models) |
| Whether rules fire | EventBridge, the rule, Monitoring tab, Invocations |
| Code loaded correctly | The log line `matrix_change loaded` at start-up |

**Quick health test.** In Lambda, Test tab, run `{"matrix_task": "alarm_sweep"}`. A healthy function returns a JSON result. An
import error means a code file is missing.

## 3. Common problems

| Symptom | Likely cause | What to do |
|---|---|---|
| Console: **"API fetch failed"** at sign-in | The Lambda fails to start. The log shows `Runtime.ImportModuleError: No module named '...'` | A code file is missing or misnamed. Upload the whole zip, or add the named file with the **exact** file name (for example `matrix_alarm_intake.py`). Deploy and test |
| Alarm in ALARM but **no incident** | The EventBridge rule is off or missing; an old alarm action created a ticket first; an open incident for that alarm already exists (the duplicate guard skips it) | Check the rules; remove old alarm actions; resolve the open incident; run the sweep test and read its result line |
| Incident created but **no group and no agent** | An older intake function created it, or `AGENT_KEY` is not set, or the role cannot invoke the function itself | Remove the old trigger; set `AGENT_KEY`; check the role allows `lambda:InvokeFunction` on the function |
| Agent ran but the incident **stays open and is escalated** | The post-fix check judged "not recovered" | Read the last notes. If the problem was fixed, resolve by hand. If the code is older than 18 Nov, update `autonomy.py` (alarm state lag fix) |
| Chat: **"LLM 401"** | A model key is wrong or expired | The slot is skipped for 10 minutes. Fix the key in settings. Observability shows which slot |
| Chat: **"LLM 404: 404 page not found"** | A wrong URL (it must end in `/chat/completions`) or a model name the provider does not have (NVIDIA names start with a vendor, for example `nvidia/...`, `moonshotai/...`) | Correct the model name or URL. Updated code skips the slot and tries the next |
| Chat: **"LLM 429" or models busy** | Rate limits on a free tier | Add a standby on another key or provider; wait a minute |
| Chat asks for a **CHG** and you have no Change module | The default mode needs real changes | Set `CHANGE_MODE=incident`, deploy, start a new chat |
| Deployment says **"Not configured on the Lambda"** | `DEPLOY_SUBNET`, `DEPLOY_SG` or `DEPLOY_PROFILE` is missing | Set them |
| **Approve** is greyed out on a learning draft | The automatic checks blocked it (a secret, a dangerous command, an incomplete article) | Open the draft, read the lines marked with a cross, then **Request changes** or **Reject** |
| Knowledge page shows an error for **ServiceNow** | The integration user lacks a knowledge role, or the knowledge base in `KB_NAME` does not exist | Add the role; create the knowledge base |
| Knowledge page shows an error for **AWS documents** | The role lacks Systems Manager list and read permission | Update the stack from the current template, or add the permission |
| Dashboard cost shows **only EC2**, or "you pay $0" | Credits or the free tier cover everything else; the card shows the gross total and the credits | Read the credits line. Check Cost Explorer is enabled |
| Dashboard **human intervention is 100%** from old records | Old test events count | Set `STATS_SINCE` to a start date, or delete old inbox records |
| **Average time to resolve** looks wrong | It is calculated from resolved ServiceNow incidents, including old ones | Resolve or archive old test tickets, or filter by date `[feature request]` |
| A server is **never touched** | It lacks the `matrix-managed` or `environment` tag, the SSM agent is offline, or its `Name` tag does not match the CI | Fix the tags and the agent |
| Launch fails with **VcpuLimitExceeded** | The AWS account allows only 8 vCPUs for that instance family; running servers already use them | Stop or decommission a server, or ask AWS to raise the limit |
| Cutover or validation fails with **UnauthorizedOperation ... DescribeInstanceStatus** | The executor role is missing that permission | Paste the current `infra/matrix-executor-policy-fixed.json` into the `matrix-executor-dev` policy |
| Console says **"ServiceNow is asleep"** | The free developer instance hibernates | Wake it at developer.servicenow.com, then retry |
| Agent asks for **approval on a dev server** | The server lacks an `environment` tag (either spelling), so it is treated as unknown | Add `environment=dev` |
| Chat cannot sign in or stays on the sign-in page | `USERS` in settings is not a valid JSON array | Fix the JSON; the console is down for everyone until it is valid |
| Many incidents at once | An alarm storm | The sweep creates at most `ALARM_MAX_PER_RUN` per run. Use RSK-001 level 1 if needed |

## 4. How to request help

Include:
1. The time (with time zone) and the incident number.
2. What you expected and what happened, with the exact error text.
3. The relevant log lines from section 2. **Never include keys, passwords or the full settings list.** If a secret was pasted by
   mistake, rotate it.
4. What changed recently (a new code file, a setting, a stack update).

## 5. Routine care

| Task | How often |
|---|---|
| Check the dashboard for escalations and cost | Daily |
| Review learning drafts | As they arrive; weekly at least |
| Check model health and cooling slots | Weekly |
| Review the audit log group | Weekly |
| Rotate keys and passwords | Every 90 days `[to be decided]` |
| Review the Lambda role and ServiceNow account permissions | Quarterly |
| Test the kill switch (RSK-001) | Every six months |
| Re-run the offline tests before every deploy | Every release |

## 6. Known limitations

- No automatic deploy pipeline; changes are pasted into the Lambda.
- Console passwords are stored in settings; there is no single sign-on.
- Autonomous fixes are Linux-only, over Systems Manager.
- The per-team chargeback report is manual (COM-001).
- The one-template install has not been rehearsed in a clean account.
- The hosted console page is plain HTTP (S3 website). HTTPS needs CloudFront, which is not set up.
- Chat answers take 10 to 45 seconds; most of that is the model.
- A resolved or stopped decommission leaves termination as a manual, tag-gated step on purpose.

## Change history
| Version | Date | Author | Summary | Approval |
|---|---|---|---|---|
| 0.1 | 18 Nov 2026 | Product owner | First draft from the faults seen during setup | Pending |
