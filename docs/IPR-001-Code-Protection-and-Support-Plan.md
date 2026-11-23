# MATRIX: Code Protection, Support and Maintenance Plan

| Field | Value |
|---|---|
| Document ID | IPR-001 |
| Owner | MATRIX product owner |
| Version / status | 0.1 / Draft, for owner decision |
| Classification | Internal |
| Effective date | 23 November 2026 |
| Applies to | MATRIX AIOps (this repository, `main`) |
| Related documents | LIC-001 (licensing), MTX-03 part C (support model), SUP-001, DEP-001 |

## 1. The question

MATRIX runs inside the customer's own AWS account (DEP-001). The Lambda code runs there. A customer, or a contractor with
Lambda access, can therefore download it. If the code is only "encrypted" at rest, AWS decrypts it for the customer to run
it, so **encryption alone cannot hide the code from the person who runs it**. This document sets out what protects the product
instead, what each option costs, and what we recommend.

## 2. What is true (and not)

| Idea | Reality |
|---|---|
| Encrypt the Lambda zip | AWS encrypts function code at rest, and the account owner can still download it. This protects against outsiders, not against the customer |
| Encrypt the code and ship a key | The key has to be in the customer's account for the code to run, so the customer can get it |
| Hide the code completely | Only possible if the code never leaves the vendor's account (vendor-hosted) |
| Make copying hard and expensive | Yes: compile or obfuscate, bind to a licence, and add contract terms |
| Stop a determined competitor | No technical control fully does. Contract, licence and audit rights are the real deterrents |

## 3. Options

| # | Option | What it does | Protects against | Cost and trade-off |
|---|---|---|---|---|
| A | **Vendor-hosted (SaaS)** | MATRIX runs in the vendor's AWS account. The customer gives a cross-account role and ServiceNow access | Everything: the customer never sees the code | Changes the model in MTX-03 (customer data and access go to the vendor); more security review by customers; the vendor carries the run cost |
| B | **Compile to native code** | Build the Python files into compiled modules (Nuitka or Cython) for the Lambda runtime. The zip holds binaries, not readable source | Casual reading and copying | A build step per release; needs testing on the Lambda runtime (Linux, Python 3.12). Can still be reverse engineered with effort |
| C | **Obfuscate** (PyArmor or similar) | Scrambles names and bytecode, adds a runtime check | Casual copying | Adds start-up time and debugging pain; weaker than B |
| D | **Licence key** | A signed key tied to the customer, plan and expiry. MATRIX checks it at start and reports usage | Unlicensed use and sharing the product | Needs a key service on the vendor side; offline customers need long-lived keys. Today only the soft usage meter exists (LIC-001 section 9) |
| E | **Contract terms** | Licence forbids copying, reverse engineering and building a competing product; audit right; source escrow for continuity | Everyone who signs it | Needs a lawyer; enforced only by contract and courts |
| F | **Keep the valuable part server-side** | Keep a small vendor-run service for the parts that are hard to copy (for example the curated runbook library, learning, model routing) and call it from the customer's install | The core intellectual property | A vendor service to run; customers must allow outbound access |

## 4. What is actually valuable (and what is not)

The Python glue is not the hardest thing to copy. What takes time to build and keep right is:
- the **safety design** (fix catalogue, vetting, ticket gate, tag boundary, kill switch, tests),
- the **tuned agent prompts and flows** proven on real incidents,
- the **runbook library and learning loop**, and
- the **ServiceNow and AWS integration details** (close codes, states, IAM boundaries).

Option F protects the second and third items best, and options B, D and E protect the first and fourth.

## 5. Recommendation

