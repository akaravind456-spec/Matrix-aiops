# MATRIX: Cost and Chargeback Model

| Field | Value |
|---|---|
| Document ID | COM-001 |
| Owner | MATRIX product owner |
| Approver | `[to be named]` (finance review recommended) |
| Version / status | 0.1 / Draft: **method and measured costs; no prices are proposed** |
| Classification | Internal |
| Effective date | 18 November 2026 |
| Review frequency | Monthly for the first quarter, then every quarter, and whenever a model or plan changes |
| Applicable product version | MATRIX AIOps (this repository, `main`) |
| Related | PRD-001 (overview), DEP-001 (deployment), SUP-001 (support) |

**Status of the figures.** The amounts in section 3 were read from the MATRIX Dashboard of the dev account for one week
(12 to 18 November 2026). They show the size of the problem, not a forecast for a bigger fleet. Section 7 gives the
price-setting method but **leaves the rates blank on purpose**: set them after a few months of measured data and a finance
review. All amounts are US dollars, exclude tax, and are before credits unless stated.

## 1. What "chargeback" means here

MATRIX is a shared platform used by several teams and environments. **Chargeback** is how the platform's running cost, and
the resources it creates for a team, are passed on to the teams that benefit. This document gives a fair, simple and
measurable way to do that. It also gives the cost-to-serve a team needs if MATRIX is later offered to other
units as an internal service.

**Principles**
1. **Charge from measured data**, taken from the Dashboard, AWS Cost Explorer and ServiceNow, never from guesses.
2. **Direct costs go to their owner.** Servers the agent creates for a team are charged to that team through tags.
3. **Shared costs are split by a visible driver**: how much of MATRIX's work each team used.
4. **Use costs before credits** (gross), so a team is not charged zero today and a surprise later when credits end.
5. **Keep it cheap to run.** The monthly worksheet in section 6 takes minutes, not days.

## 2. The cost components

| # | Component | What drives it | Type | Where to read it |
|---|---|---|---|---|
| A | **Platform compute and services** | Lambda invocations and time; DynamoDB reads and writes; S3; CloudWatch logs; EventBridge; Cost Explorer API calls (about $0.01 each; MATRIX caches the answer for an hour) | Shared | Dashboard cost card, "By AWS service" |
| B | **Model usage (LLM)** | Tokens in and out for each model, times that model's price per million tokens | Shared (or per ticket) | Dashboard "LLM usage" table (price table kept on the server, setting `LLM_PRICES`) |
| C | **Resources MATRIX creates** | Servers launched by deployment, migration clones, backup images (AMIs) and their snapshots | Direct | Cost Explorer grouped by the tag `matrix-managed=true` and by your owner or cost-centre tag |
| D | **Workloads MATRIX manages** | The teams' own servers | Not MATRIX's cost | Charged as before; shown for context |
| E | **ServiceNow** | Instance, licences, knowledge base | Outside this model | ServiceNow contract |
| F | **People** | Platform owner time, reviewers of learning drafts and approvals | Outside this model unless you choose to include it | Timesheets |

Components A and B are the **MATRIX platform cost**. C is passed straight to the owner. D, E and F are listed so nobody
counts them twice.

## 3. What MATRIX actually cost in the first measured week

From the Dashboard, last 7 days, dev account.

| Item | Amount | Note |
|---|---|---|
| Whole account, gross before credits | $7.78 | Includes the teams' own test servers |
| Of which EC2 compute | $4.57 | Component D, not MATRIX |
| Of which EC2 - Other | $0.95 | Component D (volumes, addresses) |
| Of which Virtual Private Cloud | $1.32 | Component D (networking) |
| Of which CloudWatch | $0.47 | Mostly A (logs and alarms) |
| Of which Cost Explorer | $0.32 | A (the Dashboard cost card) |
| Of which Secrets Manager | $0.08 | Not part of MATRIX unless you adopt it for secrets |
| Of which S3, DynamoDB, API Gateway | $0.07 | A |
| Lambda | $0.00 | Inside the free tier, so not listed |
| Credits applied | $7.78 | The account pays $0.00 for now |
| **LLM cost** | **$0.05** | 129 calls; NVIDIA free endpoint, plus one paid Groq model at $0.15 in / $0.60 out per 1M tokens |

