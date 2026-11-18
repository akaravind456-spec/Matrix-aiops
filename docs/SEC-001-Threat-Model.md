# MATRIX: Threat Model

| Field | Value |
|---|---|
| Document ID | SEC-001 |
| Owner | MATRIX product owner |
| Approver | `[to be named]` (security review recommended) |
| Version / status | 0.1 / Draft |
| Classification | Internal. Do not share outside the organisation |
| Effective date | 18 November 2026 |
| Review frequency | At every release, after any security incident, and at least every six months |
| Applicable product version | MATRIX AIOps (this repository, `main`) |
| Related | ARC-001 (controls), AIG-001 (agent behavior), RSK-001 (stop procedure), DEP-001 (deployment) |

**Status.** This is a desk review of the design and the code. It has not been checked by a penetration test. Items marked
**Open** are weaknesses that exist today.

## 1. What we protect

| Asset | Why it matters |
|---|---|
| The servers MATRIX can act on | A wrong or malicious action causes an outage or data loss |
| ServiceNow data and the integration account | Tickets, CMDB, knowledge; the account can write all of them |
| Model and AWS credentials | Misuse costs money and gives access |
| Ticket text, logs and tool output | They can contain personal or sensitive data and they go to the model providers |
| The console and its sign-in accounts | The way a person approves a fix |
| The record of what was done | Needed to prove who did what |

## 2. Who might attack, or fail

| Actor | Example |
|---|---|
| Outsider on the internet | Finds the public Function URL and guesses passwords |
| Malicious or careless insider | An engineer approving too fast, or someone with AWS access reading settings |
| Poisoned input | Alarm text, ticket text, log lines or a knowledge article that tries to steer the model |
| The model itself | Makes a wrong or invented proposal |
| A supplier | A model provider or a code package that misbehaves |

## 3. Threats and controls

| # | Threat | Control today | Residual risk |
|---|---|---|---|
| 1 | The model proposes a destructive or invented action | Fixed three-fix list; code vets service, PID and name against real tool output; never-kill list; Confirm for anything not low-risk dev or a known pattern | Low. The worst fix is one wrongly-chosen service restart or a kill of a listed-safe process |
| 2 | **Prompt injection**: text in an alarm, ticket, log or article tells the model to do something else | The model can only call the allow-listed tools; proposals are vetted in code; the fix list is closed; write tools need Confirm | Medium. Injected text can mislead a diagnosis or the "recovered" judgment, but cannot create new capabilities |
| 3 | A fix is wrongly judged as successful | The incident, alarm and work notes remain; a failed fix leaves the alarm in ALARM | Medium. See AIG-001 section 7 |
| 4 | Actions on servers that are not meant to be touched | Role conditions on tags `matrix-managed=true` and `environment`; SSM only; no inbound ports | Low, if tags are managed carefully. **Anyone who can add the tag to a server brings it into scope** |
| 5 | Termination, resize or IAM damage | `NeverAllow` in the executor role (terminate, delete volume, security-group and IAM changes, resize); a separate optional role for termination needing a human tag and a hold period | Low |
| 6 | Planned work without authority | Approved change (or open incident in incident mode) plus Confirm; the ticket is checked in ServiceNow | Low in change mode. **In incident mode the engineer's Confirm is the only approval** |
| 7 | **Credential leakage**: keys and passwords in settings, chat or a repository | Secrets are never committed; work notes mask password, token and key patterns; learning checks block secrets | **Open.** Secrets are Lambda environment variables, readable by anyone with configuration access. Keys have been pasted into chat during development and must be rotated (section 5) |
| 6a | Weak console sign-in | Signed tokens (HMAC-SHA256); the service token is compared in constant time | **Open.** Accounts and passwords are stored in the `USERS` setting in clear text; no single sign-on or multi-factor sign-in; no lockout is documented |
| 7 | Public Function URL abuse | Every action except sign-in needs a valid token; the service token needs `AGENT_KEY` | **Open.** The URL has no network restriction and `ALLOWED_ORIGIN` is `*` by default; brute force and denial of wallet (model cost) are possible |
| 8 | Sensitive data sent to a model provider | Only what the investigation needs is sent; free providers may keep prompts | **Open.** Ticket text and tool output go to the provider unredacted; use providers whose terms you accept |
| 9 | Over-broad ServiceNow account | The tools write only incidents, work notes, knowledge, CMDB status and related records | Medium. The account's roles are the real limit; keep its ACLs tight |
| 10 | Over-broad Lambda role | The template grants named actions on named resources; the role cannot assume other roles beyond the executor | Medium. Review the role after every change; new features add permissions |
| 11 | Learned playbooks that are dangerous | Automatic checks block secrets and dangerous commands; a human approves; learned playbooks are not added to the agent's allow-list | Low to medium. A reviewer must read every command |
| 12 | Tampered code or settings | Changes are deployed by hand into the Lambda | **Open.** No code signing or deployment pipeline; anyone with Lambda edit rights can change behavior |
| 13 | Runaway cost (loops, alarm storms, model charges) | Duplicate guard and a per-sweep cap; model failover has cooldowns; a budget alert is recommended (COM-001) | Medium until budgets are set |
| 14 | Loss of the audit trail | Work notes in ServiceNow, an audit log group, traces for 30 days | Medium. Set log retention to meet your policy |
| 15 | The ticketing system is down or wrong | A ServiceNow failure fails closed: the gate refuses to act without a valid ticket | Low |

## 4. Data flows and trust boundaries

| Flow | Boundary crossed | Protection |
|---|---|---|
| Browser to Function URL | Internet to Lambda | HTTPS, signed token |
| Lambda to model provider | Account to a third party | HTTPS, API key, redaction is **not** applied |
| Lambda to ServiceNow | Account to your instance | HTTPS, basic authentication of the integration user |
| Lambda to servers | Account to EC2 | Assume-role, SSM, tag conditions |
| Alarm to Lambda | AWS to AWS | EventBridge invokes the function by permission |

## 5. Recommended actions (in priority order)

1. **Rotate every key and password that has been shown in chat, a ticket or a repository** (model keys, ServiceNow password, console passwords, `TOKEN_SECRET`, `AGENT_KEY`).
2. **Move secrets to AWS Secrets Manager or SSM Parameter Store** and read them at start-up, so they are not in the function's settings.
3. **Hash console passwords or add single sign-on**, and add multi-factor sign-in for the approvers.
4. **Restrict the Function URL**: set `ALLOWED_ORIGIN` to the console's address, put the console behind CloudFront and AWS WAF or a private network, and add rate limits.
5. **Set AWS Budgets and Lambda concurrency limits** so a loop cannot run up cost (COM-001).
6. **Deploy from a pipeline** with code review and signing, not by pasting files.
7. **Apply least privilege review** to the Lambda role and the ServiceNow account every quarter.
8. **Tag control**: limit who can create the `matrix-managed` and `decommission-approved` tags.
9. **Set retention** on the audit log group and decide who reviews it.
10. **Run a penetration test and a prompt-injection test** before widening the scope to production.

## 6. Review log

| Date | Reviewer | Result |
|---|---|---|
| `[date]` | `[name]` | `[not yet reviewed]` |

## Change history
| Version | Date | Author | Summary | Approval |
|---|---|---|---|---|
| 0.1 | 18 Nov 2026 | Product owner | First draft from the code and templates | Pending |
