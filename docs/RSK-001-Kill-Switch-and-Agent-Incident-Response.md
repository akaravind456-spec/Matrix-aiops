# MATRIX: Kill Switch and Agent Incident Response

| Field | Value |
|---|---|
| Document ID | RSK-001 |
| Owner | MATRIX product owner |
| Approver | `[to be named]` |
| Version / status | 0.1 / Draft |
| Classification | Internal. Keep a printed or offline copy |
| Effective date | 18 November 2026 |
| Review frequency | After every use, after a test, and at least every six months |
| Applicable product version | MATRIX AIOps (this repository, `main`) |
| Related | ARC-001, AIG-001, SEC-001, SUP-001 |

**Status.** The steps below follow the AWS console and the settings in this repository. They have not been rehearsed as a drill.
Run a drill in the dev account before you need them.

## 1. When to use this

Stop MATRIX when any of these is true:
- It took a wrong action, or an action you cannot explain.
- It is creating many incidents or taking many actions at once.
- A key, password or token has leaked.
- Model cost is running away.
- A real outage is under way and you do not want an automatic fix touching the servers.

Stopping MATRIX never loses tickets. Alarms and incidents still exist, and the five-minute sweep picks up missed alarms when
automatic mode is turned back on.

## 2. The kill-switch ladder

Start at the lowest step that solves the problem. Each step also includes the ones above it.

| Level | What to do | Effect | Time | Undo |
|---|---|---|---|---|
| **1. Stop new alarm work** | EventBridge: disable the rules `matrix-alarm-to-incident` and `matrix-alarm-sweep` (or update the alarm-events stack with `AlarmRuleEnabled=false` and `SweepEnabled=false`) | No new incidents or agent runs from alarms. Chat still works | 1 minute | Enable the rules |
| **2. Stop the agent starting** | Lambda, Configuration, Environment variables: clear `AGENT_KEY` | Incidents may still be created, but the agent is never started (the log says so). The console still works | 2 minutes | Put the value back |
| **3. Stop learning** | Set `LearnScan` to `DISABLED` in the stack, or disable the learning EventBridge rule | No new drafts. Existing ones stay | 2 minutes | Enable it |
| **4. Take away its hands** | Attach a deny-all inline policy to the **executor role** (`matrix-executor-<env>`), or edit its trust policy to remove the Lambda | The Lambda can no longer act on any server, even if code runs | 3 minutes | Remove the deny |
| **5. Stop everything** | Lambda, **Throttle** (sets reserved concurrency to 0) | Every request, including the console, is rejected | 1 minute | Remove the throttle |
| **6. Remove access** | Delete the Function URL, and disable the model keys at their providers | No one can reach the function, and models stop answering | 5 minutes | Recreate the URL, new keys |
| **7. Cut off ServiceNow** | In ServiceNow, deactivate the integration user (`matrix.ai`) | Nothing can be read or written there | 2 minutes | Reactivate |

**Decommission and termination.** The normal role cannot terminate. If the optional decommission role exists, set
`EnableDecommissionRole=false` and update the stack to remove it.

**For a suspected leak**, do level 5 first, then rotate everything in SEC-001 section 5 before turning anything back on.

## 3. Who can do it

| Level | Who |
|---|---|
| 1 to 3 | The platform owner, or any engineer with the EventBridge and Lambda settings permission |
| 4 to 7 | The platform owner and the AWS account owner |

Keep the names and phone numbers of two people who can do each level: `[to be filled]`.

## 4. Responding to something the agent did

1. **Stop first** (section 2). Do not wait to understand it.
2. **Write down the time** and the incident number.
3. **Collect the evidence** before it expires:
   - The incident's work notes (every step is there).
   - The CloudWatch audit log group (every action).
   - The console's Observability page for the traces (kept 30 days).
   - The Lambda log group for the run.
4. **Make the server safe.** Check its state; for a service or process change, restart or restore by hand. For a patch, a rollback image was made first (the patch tool creates it); restore from it if needed.
5. **Tell people.** The server owner, the service manager, and the security contact if data or credentials are involved.
6. **Find the cause.** Was it a wrong proposal, a wrong judgment of recovery, a bad runbook, a bad learned playbook, or a tag that put a server in scope?
7. **Fix it** and record the fix:
   - A wrong runbook or draft: correct or reject it in the Knowledge page.
   - A server wrongly in scope: remove the `matrix-managed` tag.
   - An unsafe process: add it to the never-kill list in code.
   - An unsafe action: remove it from the fix list or require approval.
8. **Test** the change in dev, then turn automatic mode back on one level at a time.
9. **Write the review**: what happened, why, what changed (section 6).

## 5. Turning automatic mode back on

1. Rotate any key that was involved. Confirm the cause is fixed.
2. Enable the learning scan last. Enable the alarm sweep before the instant rule if you want a gentler restart.
3. Watch the first three incidents end to end: the ticket, the notes, the verification, the resolution.
4. Raise the cap (`ALARM_MAX_PER_RUN`) only after the first week is clean.

## 6. Review record

| Date | Level used | What happened | Cause | Change made | Reviewed by |
|---|---|---|---|---|---|
| `[date]` | | | | | |

## Change history
| Version | Date | Author | Summary | Approval |
|---|---|---|---|---|
| 0.1 | 18 Nov 2026 | Product owner | First draft | Pending |
