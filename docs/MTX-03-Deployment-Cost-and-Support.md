# MATRIX: Deployment Strategy, Cost Model and Support Model

| Field | Value |
|---|---|
| Document ID | MTX-03 |
| Owner | MATRIX product owner |
| Version / status | 0.1 / Draft: measured costs and a value method; licence prices are **proposals** in LIC-001, support terms not yet approved |
| Classification | Customer-shareable once approved |
| Effective date | 18 November 2026 |
| Applies to | MATRIX AIOps (this repository, `main`) |
| Companion documents | MTX-01 (problem and approach), MTX-02 (product), MTX-04 (security and AI observability) |
| Detail behind this summary | DEP-001, `deployment-guide.md`, `env-template.md`, COM-001, SUP-001, RSK-001 |

**Status.** Amounts are US dollars, exclude tax and are before credits unless stated. Anything in `[brackets]` is a
commitment that has not been decided. Figures marked "to be measured" have not been measured on a customer-sized system.
Licence plans and proposed prices are in **LIC-001** and summarised in section B1.

# Part A: Deployment strategy

## A1. In your own AWS account only
MATRIX runs in the AWS account that owns the servers, as one Lambda function. There is no vendor-hosted edition. The vendor
never holds your tickets, credentials or audit trail, and has no network path into your environment.

What still crosses your boundary is only what you choose to connect: the model providers you pick (prompts and tool output
go to them) and your ServiceNow instance.

## A2. Ways to install

| | One template (recommended) | Separate stacks | Hand-built |
|---|---|---|---|
| What you use | `infra/matrix-all.yaml` | The six files in `infra/` in order | Console clicks |
| Effort | One upload, one form | Six uploads | Most work, easiest to get wrong |
| Best for | A new account or a clean rebuild | Debugging one piece | Not advised |
| Optional add-on | `infra/matrix-alarm-events.yaml` for alarm triggers | Same | Same |

The code is one zip (`dist/matrix-lambda.zip`, every `.py` file at the top level) read from an S3 bucket you create first.
A missing file breaks every request, and the console shows "API fetch failed", so always upload the whole zip.

## A3. What runs where

| Component | Location | Notes |
|---|---|---|
| MATRIX Lambda | Your account, one region | Python 3.12, 512 MB, 300 second timeout, Function URL |
| DynamoDB tables | Same region | Traces, inbox, approvals and learning drafts (30-day expiry); projects, sessions, usage |
| Ops bucket | S3 | Runbooks and the knowledge index. Kept when the stack is deleted, on purpose |
| Executor role and instance profile | IAM | Scoped by tags. The role MATRIX assumes to act on servers |
| Audit log group | CloudWatch Logs | One entry for every action |
| SSM documents | Systems Manager | `MATRIX_*` playbooks, plus learned and uploaded ones |
| EventBridge rules | Same region | Alarm to incident, five-minute sweep, optional learning scan |
| Web console | `frontend/matrix-ui.html` | Opened from a PC, or hosted in S3 for a team |
| Model APIs | The providers you choose | Prompts go there |
| ServiceNow | Your instance | Needs an integration user |

## A4. Network connections

| From | To | Purpose |
|---|---|---|
| MATRIX Lambda | Model APIs, HTTPS 443 | Prompts and answers |
| MATRIX Lambda | ServiceNow, HTTPS 443 | Tickets, CMDB, knowledge |
| MATRIX Lambda | AWS APIs | EC2, Systems Manager, CloudWatch, DynamoDB, S3, Cost Explorer |
| Servers | AWS Systems Manager | The SSM agent calls out. **No inbound port is opened** |
| Browser | Function URL, HTTPS | Console API |
| EventBridge | MATRIX Lambda | Alarm events and schedules |

There is no VPC attachment, so the Lambda reaches ServiceNow over the internet. A private ServiceNow instance needs a
different network design.

## A5. Requirements

| Item | Requirement |
|---|---|
| AWS | One account and region, an administrator who can run CloudFormation with IAM permissions, Cost Explorer enabled once in Billing |
| ServiceNow | An integration user (incident read and write, CMDB read, knowledge write for uploads); the groups `MATRIX-AI-L1` and the L2 group; a knowledge base named in `KB_NAME` |
| Models | A primary key and model ID, and at least one standby on a different key or provider |
| Managed servers | Linux, SSM agent running, the instance profile from the stack, tags `matrix-managed=true` and `environment=<your value>`, and a `Name` tag that matches the CMDB CI |
| Secrets | A new `TokenSecret` and `AgentKey`, 32 or more random characters each, never reused between accounts |
| Servers to host MATRIX | None. There is nothing to size |

## A6. Rollout plan

| Environment | Guidance |
|---|---|
| Pilot | One stack, a few tagged test servers. Move through the three stages in MTX-01 section 4 |
| Development | `Environment=dev`. Low-risk fixes may run automatically |
| Test and production | A separate stack per environment. Fixes on non-development servers wait for Confirm |
| New account | Follow `deployment-guide.md`. With the same ServiceNow, only one agent may act at a time during cutover |
| Never | Share `TokenSecret`, `AgentKey` or tables between two stacks |

