# MATRIX: Problem Statement, Approach and Future Scalability

| Field | Value |
|---|---|
| Document ID | MTX-01 |
| Owner | MATRIX product owner |
| Version / status | 0.1 / Draft |
| Classification | Customer-shareable after review |
| Effective date | 18 November 2026 |
| Applies to | MATRIX AIOps (this repository, `main`) |
| Companion documents | MTX-02 (product), MTX-03 (deployment, cost, support), MTX-04 (security and AI observability) |
| Detail behind this summary | PRD-001, ARC-001, AIG-001, DEP-001, COM-001, SEC-001, RSK-001, SUP-001 |

## 1. Problem statement

Most first-line incidents repeat. A service has stopped, a disk is full, or one process is using all the CPU. Every one of
them needs the same first checks before anyone can decide what to do.

That work causes four problems for an operations team:

| Problem | What it looks like |
|---|---|
| Waiting | An alarm sits until an engineer is free. At night the wait is longer, and the fix itself often takes two minutes |
| Inconsistency | The checks and the fix depend on who is on shift and what they remember |
| Missing records | Notes are written afterwards, if at all, so the next engineer starts again |
| Slow approvals | Risky changes are agreed by phone or chat, and the agreement is not recorded where the auditor looks |

Existing tools each solve part of this. A monitoring tool tells you something is wrong. A copilot suggests what you could do.
Neither takes the next step, checks that it worked, and updates the ticket.

**The problem we solve:** shorten the time from an alarm to a verified fix, and remove repetitive work from engineers,
without giving up control or a record of what was done.

## 2. What success looks like

We propose to judge MATRIX on six measures. The dashboard already shows most of them, so nobody has to count by hand.

| Measure | Question it answers | Where it comes from today |
|---|---|---|
| Time to detect | How quickly does an alarm become a ticket? | Alarm time against incident creation time (about a minute by design; not yet reported on the dashboard) |
| Time to resolve | How quickly is it fixed and checked? | Dashboard, average time to resolve |
| Autonomous rate | How many incidents does MATRIX fix by itself? | Dashboard, "Resolved by the agent" |
| Human intervention rate | How many need a person? | Dashboard, escalations |
| Escalations to L2 | How many reach senior engineers? | Dashboard and ServiceNow |
| Cost per ticket | What does each handled ticket cost? | Dashboard cost cards (see COM-001) |

**An honest statement of evidence.** We have not published measured results from a live customer. What exists today is a
working development deployment, 52 automated offline tests, and one traced real incident from alarm to approved fix in about
three minutes. Whether MATRIX improves your numbers is what a pilot is for. We want to prove improvement with your baselines,
not promise it.

## 3. Our approach

We built MATRIX around five decisions.

| # | Decision | Why |
|---|---|---|
| 1 | Work inside the ticketing tool the customer already uses | No new queue to watch. Findings and actions are written on the ServiceNow ticket, where people already look |
| 2 | The platform enforces the rules, not the AI's instructions | Which servers, which fixes and which actions are allowed is decided by code and by AWS IAM. The model only proposes |
| 3 | A person stays in the loop for anything risky | Fixes outside the low-risk development rule need an engineer's Confirm, and planned work needs a ticket |
| 4 | Never mark your own work | After a fix the agent re-measures the real server, and the alarm and the notes remain as a second check |
| 5 | Run inside the customer's own AWS account | One Lambda, in the account that owns the servers. No vendor-hosted service sits in between |

### How one incident is handled

1. A CloudWatch alarm enters the ALARM state. An EventBridge rule starts MATRIX; a five-minute sweep catches any it missed.
2. MATRIX opens a ServiceNow incident, assigns it to the AI group and fills in the server. A second alarm for the same open incident is not duplicated.
3. The agent reads the matching runbook, then runs read-only checks: health, CPU, disk, services, alarms.
4. It proposes **one** fix from a fixed list. Code checks the proposal against what the checks really showed.
5. A person confirms when the fix is risky. Low-risk fixes in development, and patterns MATRIX has resolved before, run on their own.
6. After about 15 seconds MATRIX measures again. If the problem is gone, the incident is resolved with the evidence. If not, it is escalated to L2 with the reason.
7. A resolved escalation produces a draft article and playbook that a person reviews before anything is published.