**Reading it.** MATRIX's own running cost this week was **well under one dollar**. The visible AWS bill was dominated by the
test servers it was managing. At small scale, MATRIX is cheap; the real saving or cost is in the servers and the engineers' time.
Two things will change this: leaving the free tiers (Lambda, the NVIDIA free endpoint, credits) and growth in ticket volume.

## 4. How to allocate the cost

### 4.1 Direct costs (component C)

Everything MATRIX launches carries `matrix-managed=true` and an `environment` tag. Add an **owner or cost-centre tag** (for
example `cost-centre`) so the cost can be charged to a team. MATRIX does **not** add that tag by itself today: put it on the
server through the launch template or the Terraform module, or add it by hand after launch.

| Step | Action |
|---|---|
| 1 | Choose the tag name (for example `cost-centre`) and make sure every launched server and backup image gets it |
| 2 | Activate `matrix-managed` and that tag as **cost allocation tags** in the AWS Billing console (it takes up to a day to appear) |
| 3 | Monthly, in Cost Explorer filter on `matrix-managed=true` and group by the cost-centre tag; the total per value is that team's direct cost |
| 4 | Resources with no cost-centre tag go to the platform owner's budget, and are chased |
| Optional | Set `COST_TAG_KEY` on the Lambda to the tag name. The console's cost report can then be limited to one tag value (the `project` field of the cost request). It only filters the report; it does not apply tags |

### 4.2 Shared platform cost (components A and B)

Split by **how much MATRIX worked for each team**. Pick one driver and stay with it for a year.

| Driver | How to measure | Fair when | Weakness |
|---|---|---|---|
| **Handled tickets** (recommended) | Count incidents MATRIX worked on per team in the month. Use the incident's assignment group or the CI's owner group in ServiceNow | Teams get similar benefit per ticket | A hard ticket costs more than an easy one |
| **Managed servers** | Count servers with `matrix-managed=true` per team | Cost is mostly standing cost | Ignores real usage |
| **LLM tokens** | Tokens used for each team's tickets (from traces) | Model cost dominates | Needs per-ticket tracing; not available as a report yet |
| **Even split** | Total divided by teams | Early days, tiny cost | Not related to use |

**Formula (handled tickets).**

```
Team share of platform cost = (platform cost A + B for the month)  x  (team's handled tickets / all handled tickets)
```

### 4.3 Which cost basis to use

| Basis | Use |
|---|---|
| **Gross (before credits)** | **Charge this.** It is the real price of the service |
| Net (after credits) | Report only. Credits are temporary and shared |
| Fixed monthly budget | Acceptable for a first quarter while volumes are tiny |

The Dashboard cost card already shows the AWS total before credits and a separate line for credits, so the numbers match
what you charge.

## 5. Unit costs to track

These show whether MATRIX is getting cheaper or dearer as it grows, and feed any future price.

| Unit | Formula | Where the inputs come from |
|---|---|---|
| Cost per handled ticket | (A + B) / tickets MATRIX worked on | Cost card, Dashboard agent runs |
| Cost per automatic resolution | (A + B) / tickets resolved without a person | Dashboard "Resolved by the agent" |
| Model cost per ticket | B / tickets | LLM usage table, Dashboard |
| Cost per managed server | (A + B) / managed servers | CMDB or tag count |
| Autonomous resolution rate | Resolved by the agent / (resolved + escalated) | Dashboard |
| Human intervention rate | Escalated / (resolved + escalated) | Dashboard |

Set the Dashboard's `STATS_SINCE` date to the start of the period so test records do not distort these.

## 6. The monthly chargeback worksheet

Do this on the first working day of each month.