## A7. Install, upgrade, back up, remove

**Install.** Create the bucket and upload the zip. Create the stack from `matrix-all.yaml` and fill the form. Copy the
`FunctionUrl`, open `matrix-ui.html` and sign in. Tag a test server. Add alarm triggers with `matrix-alarm-events.yaml`.

**Upgrade.** Upload the new zip (or paste the changed files with every new file included) and click Deploy. Update the stack
when `infra/` changed. Run the Test event `{"matrix_task": "alarm_sweep"}` and check the log for an import error.

**Roll back.** Upload the previous zip.

**Remove.** Disable the EventBridge rules first, then delete the stack. Empty the ops bucket first if you want it removed.

**Backups and recovery.** The Lambda holds no state. Nearly everything is in DynamoDB (point-in-time recovery on), S3 and
ServiceNow. Redeploy the stack and code to recover. Drafts, approvals and traces expire after 30 days by design, and the
ServiceNow tickets and notes are the permanent record. A restore rehearsal has not been done `[to be decided]`.

**Availability.** Lambda runs across the region's zones. If MATRIX is down, alarms and tickets still exist and the sweep
recovers missed alarms when it is back. There is no multi-region failover.

## A8. Securing the deployment
1. Use new secrets in every account, and rotate any key that was pasted into chat, a ticket or a repository.
2. Keep secrets out of the repository. Today they are Lambda settings (see MTX-04 for the stronger option).
3. Give the ServiceNow integration user only the roles it needs.
4. Leave `EnableDecommissionRole` off unless a decommission is planned.
5. Set `ALLOWED_ORIGIN` to the console's address once it is hosted, instead of `*`.
6. Restrict who can edit the Lambda and its role.
7. Send alerts for Lambda errors to a monitored place.

# Part B: Cost model

## B1. What the customer pays

**Licence (proposed, see LIC-001).** An annual licence by plan, plus support as a percentage. The price follows managed
servers and approver seats. There is no per-ticket or per-token charge, and limits are soft.

| Per year, proposed | Starter | Team | Commander |
|---|---|---|---|
| Managed servers / approver seats | 25 / 2 | 100 / 10 | Unlimited / 50 |
| Licence | $3,600 | $18,000 | $60,000 |
| Standard support (18%) | $648 | $3,240 | $10,800 |

**Running cost in the customer's own account.** Separate from the licence. It has two shared parts and one direct part.

| # | Component | What drives it | Where to read it |
|---|---|---|---|
| A | Platform compute and services | Lambda time, DynamoDB, S3, CloudWatch logs, EventBridge, Cost Explorer calls (about $0.01 each, cached for an hour) | Dashboard cost card |
| B | Model usage | Tokens in and out for each model, times that model's price per million tokens | Dashboard LLM usage table (`LLM_PRICES`) |
| C | Resources MATRIX creates for a team | Servers launched, migration clones, backup images | Cost Explorer, by the tag `matrix-managed=true` and your cost-centre tag |
| | Outside this model | ServiceNow, the teams' own servers, people's time | Their own owners |

## B2. What MATRIX cost in the first measured week

Read from the dashboard of the development account, 12 to 18 November 2026.

| Item | Amount | Note |
|---|---|---|
| Whole account, before credits | $7.78 | Includes the test servers, which are not MATRIX |
| Other AWS services in the whole account | about $0.94 | CloudWatch, Cost Explorer, Secrets Manager, S3, DynamoDB, API Gateway |
| Lambda | $0.00 | Inside the free tier |
| **Model cost** | **$0.05** | 129 calls on a free endpoint plus one paid model at $0.15 in and $0.60 out per million tokens |

**Reading it.** MATRIX's own running cost was well under one dollar that week. At small scale it is cheap. The real
saving is in engineers' time. Leaving the free tiers (Lambda, the free model endpoint, credits) and growth in ticket volume
will change this, so repeat the table for a full month before any decision.

## B3. Chargeback to teams (summary)

Charge from measured data. Pass direct costs (component C) to the owning team through tags. Split the shared platform cost
(A and B) by handled tickets:

```
Team share of platform cost = (platform cost A + B for the month) x (team's handled tickets / all handled tickets)
```

Use costs before credits, so a team is not charged zero today and a surprise later. The monthly worksheet, the unit costs
and the tag set-up are in COM-001. MATRIX does not produce a per-team report yet; it is done by hand.

## B4. The value case

This is a method with stated assumptions, **not a promise**. The pilot measures the real figures from your own data.

| Item | Figure | Source |
|---|---|---|
| Cost of one L1 support engineer, all in | about $65,000 a year | $50,000 base from public 2026 salary sites, plus 30% for tax and benefits (our assumption) |
| Five engineers to cover every hour of the week | about $27,000 a month | Five times the above |
| MATRIX running cost, pilot week | under $1, plus $0.05 for the model | Section B2 |
| Share of repeated work MATRIX takes over | 30% (an assumption to be measured) | |
| Time given back to the team | about $8,000 a month | 30% of $27,000 |

