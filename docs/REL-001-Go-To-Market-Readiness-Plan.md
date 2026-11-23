# MATRIX: Go-to-Market Readiness Plan (lift and shift, licence, protection, support)

| Field | Value |
|---|---|
| Document ID | REL-001 |
| Owner | MATRIX product owner |
| Version / status | 0.1 / Draft, for owner decision |
| Classification | Internal |
| Effective date | 23 November 2026 |
| Applies to | MATRIX AIOps (this repository, `main`) |
| Related documents | IPR-001 (code protection, support), LIC-001 (licence and pricing), DEP-001 (deployment), MTX-03 (support model), DEMO-001 (test evidence) |

## 1. Goal

Be ready to hand MATRIX to a paying customer so that it is: **licensed** (only paying customers run it), **protected** (hard to copy, read or
change, and the usage meter cannot be edited), **fully functional** (every case works and is evidenced), **installable in days** (the lift and
shift), and **supported** (a plan the customer can read and we can staff).

Honest limit, said once: while code runs inside a customer's AWS account, no technique makes it impossible to reverse engineer. Real protection
comes from keeping the valuable part in our account (stage 3 below), plus the signed licence and the contract. See IPR-001.

## 2. What "lift and shift" means for MATRIX

It is an **install into the customer's account, not a migration of their systems**. One CloudFormation template (`infra/matrix-all.yaml`) deploys one
Lambda, one DynamoDB table and one S3 bucket. We connect it to the customer's ServiceNow, tag the servers it may manage, and set the IAM boundary.

| Step | What happens | Who | Time |
|---|---|---|---|
| 1. Pilot agreement | 60 days, up to 10 servers, dev only. Signed agreement and data terms | Vendor and customer | 1 week |
| 2. Prepare | Customer gives an AWS account, a ServiceNow user and a model key. Customer tags servers `matrix-managed=true`, `environment=dev` | Customer | 1 to 2 days |
| 3. Install | Deploy the template, set the licence key, upload runbooks | Vendor | 1 day |
| 4. Prove | Run the demo cases (DEMO-001): auto-fix, false alarm, restart with ticket, deploy, migrate, decommission, refusal | Both | 2 days |
| 5. Pilot | Measure tickets resolved with no human, escalation rate, minutes saved | Both | 60 days |
| 6. Convert | Sign the licence, issue the production key, enable production with human approval | Vendor | 1 week |

## 3. The five workstreams

### 3.1 Selling model (LIC-001)
| Item | State | Next action | Decider |
|---|---|---|---|
| Plans: Starter, Team, Commander, with proposed prices | Drafted, **not approved** | Owners agree or change every price | Product owner, finance |
| Pilot offer (60 days, credited on conversion) | Drafted | Confirm | Product owner |
| LIC-001 section 9 ("nothing is enforced") | **Out of date**: a signed key now exists | Rewrite section 9 to describe the signed key and the enforcement switch | Engineering |
| Value case (30% of L1 time) | An assumption | Replace with measured figures after the first pilot | Product owner |
| Contract, data terms, tax, invoicing | Not started | Hire a lawyer; use IPR-001 section 3 option E as the brief | Legal |

### 3.2 Licensed
| Item | State | Next action |
|---|---|---|
| Signed licence key (Ed25519), checked at start | **Built and live** | Keep |
| Key sets plan, servers, seats, account and expiry; settings cannot raise limits | **Built and live** | Keep |
| Enforcement switch `LICENSE_ENFORCE` | Built, **off** | Turn on in a test Lambda and prove changes stop without a key; then on for customers |
| Vendor signing tool (`tools/matrix_licence_sign.py`) | **Built** | Needs the private key (see 4, item 1) |
| Key renewal and revocation | Not built | Short expiry (for example 1 year) plus a vendor check-in (stage 2) |

### 3.3 No reverse engineering (IPR-001 stages)
| Stage | Work | State |
|---|---|---|
| 1 | Signed key, compiled build | Key done. `tools/build-release.sh` written, **not yet run** (needs Docker) |
| 2 | Vendor-side meter: signed usage reports to a vendor endpoint, the source of truth for limits | Not started |
| 3 | Split: valuable logic, prompts, runbook library, learning and meter in the **vendor account**; a thin Connector in the customer's | Designed (IPR-001 5a), not started |
| 4 | Onboarding automation: cross-account role, per-customer keys, tag boundary, kill switch | Not started |

