# MATRIX: Licensing and Pricing

| Field | Value |
|---|---|
| Document ID | LIC-001 |
| Owner | MATRIX product owner |
| Approver | `[to be named]` (finance and legal review required) |
| Version / status | 0.1 / Draft: **proposed prices, not an offer** |
| Classification | Internal until approved; customer-shareable after |
| Effective date | `[date prices are approved]` |
| Applicable product version | MATRIX AIOps (this repository, `main`) |
| Related | MTX-03 (deployment, cost, support), COM-001 (internal chargeback), PRD-001, DEP-001 |

**Status.** Every price below is a **proposal** to be adjusted and approved by the owners. None is based on a customer
contract or measured savings yet. Prices are US dollars, exclude tax, and are per year unless stated. Anything in
`[brackets]` is undecided. Legal terms (licence agreement, privacy notice) are not part of this document.

## 1. How MATRIX is licensed

The customer runs MATRIX in **their own AWS account** (one Lambda). They pay the vendor an **annual licence**, plus
**support** as a percentage, plus optional one-time services. The licence price follows what the customer uses, so it is
easy to predict. There is **no per-ticket charge and no per-token charge**: model cost is paid directly by the customer to
their model provider (MTX-03 Part B).

| Part | What it pays for |
|---|---|
| Licence | The right to run MATRIX for one ServiceNow instance, within the plan's limits |
| Support | Fixes, new releases and help from the vendor |
| Add-ons and capacity | A feature the plan lacks, or more servers or seats |
| Services | One-time help: pilot, onboarding, training |

## 2. What is counted

| Unit | Definition | Where to see it |
|---|---|---|
| **Managed server** | An EC2 instance tagged `matrix-managed=true` and `environment=<the stack's environment>`, running or stopped. The highest count in the month | Dashboard, Licence card |
| **Approver seat** | A console user who can sign in and confirm fixes (an entry in the `USERS` setting) | Dashboard, Licence card |

Auditors who only read ServiceNow and the audit log do not need a console seat.

## 3. Plans

| | Starter | Team | Commander |
|---|---|---|---|
| Managed servers | 25 | 100 | Unlimited (fair use) |
| Approver seats | 2 | 10 | 50 |
| **Licence per year** | **$3,600** | **$18,000** | **$60,000** |
| Per month, billed yearly | $300 | $1,500 | $5,000 |
| Alarm to incident to fix, runbooks, learning drafts, dashboard, chat read checks | Included | Included | Included |
| Chat changes and planned work (patching, migration, deployment, decommission) | Add-on | Included | Included |
| Effective unit cost at the limit | $144 per server | $180 per server | $1,200 per seat |

**Support**: Standard is 18% of licence and add-ons (business hours `[to be decided]`); Premium is 25% (24 by 7 for severity 1
and 2 `[to be decided]`, a named engineer, a quarterly review).

| Support per year | Starter | Team | Commander |
|---|---|---|---|
| Standard (18%) | $648 | $3,240 | $10,800 |
| Premium (25%) | $900 | $4,500 | $15,000 |

## 4. Add-ons, capacity packs and services

| Item | Price |
|---|---|
| Add-on: chat changes and planned work, for Starter | $2,400 a year |
| Capacity pack: 50 more managed servers | $4,000 a year |
| Capacity pack: 5 more approver seats | $2,000 a year |
| Pilot: 60 days, up to 10 servers. Credited in full if the customer converts | $2,500 |
| Onboarding (Starter / Team / Commander) | $2,500 / $6,000 / $15,000 |
| Training session (half day) | $1,500 |
| Extra consulting day | $1,200 |
| Custom integration (for example another ticketing tool) | Quoted |

## 5. Discounts and terms

| Item | Terms |
|---|---|
| Two-year or three-year commitment | 5% or 10% off licence and add-ons, price locked |
| Renewal increase | Capped at 5% a year |
| Non-production instance (test, staging) | 20% of the production licence |
| Second and later production instances | 15% off each |
| Billing | Yearly in advance. Quarterly billing adds 3% |