Every step is written on the ticket and to the audit log.

## 4. How a customer adopts it

We recommend three stages, so trust is earned and not assumed.

| Stage | What MATRIX does | What people do | How it is set |
|---|---|---|---|
| 1. Tickets only | Opens the ticket, assigns it and fills in the server | Fix the incidents as today and see how much work the ticket opening saves | Clear `AGENT_KEY` (RSK-001 level 2) |
| 2. Engineers confirm | Diagnoses and proposes; nothing runs until Confirm | Confirm or reject each action card | Tag servers with a non-development `environment`, and raise `AUTO_AFTER` so no pattern counts as known |
| 3. Automatic for routine work | Runs low-risk fixes in development, and fixes it has resolved three times before | Review results monthly and improve the runbooks | Default behaviour for development servers |

Scope is controlled by tags on each server: `matrix-managed=true` puts a server in scope, and removing the tag takes it out.
A pilot on a few test servers, with stage 2 first, is the normal way in.

## 5. Future scalability

### 5.1 What scales today

| Dimension | How it scales today | Limit today |
|---|---|---|
| Ticket volume | The Lambda scales with the number of alarms. The part that limits first is model traffic | Free-tier model endpoints are rate limited (about 40 requests a minute on NVIDIA's). Add a standby model, or a paid tier |
| Alarm bursts | A sweep opens at most `ALARM_MAX_PER_RUN` new incidents each run (default 5) and continues on the next run | A storm of many alarms is worked through over several sweeps |
| Number of servers | Each managed server is a tag, with no per-server software | Larger fleets: `[to be measured]` |
| Model availability | A primary model, same-key extras and up to three standbys. A rejected, missing or rate-limited model is skipped and cooled down | A model's own limits and prices |
| Accounts and regions | One stack per account and region. Each keeps its own data and settings | No central view across stacks yet |
| Ticketing tools | ServiceNow | Another tool needs new code |
| Server types | Linux servers managed through AWS Systems Manager | No Windows fixes yet |

**Planning figures (observed in the development account over seven days).** 129 model calls across three models, about
439,000 tokens sent and 25,800 received, and a model cost of about $0.05. One observed run took about three minutes from
ticket creation to escalation, including a human approval. These are a starting point, not a guarantee.

### 5.2 What we plan next

| Horizon | Planned improvement | Why it matters |
|---|---|---|
| Next | Secrets moved to AWS Secrets Manager; hashed console passwords or single sign-on with multi-factor sign-in | Closes the main sign-in and secret-storage gaps (SEC-001) |
| Next | A deployment pipeline with review and signing | Replaces pasting files into the Lambda |
| Next | A rehearsed stop procedure and restore test | Faster, safer containment (RSK-001) |
| Next | A per-team chargeback report on the dashboard | Today the monthly worksheet is by hand (COM-001) |
| Next | Average time to resolve that honours the `STATS_SINCE` date | Today it counts every old test ticket |
| Next | A second ticketing adapter and Windows fixes | Wider coverage |
| Later | More pre-approved routine fixes, with the same audit trail | Handles a wider share of tickets |
| Later | A central view across several accounts | Large and multi-region customers |
| Long term | Recurring causes are found and fed back to engineering | Fewer incidents, not just faster ones |

We do not want to jump to the end. Each step is earned with the right controls and measurements first.

### 5.3 Known limits today

- One Lambda, one region, one account per deployment. If MATRIX is down, alarms and tickets still exist and the sweep recovers missed alarms when it is back. Nothing is lost.
- Prompts and tool output go to the model provider you choose, unredacted. Pick one whose terms you accept.
- Console accounts are held in a setting, with no single sign-on or multi-factor sign-in.
- Autonomous fixes are Linux-only, over Systems Manager.
- The post-fix recovery check uses a language model, so a wrong "yes" is possible. The alarm, the incident and the notes remain the check.
- The one-template install has not yet been rehearsed in a clean account.

## 6. What we ask of you

1. Agree the pilot scope: which servers, which alarms, and for how long.
2. Agree the six measures above.
3. Define the baselines together, so improvement can be shown with your own numbers.

## Change history
| Version | Date | Author | Summary | Approval |
|---|---|---|---|---|
| 0.1 | 18 Nov 2026 | Product owner | First draft | Pending |
