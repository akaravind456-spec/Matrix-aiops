# MATRIX: Cybersecurity and AI Observability

| Field | Value |
|---|---|
| Document ID | MTX-04 |
| Owner | MATRIX product owner |
| Version / status | 0.1 / Draft |
| Classification | Customer-shareable after review |
| Effective date | 18 November 2026 |
| Applies to | MATRIX AIOps (this repository, `main`), single Lambda in the customer's AWS account |
| Companion documents | MTX-01 (problem and approach), MTX-02 (product), MTX-03 (deployment, cost, support) |
| Detail behind this summary | SEC-001 (threat model), RSK-001 (stop procedure), AIG-001 (agent behavior) |

**Status of the ratings.** The ratings below are our own assessment from a desk review of the design and the code. No
independent review and no penetration test has been done. We state the known gaps plainly (sections 5 and 6), because a
diagram does not make a system safe; the controls do.

# Part A: Cybersecurity

## 1. What we protect

| Asset | Why it matters |
|---|---|
| The servers MATRIX can act on | A wrong action causes an outage or data loss |
| ServiceNow data and the integration account | Tickets, CMDB and knowledge; the account can write all of them |
| Model and AWS credentials | Misuse costs money and gives access |
| Ticket text, logs and tool output | May hold personal or sensitive data, and goes to the model provider |
| The console and its sign-in accounts | The way a person approves a fix |
| The record of what was done | Evidence of who did what |

## 2. Security by design

| Principle | How it is applied |
|---|---|
| The platform decides, the model does not | A closed fix list, allow-lists for services, and a check of every proposal against real tool output. The model cannot add a capability |
| Least authority | Only servers tagged `matrix-managed=true` with the right `environment`. The role MATRIX assumes cannot act on anything else |
| Hard limits in AWS | The executor role denies terminate, delete volume, security-group, IAM and resize changes. This is enforced by AWS, so "do it anyway" does nothing |
| Humans approve risk | Killing a process, and any change outside the low-risk development rule, needs an engineer's Confirm. The agent's own identity cannot approve |
| Never mark your own work | After a fix MATRIX re-measures. The alarm, the incident and the notes remain as a second check |
| Fail closed | If ServiceNow cannot confirm a valid ticket, the action is refused |
| Evidence for everything | Notes on the ticket, an audit log entry per action, and a trace per model call |
| No inbound access to servers | Systems Manager only. No SSH, no open ports |

## 3. Trust boundaries and their controls

| # | Boundary | Control at the boundary |
|---|---|---|
| B1 | Browser to the Function URL | HTTPS, a signed token (HMAC-SHA256), every action except sign-in needs a token |
| B2 | Lambda to the model provider | HTTPS and an API key per model. Prompts are **not** redacted |
| B3 | Lambda to ServiceNow | HTTPS, an integration user. The tools only write incidents, notes, knowledge and related records |
| B4 | Lambda to servers | Assume-role, Systems Manager, tag conditions, command classes (read-only, mutating, blocked), a never-kill list |
| B5 | Alarm to Lambda | EventBridge invokes the function by permission |

## 4. Threats and residual risk

H high, M medium, L low: the risk left after the control.