## 6. Limits are soft

Going over a limit **never stops people working** and never blocks a fix. The Dashboard Licence card shows a notice when
usage reaches 90% of a limit and when it passes it. If the customer stays over after a grace period of `[30 days]`, the
excess is charged quarterly at 125% of the capacity-pack rate, or they buy the pack and the overage is credited against it.

## 7. Worked examples

| | Small team | Mid-size operations | Large enterprise |
|---|---|---|---|
| Plan | Starter | Team | Commander, 3-year term |
| Licence and add-ons, net | $3,600 | $18,000 | $54,000 (60,000 less 10%) |
| Support | Standard $648 | Standard $3,240 | Premium $13,500 |
| **Recurring cost per year** | **$4,248** | **$21,240** | **$67,500** |
| Onboarding (one time) | $2,500 | $6,000 | $15,000 |
| **First-year total** | **$6,748** | **$27,240** | **$82,500** |
| Starter with the planned-work add-on | $3,600 + $2,400 + 18% support = $7,080 a year | | |

The customer also pays, outside these prices: AWS, the model provider, ServiceNow, and their engineers' time to approve and
review (MTX-03 section B5).

## 8. The value case

A method, not a promise. The pilot measures the real figures from the customer's own data.

| Item | Figure | Source |
|---|---|---|
| Cost of five L1 engineers covering every hour | about $27,000 a month, $324,000 a year | $50,000 base from public 2026 salary sites, plus 30% for tax and benefits (our assumption), times five |
| Share of repeated work MATRIX takes over | 30% (assumption, to be measured) | |
| Time given back | about $8,000 a month, about $96,000 a year | 30% of the above |
| Team plan recurring cost | $21,240 a year | Section 7 |
| Team cost as a share of that time | about 22% | $21,240 / $96,000 |

For a desk of this size Starter or Team is the right fit. Commander is meant for large fleets where the saving scales with
many more tickets and servers. Use the customer's own cost per ticket and ticket volume for the real calculation.

```
Saving = tickets MATRIX resolves without a person x the customer's cost of handling an L1 ticket
Net    = Saving - recurring licence and support - the customer's AWS and model cost - people time to approve
```

## 9. What is and is not enforced today

| | Today |
|---|---|
| **Measured** | The Licence card on the Dashboard counts managed servers (EC2 tag) and approver seats (`USERS`), and compares them with the plan |
| **Set by** | The settings `LICENSE_PLAN` (`starter`, `team`, `commander` or `custom`), `LICENSE_NAME`, and for custom deals `LICENSE_SERVERS` and `LICENSE_SEATS` (a number, or `unlimited`). Unset means "Evaluation", with no limits shown |
| **Enforced** | **No.** There is no signed licence key and nothing is paused or blocked. The plan setting is trust-based, and a customer with Lambda access can change it |
| **Prices in code** | None. Prices live only in this document |

If MATRIX is sold beyond trusted pilots, add a vendor-signed licence file that the Lambda verifies (plan, limits, expiry,
customer), and decide what happens when it expires. The meter, the settings and the soft-limit rules above are designed
to carry over unchanged.

## 10. Open decisions
1. Approve or change the plan sizes and every price (finance).
2. Choose the support hours, response targets and named contacts (see MTX-03 Part C).
3. Decide the grace period and the overage rate.
4. Decide currency, invoicing, tax and payment terms.
5. Decide whether to add a signed licence file, and when.
6. Write the licence agreement and privacy notice with legal review.
7. Re-check the prices after the first pilot has measured the real saving.

## Change history
| Version | Date | Author | Summary | Approval |
|---|---|---|---|---|
| 0.1 | 18 Nov 2026 | Product owner | First draft of proposed plans and the usage meter | Pending |