1. **Now (pilots, trusted customers):** option E only. A licence agreement with no-copy, no-reverse-engineering and audit terms, and the existing soft usage meter. Do not spend on technology yet.
2. **Before the first paid, non-trusted customer:** add B (compile the Lambda to native modules in the release build) and D (a signed licence key checked at start, with the plan limits in LIC-001). Keep the readable source in a private repository only.
3. **When customers allow it, or for security-sensitive ones:** offer option A as a vendor-hosted tier and move the runbook library and learning to option F.
4. **Never rely on "encryption" as the answer.** Say plainly in sales material: the code runs in your account; it is protected by licence and contract, and by compiled releases.

Also: remove the live secrets from the repository history and rotate them (they were shared during development), and keep the repository private.

## 6. Support and maintenance plan

This is the plan that sits on top of the tiers in MTX-03 part C. Items in square brackets are for the owners to decide.

### 6.1 Support tiers and hours

| Plan | Hours | First response, severity 1 | Channel | Price (LIC-001) |
|---|---|---|---|---|
| Standard | Business hours `[time zone]` | `[4 hours]` | Email and ticket | 18% of licence per year |
| Premium | 24 by 7 for severity 1 and 2 | `[30 minutes]` | Email, ticket and phone | 25% of licence per year |

Severity levels, tiers and the first move for a critical issue (stop MATRIX) are in MTX-03 C1 and C2.

### 6.2 Releases and updates

| Item | Plan |
|---|---|
| Release rhythm | A small release every `[month]`; security fixes as needed |
| Versioning | Numbered releases with a change log (what changed, what to test, how to roll back) |
| How a customer updates | The customer's platform owner deploys the new zip (or runs the stack update) in a test account first, then production. The one-zip layout makes this a single upload |
| Roll back | Keep the previous zip; redeploy it. Settings are unchanged by a code update |
| Compatibility | ServiceNow and AWS API changes are checked each release; the customer is told what to retest |
| Test gate | The 107 automated tests must pass; a live check on a dev stack (deploy, migrate, decommission, agent fix) before each release |

### 6.3 Routine care (customer's platform owner)

- Weekly: review escalations and learning drafts; read the Observability page for model failures and slow calls.
- Monthly: rotate model keys and the console passwords; remove old test users; review the audit log.
- Each release: read the change log, deploy to dev, run the demo test cases (DEMO-001), then deploy to production.
- Quarterly: review which servers are tagged as managed and which fixes ran automatically; adjust the dev and production split.

### 6.4 Vendor responsibilities

| Area | Vendor | Customer |
|---|---|---|
| Defects in the product | Fix and release | Report with logs and ticket numbers (MTX-03 C4) |
| Security issues in the code | Fix, notify, publish a patched release | Apply the patch within `[x days]` |
| AWS, ServiceNow and model-provider outages | Advise and apply workarounds | Own the accounts and plans |
| Runbooks and tagging | Provide the starter library | Own their content and quality |
| Keys, passwords, access | Never holds the customer's secrets | Owns and rotates them |

### 6.4a Lessons from the 23 November 2026 test run

These are real faults we hit, and the support checks they led to (also in SUP-001 section 3):
- a broken `USERS` setting takes the console down for everyone, so validate it before saving;
- an account vCPU limit blocks a clone launch, so check the limit before a migration;
- a missing IAM permission (`DescribeInstanceStatus`) blocks a cutover, so test the policy in dev first;
- servers must carry the `environment` and `matrix-managed` tags (either spelling of the environment tag now works);
- the ServiceNow free instance hibernates; use a paid instance for customers.

### 6.5 Open decisions

| Decision | Owner |
|---|---|
| Response times, hours and who staffs tier 2 and tier 3 | Product owner |
| Release rhythm and the support period for old versions | Product owner |
| Which protection options (B, D, E, A, F) and in what order | Product owner and legal |
| Price of vendor-hosted tier | Product owner |
| Source escrow and audit right wording | Legal |

## Change history
| Version | Date | Author | Summary | Approval |
|---|---|---|---|---|
| 0.1 | 23 Nov 2026 | Product owner | First draft: code protection options and support and maintenance plan | Pending |