**Method for your own numbers.**

```
Saving = tickets MATRIX resolves without a person x your cost of handling an L1 ticket
Net    = Saving - (platform cost A + B) - the people time spent approving and reviewing
```

Take your service desk's own cost per ticket. Public benchmarks of about $15 to $22 per ticket are old and vary widely, so
use them only if you have no figure of your own. Ignore the time saved on tickets that are diagnosed but still need a person;
it makes the estimate cautious.

## B5. Costs the customer carries outside MATRIX

| Cost | Notes |
|---|---|
| ServiceNow | The instance, licences and any AI add-on from ServiceNow |
| Model providers | Charges above the free tier |
| The servers MATRIX manages | Charged to their teams as before |
| Engineers' time to approve and review | Their own teams |
| AWS support plan | The account owner |

## B6. Controls and open decisions

- Create an AWS Budget for the MATRIX services, with alerts at 80% and 100%.
- Set `LLM_PRICES` for every paid model. A model with no price shows "price not set" and is never counted as $0.
- Decide the allocation driver and the cost-centre tag, and keep them for a year.
- The licence prices in LIC-001 are drafts. Re-check them after the first pilot has measured the real saving, and get finance and legal review before any offer.
- Internal team-to-team charging (not the licence) is covered in COM-001.

# Part C: Support model

## C1. Three tiers

| Tier | Who | Handles | Hands over when |
|---|---|---|---|
| 1 | Your operations team | Daily care: the dashboard, escalations, cost, learning drafts, turning automatic mode off or on, first checks with the Test event and the Observability page | The cause is not something they can fix, or an agent action looks wrong |
| 2 | The platform owner `[team, hours]` | The Lambda, settings, models, EventBridge, IAM, deploys, ServiceNow integration | A defect is suspected |
| 3 | The developer of the code `[lead]` | Defects, new tools, design changes, review after an incident | This is the last tier |

## C2. Severity and response (to be agreed)

| Severity | Meaning (proposed) | First response | Target |
|---|---|---|---|
| 1 Critical | MATRIX acted wrongly or cannot be stopped | `[x minutes]` | Contain at once, then fix |
| 2 High | MATRIX is down and no alarms become incidents | `[x hours]` | `[x]` |
| 3 Medium | A feature fails or a model is down but work continues | `[x business days]` | Next planned release |
| 4 Low | A question or request | `[x business days]` | As planned |

For severity 1 the first move is to stop MATRIX (MTX-04 section 7), before contacting anyone.

## C3. Where to look first

| What | Where |
|---|---|
| The Lambda's own log | CloudWatch, `/aws/lambda/<function name>`, newest stream |
| Alarm intake results | The same log, lines starting `MATRIX-ALARM-INTAKE` or `MATRIX-ALARM-SWEEP` |
| What the agent did | The incident's work notes |
| Every action taken | The CloudWatch audit log group |
| Model calls, tokens, errors, healthy models | Console, Observability |
| Quick health test | Lambda Test event `{"matrix_task": "alarm_sweep"}` |

The common faults and their fixes are in SUP-001 section 3.

## C4. Raising a case
Include the time with time zone and the incident number; what you expected and what happened, with the exact error text; the
relevant log lines; and what changed recently. **Never send keys, passwords, the full settings list or tokens.** If one was
sent by mistake, rotate it.

## C5. What the product gives the support team

| Feature | How it helps |
|---|---|
| Work notes on every ticket | Show what the agent saw, did and decided |
| Audit log group and traces | Every action and every model call |
| Duplicate guard and a per-sweep cap | An alarm storm cannot flood the queue |
| Model failover with cooldowns | One failing model does not stop the work |
| The Test event | Separates a missing file from a product fault |
| A stop ladder with seven levels | Containment in minutes (RSK-001) |

## C6. Responsibilities

| Area | Platform owner | Service owner and engineers |
|---|---|---|
| Lambda code, templates, settings, model keys | Yes | |
| AWS account, IAM, budgets, alarms | Yes | |
| ServiceNow groups, integration user, knowledge base | Shared | Shared |
| Runbooks and their quality | | Yes |
| Tagging servers as managed | | Yes |
| Approving fixes and reviewing learning drafts | | Yes |
| Rotating keys | Yes | |

## C7. Not supported today
- No multi-region failover, and no deployment pipeline (files are pasted or uploaded by hand).
- No single sign-on or multi-factor sign-in for console users.
- No Windows fixes, and no ticketing tool other than ServiceNow.
- A model provider whose terms you do not accept.

## C8. Open decisions
1. Name the tiers 2 and 3 teams, their hours and the contact channel.
2. Set response and update times per severity.
3. Decide the supported-version policy.
4. Decide whether the per-team report is built into the dashboard.
5. Decide any price, after measured data.

## Change history
| Version | Date | Author | Summary | Approval |
|---|---|---|---|---|
| 0.1 | 18 Nov 2026 | Product owner | First draft | Pending |