| Step | What to do | Source |
|---|---|---|
| 1 | Record the platform cost: AWS services that belong to MATRIX (Lambda, DynamoDB, S3, CloudWatch, EventBridge, Cost Explorer), gross | Cost Explorer or the Dashboard |
| 2 | Record the LLM cost for the month | Dashboard LLM usage |
| 3 | Add them: **platform cost** | |
| 4 | Count handled tickets per team | ServiceNow list, filtered by `[MATRIX]` and the month |
| 5 | Work out each team's share with the formula in 4.2 | |
| 6 | Pull each team's **direct costs** by tag (4.1) | Cost Explorer |
| 7 | Team charge = direct costs + share of platform cost | |
| 8 | Send the statement; keep the worksheet with the month's records | Finance |

| Team | Handled tickets | Share | Platform cost share | Direct costs (tags) | **Total charge** |
|---|---|---|---|---|---|
| `[team A]` | | | | | |
| `[team B]` | | | | | |
| Unassigned | | | | | Platform owner |
| **Total** | | 100% | | | |

**Limits today.** MATRIX does not yet produce a per-team report. Steps 4 to 7 are done by hand, or in a spreadsheet, from
ServiceNow and Cost Explorer. A per-team report (tickets, tokens and tagged cost on one page) is a candidate feature; ask
the platform owner before relying on it.

## 7. If MATRIX is offered as a service: how to set a price

Only do this after at least three months of measured data. **No rates are proposed in this version.**

1. **Find the cost to serve** one unit (a managed server, an approver seat or an automatic ticket) using section 5.
2. **Choose the charging unit.** Usage that follows value is easiest to explain: per managed server a month, or per handled
   ticket. A per-token charge is hard for teams to predict; keep tokens inside the unit price.
3. **Add the people cost** (support, reviews, improvement) per unit.
4. **Floor price** = (platform cost + people cost) / units, plus a margin for growth and for leaving the free tiers.
5. **Compare with the cost of the work saved**: the Dashboard gives tickets resolved without a person, and your service
   desk knows what an L1 ticket costs to handle. A price above that saving will not be accepted.
6. **Keep limits soft.** Charge for use above a team's plan in the next period instead of stopping people from working.

| Item | Rate |
|---|---|
| Per managed server per month | `[to be decided]` |
| Per handled ticket | `[to be decided]` |
| Per approver seat | `[to be decided]` |
| Direct resources | At cost (tagged) |

## 8. Costs outside this model

| Cost | Who pays |
|---|---|
| ServiceNow instance, licences and any AI add-on | The ServiceNow owner |
| The teams' own servers, networks and storage | The teams (component D) |
| Model provider charges above the free tier | The platform owner (component B), then allocated as shared |
| AWS support plan, if any | The account owner |
| People time (owners, reviewers, engineers who approve) | Their own teams, unless you choose to include it |

## 9. Controls and alerts

- Create an **AWS Budget** for the MATRIX tag or service set, with an alert at 80% and 100%.
- Watch the Dashboard's LLM cost; set `LLM_PRICES` for every paid model so a model with no price shows "price not set", never $0.
- A model with no price is excluded from the total and listed as unpriced; fix it before the month-end worksheet.
- A rising **cost per handled ticket** without a rising resolution rate means the agent is working harder, not better: check the Traces page.
- Review the free tiers in use (Lambda, the NVIDIA endpoint, credits) each month, so their end is not a surprise.

## 10. Assumptions and open decisions

1. The week measured is small and uneven; repeat the table in section 3 for a full month before any decision.
2. Decide the allocation driver (section 4.2) and the cost-centre tag name, and keep them for a year.
3. Decide whether people cost is included.
4. Decide whether the per-team report should be built into the Dashboard.
5. Confirm the paid model prices every quarter; providers change them. The built-in price for the one paid model comes from the provider's own price page and has a single source.
6. Finance and the platform owner must approve the method before any team is charged.

## Change history
| Version | Date | Author | Summary | Approval |
|---|---|---|---|---|
| 0.1 | 18 Nov 2026 | Product owner | First draft from the measured first week | Pending |