The pilot version (everything in the customer's account) is for **trusted pilots only** until stage 3.

### 3.4 Fully functional
| Item | State | Next action |
|---|---|---|
| Auto-fix, false-alarm close, restart with ticket, deploy, migrate, decommission, guardrails | **Tested live** (DEMO-001, 10 cases) | Re-run on a clean account before each release |
| 119 automated tests | Pass | Keep as the release gate |
| Account vCPU limit message is raw AWS text (T10) | Open | Plain-language message and a pre-check before a launch |
| Backup model slots: both `gpt-oss-120b` slots return HTTP 400; failover takes about 65 seconds | Open | Fix the tool format; lower standby time-outs to about 15 seconds |
| Free model endpoint (rate limited) | Open | A paid model key for customers |
| Console is HTTP only | Open | CloudFront with HTTPS before any customer sees it |
| Clean install test of `matrix-all.yaml` in a second, empty account | Not done | Do before the pilot; this is the real lift-and-shift test |
| Old tickets still "investigating" (INC0010021 to 23 and a few earlier) | Open | Close or let the agent finish them |
| ServiceNow developer instance hibernates | Known | Customers use their own paid instance |

### 3.5 Support model (IPR-001 section 6, MTX-03 part C)
| Item | State | Next action |
|---|---|---|
| Tiers: Standard 18% (business hours), Premium 25% (24 by 7 for severity 1 and 2) | Drafted | Decide the hours, time zone and first-response times |
| Severity levels, kill switch as the first move | Written (MTX-03 C1, C2, RSK-001) | Keep |
| Troubleshooting guide (SUP-001) with the faults we hit | Written | Keep updated each release |
| Release rhythm, change log, rollback zip | Drafted | Decide the rhythm; start a `CHANGELOG` |
| Who staffs tier 2 and tier 3, on-call | **Not decided** | Owners decide |
| Vendor-hosted tier (if stage 3 is built) | Not priced | Price it to cover hosting and model cost |

## 4. Blockers that need the owners

1. **Signing key.** The public key in the product has no private key we can use. Either find it, or make a new pair and redeploy (any key already issued would stop working). Keep the private key offline and outside the repository.
2. **Rotate the secrets** that were shared during development (model keys, ServiceNow password, console passwords, token secret, agent key), and clean the repository history before anyone outside sees it.
3. **Approve the prices and plans** (LIC-001), and the support hours (3.5).
4. **Decide the protection target:** stage 1 only, or the full vendor-hosted Core with a customer Connector (stages 1 to 4). IPR-001 recommends the full split.
5. **Legal:** licence agreement, data terms, source escrow and audit right.

## 5. Order of work

| Phase | Work | Result |
|---|---|---|
| Now | Settle the signing key; run the compiled build; turn on enforcement in a test Lambda; fix the two model-slot problems; update LIC-001 section 9 | Licence and protection stage 1 proven |
| Next | Clean install in a second account; HTTPS; plain vCPU message; paid model key; `CHANGELOG` | A pilot-ready package |
| Then | Stage 2 vendor meter; legal terms; first pilot | The meter cannot be edited; first real customer data |
| Later | Stage 3 split and stage 4 onboarding automation; vendor-hosted tier | Valuable code leaves the customer's account |

## 6. Ready-to-sell checklist
- [ ] Prices approved and written into the offer
- [ ] Signing key settled and stored offline; a test key issued and verified in a dev Lambda
- [ ] Compiled release built and passes the demo cases
- [ ] Enforcement on in a test Lambda: changes stop with no valid key, reads still work
- [ ] Clean install in an empty account takes under one day
- [ ] HTTPS in front of the console
- [ ] Secrets rotated; repository history clean
- [ ] Support hours, response times and staffing decided and written
- [ ] Legal agreement reviewed
- [ ] Pilot plan with measured success figures agreed with the first customer

## Change history
| Version | Date | Author | Summary | Approval |
|---|---|---|---|---|
| 0.1 | 23 Nov 2026 | Product owner | First version: readiness plan across licence, protection, function, install and support | Pending |