| Threat | Main control | What is left | Rating |
|---|---|---|---|
| The model proposes a destructive or invented action | Three fixes only; service, process ID and name checked against real output; never-kill list; Confirm | A wrongly chosen restart of a listed service | L |
| Prompt injection through alarm, ticket, log or article text | Only allow-listed tools; proposals vetted in code; closed fix list; Confirm for writes | Injected text can mislead a diagnosis or the "recovered" judgement, but cannot create a new capability. Testing is thin | M |
| A fix wrongly judged successful | The alarm stays in ALARM if it failed; the incident and notes remain | The check uses a language model; a wrong "yes" is possible | M |
| Actions on servers not meant to be touched | Tag conditions in IAM; Systems Manager only | Anyone who can add the tag brings a server into scope | L |
| Terminate, resize or IAM damage | `NeverAllow` in the executor role; optional separate decommission role needing a human tag and a hold period | | L |
| Planned work without authority | Approved change (or open incident) plus Confirm | **In incident mode the engineer's Confirm is the only approval** | L to M |
| Credential leakage | Secrets never committed; notes mask passwords, tokens and keys; learning checks block secrets | **Open.** Secrets are Lambda settings, readable by anyone with configuration access | H until moved |
| Weak console sign-in | Signed tokens; service token compared in constant time | **Open.** Passwords sit in the `USERS` setting in clear text; no single sign-on; no multi-factor; no lockout | H |
| Public Function URL abuse | A valid token for every action | **Open.** No network restriction; `ALLOWED_ORIGIN` is `*` by default; brute force and denial of wallet are possible | M |
| Sensitive data sent to a model provider | Only what the investigation needs is sent | **Open.** Unredacted; free providers may keep prompts | M to H |
| Over-broad ServiceNow account or Lambda role | Named actions on named resources | The account's roles are the real limit; review every quarter | M |
| Dangerous learned playbooks | Automatic checks; a human approves; learned playbooks never join the agent's allow-list | A reviewer must read every command | L to M |
| Tampered code or settings | Changes are deployed by hand | **Open.** No signing or pipeline; anyone with Lambda edit rights can change behaviour | M |
| Runaway cost | Duplicate guard; per-sweep cap; model cooldowns | Set an AWS Budget | M until set |
| Loss of the audit trail | Notes in ServiceNow; audit log group; traces for 30 days | Set log retention to meet your policy | M |

**No sandbox.** Commands run on the managed server through Systems Manager as the scoped role. MATRIX does not isolate
execution. The controls are the closed fix list, the vetting step, the tag scope, the never-kill list and the approval
gates.

## 5. Customer responsibilities
1. Rotate every key and password that was shown in chat, a ticket or a repository.
2. Move secrets to AWS Secrets Manager or Parameter Store when you can.
3. Set `ALLOWED_ORIGIN` to the console's address, and consider CloudFront with AWS WAF.
4. Limit who can edit the Lambda and its role, and who can create the `matrix-managed` and `decommission-approved` tags.
5. Give the ServiceNow integration user only the roles it needs.
6. Set AWS Budgets, and log retention that meets your policy.
7. Pick model providers whose data terms you accept.
8. Review the Lambda role and ServiceNow account every quarter.

## 6. Top residual risks
1. Secrets are Lambda settings, and console passwords are clear text with no multi-factor sign-in.
2. Prompts are not redacted, so ticket text goes to the model provider as written.
3. Prompt-injection testing has not been done beyond design review.
4. Deployment is by hand, with no signing.
5. The stop procedure and a restore have not been rehearsed.

## 7. Stopping the agent

Use the lowest level that contains the problem. Each level includes the ones above it. Stopping never loses tickets: the
sweep picks up missed alarms when automatic mode is turned back on. The steps have not been rehearsed as a drill.

| Level | What to do | Effect | Time |
|---|---|---|---|
| 1 | Disable the EventBridge rules `matrix-alarm-to-incident` and `matrix-alarm-sweep` | No new incidents or agent runs from alarms. Chat still works | 1 min |
| 2 | Clear `AGENT_KEY` in the Lambda settings | Incidents may be created, but the agent never starts | 2 min |
| 3 | Set `LearnScan` to `DISABLED` | No new drafts | 2 min |
| 4 | Attach a deny-all policy to the executor role | The Lambda can no longer act on any server | 3 min |
| 5 | Throttle the Lambda (reserved concurrency 0) | Every request, including the console, is rejected | 1 min |
| 6 | Delete the Function URL and disable the model keys | No one can reach the function; models stop answering | 5 min |
| 7 | Deactivate the ServiceNow integration user | Nothing can be read or written there | 2 min |

For a suspected leak do level 5 first, then rotate every secret before turning anything back on. Level 4 does not depend on
MATRIX working, so use it if the application itself is suspected.

**Which actions can be undone.** Restarting a service is reversible. Clearing logs and killing a process are not. A patch has
a rollback image made first. No other action has an automatic rollback.

# Part B: AI observability

## 8. What we can see

One agent action, six stages. Blue = decided by code. Amber = the model chooses within what code allows. Green = a person decides.

| # | Stage | Decided by | Evidence kept |
|---|---|---|---|
| 1 | Trigger and detect: an alarm, or an engineer's chat request | Code | Inbox event, incident |
| 2 | Classify and decide: the runbook and the host come from the alarm and the CMDB; the model chooses among the allowed read tools | Code and model | Trace of each model call |
| 3 | Validate: the proposal is checked against the real tool output, the allow-lists and the never-kill list | Code | Vetting result on the incident |
| 4 | Approve and execute: a person confirms unless the low-risk or known-pattern rule applies | Person (or code, under the rule) | Approval record, audit entry |
| 5 | Verify: wait about 15 seconds, measure again, model judges recovery, alarm lag is ignored | Code and model | Verdict in the work notes |
| 6 | Audit and learn: every step recorded; a draft article for a person to approve | Code and person | Work notes, audit log, learning draft |

Observability here means being able to answer, for any ticket: what did the AI see, what did it decide, who approved it, what
did it do, and did it work?

| Question | Where the answer is |
|---|---|
| What did the agent do on this ticket? | The incident's work notes, step by step, and the trace of each model call |
| Who approved it? | The approval card and the audit log entry, with the person's name |
| Which model answered, and how? | Observability page: model, tokens in and out, time, error, and the state of every model in the chain |
| Did the fix hold? | The re-measure result and verdict in the notes, and the alarm state |
| What did it cost? | Dashboard: model cost from token prices, AWS cost before credits |
| Which models are healthy? | Observability, the model chain, showing cooling and parked models |

## 9. Signals

| Signal | What it covers |
|---|---|
| Traces | One record per model call: model, tokens, time, result. Kept 30 days |
| Inbox events | What happened and when: incident opened, fix applied, escalated. Kept 30 days |
| Logs | The Lambda log, with `MATRIX-ALARM-INTAKE` and `MATRIX-ALARM-SWEEP` result lines |
| Audit | One CloudWatch log entry for every action on a server |
| Notes | Written on the ServiceNow ticket, with secrets masked. The permanent record |

There are no alert emails yet. Send Lambda error alarms to a monitored place, and watch the dashboard daily.

## 10. Controlling and measuring the AI

| Control | What it limits or shows |
|---|---|
| Closed fix list | The agent can only restart a listed service, clear old logs or kill one process |
| Run cap | At most `ALARM_MAX_PER_RUN` new incidents per sweep (default 5) |
| Duplicate guard | One open incident per alarm |
| Step limit | The diagnosis stops after at most 8 steps |
| Model failover and cooldowns | A failing model is skipped. Rate-limited models cool down; rejected or missing models are parked for 10 minutes |
| Price table | `LLM_PRICES` turns tokens into dollars. An unpriced model is shown as "price not set" |
| Learning checks | Secrets, dangerous commands and incomplete articles block a draft. A person approves. The system cannot approve its own draft |

## 11. Evidence of quality so far

| Evidence | What it covers | Result | Limit |
|---|---|---|---|
| Automated tests | 52 offline tests: alarm intake and duplicates, gateway failover and 404 handling, incident mode, and other logic | All passed on the last run | The models, ServiceNow and AWS are simulated |
| Real incidents | Alarm to ticket to diagnosis to approved fix to escalation, traced end to end (INC0010006 to INC0010008) | Behaved as designed, about three minutes in one run | A handful of events in a development environment |
| Template checks | `cfn-lint` on the templates | Clean | The one-template install has not been rehearsed in a clean account |

**Gaps we know about.** There is no replay test against simulated incidents, so false resolves and false negatives are not
measured. The prompt version is not stamped on each run. Rollback status is not recorded. There is no red team and no
independent review.

## 12. Alignment with the NIST AI Risk Management Framework

"Aligned in design" only. Nothing here is certified or independently assessed.

| Function | What MATRIX does | Gap |
|---|---|---|
| Govern | A closed fix list; the approver is always a person; the system cannot approve its own learning; roles for who changes what | No formal AI risk committee or approval record for the use case |
| Map | Intended use, permitted and prohibited behaviour, trust boundaries, and what data goes to the model | No impact assessment for people affected by an action |
| Measure | Offline tests, a trace of every model call, dashboard rates, notes on every ticket | No red team, no independent review, no replay test |
| Manage | Approval gates, run caps, model failover, a seven-level stop ladder, change history, rollback images for patches | The stop procedure has never been rehearsed; no global alert emails |

## Change history
| Version | Date | Author | Summary | Approval |
|---|---|---|---|---|
| 0.1 | 18 Nov 2026 | Product owner | First draft | Pending |
