# MATRIX: Vendor-Hosted Edition (Model A) Design and Build Plan

| Field | Value |
|---|---|
| Document ID | MDA-001 |
| Owner | MATRIX product owner |
| Version / status | 0.1 / Draft, decision taken: Model A is the main offer |
| Classification | Internal |
| Effective date | 24 November 2026 |
| Applies to | MATRIX AIOps (this repository, `main`) |
| Related documents | IPR-001 (why), REL-001 (readiness), LIC-001 (pricing), SEC-001 (threat model), DEP-001 (today's deployment) |

## 1. Decision

The owners chose **Model A, vendor-hosted**: MATRIX runs in the **vendor's** AWS account. The customer installs almost nothing. The product code,
prompts, runbook library, learning and the usage meter never reach the customer, so there is nothing for them to copy, read or edit.
The current self-hosted edition stays as the **pilot** and as a premium tier for customers who must run in their own account (compiled build, signed key, contract).

## 2. Target architecture

```
 CUSTOMER ACCOUNT                         VENDOR ACCOUNT (we run it)
 ----------------                         --------------------------
 EC2 servers (tagged)  <-- assume role -- MATRIX Core Lambda (agent, prompts, runbooks, learning, meter, licence)
 matrix-executor role  (ExternalId)       DynamoDB (one table, partitioned by tenant)
 EventBridge rule ---- alarm events ----> Vendor event bus -> Core
 (no code at all)                         Console page (served by us, one login per user, tenant-scoped)
        ServiceNow (customer's) <-------- Core calls it with a per-tenant, least-privilege account
```

**The customer-side part is configuration, not code.** It is one CloudFormation stack that creates:
1. the executor role that already exists (`infra/matrix-iam-executor.yaml`), now trusting the **vendor Core role** and requiring an **ExternalId** the vendor issues per customer. Its tag boundary is unchanged: only `matrix-managed=true` and the right `environment` tag;
2. an EventBridge rule that forwards the customer's CloudWatch alarm events to the vendor event bus (`infra/matrix-alarm-events.yaml`, target changed to the vendor bus);
3. an optional kill switch: deleting or disabling the role stops MATRIX at once (RSK-001).

Nothing runs in the customer account that can be copied. Anyone reading the role sees only an IAM policy.

## 3. How each requirement is met

| Requirement | How |
|---|---|
| Licensed | The Core refuses a tenant with no active licence, an expired one, or one over its plan. Limits live in the vendor database, not in the customer's settings |
| Not reverse engineerable | The code is never shipped. The customer sees only the actions MATRIX runs in their account (the CloudTrail log), not how it chose them |
| Usage meter cannot be changed | The Core counts managed servers, seats and actions from its own calls. The customer has no setting to edit |
| Fully functional | The same Core as today (all 10 demo cases), now multi-tenant |
| Supportable | We see our own logs and traces for every tenant and ship fixes with no customer redeploy |
| Customer stays in control | They own the role and can tighten or delete it; every change still needs the engineer's Confirm; production needs approval |

## 4. What must be built (the honest size of the job)

Today the product assumes **one customer**. About 25 places create AWS clients directly (`aiops`, `autonomy`, `awsops`, `console_api`,
`matrix_alarm_intake`, `matrix_guardrails`, and others), and ServiceNow, model keys and users come from environment variables. Moving to many customers means:

| # | Work | Why | Size |
|---|---|---|---|
| 1 | **Tenant record** (DynamoDB): tenant id, AWS account id, region, executor role ARN, ExternalId (kept in Secrets Manager), ServiceNow URL and account, plan, limits, expiry, status | One place that says who the customer is and what they bought | Small |
| 2 | **Cross-account session helper**: `session_for(tenant)` assumes the customer's role (with ExternalId), caches the credentials until they expire | Replaces the global `boto3.client(...)` calls | Medium |
| 3 | **Thread the tenant through every call**: the user's token carries a tenant id; each action, the agent run and the alarm sweep take it and use that tenant's session, tag boundary and ServiceNow | The big refactor. Wrong wiring here would show one customer's data to another, so it needs the strongest tests | Large |
| 4 | **Data isolation**: every DynamoDB key, S3 path and cache key is prefixed by tenant; a test proves a user of tenant A can never read tenant B | The most important safety property of the whole edition | Large |
| 5 | **Per-tenant secrets**: ServiceNow credentials, model keys (or a vendor key with a per-tenant spend cap) in Secrets Manager, never in environment variables | A shared Lambda cannot hold one environment per customer | Medium |
| 6 | **Alarm intake from many accounts**: a vendor event bus accepting events only from registered tenant accounts, mapped to the tenant | Replaces the in-account EventBridge rules | Medium |
| 7 | **Meter and licence in the Core**: count from our own calls; plan limits enforced here; signed key no longer needed for Model A (it stays for the self-hosted edition) | Meets "cannot change the meter" | Medium |
| 8 | **Onboarding automation**: a script or page that creates the tenant, makes the ExternalId, prints the one-click stack link for the customer | Repeatable install in under a day | Medium |
| 9 | **Console**: one hosted page, login scoped to a tenant, HTTPS (CloudFront), per-tenant audit log view | Today it is a single-user S3 page over HTTP | Medium |
| 10 | **Operations**: the vendor's own monitoring, backup, on-call, and a per-tenant kill switch on our side | We now run the service | Medium |

## 5. Build order (each step leaves the product working)

| Step | Work | Proof it works |
|---|---|---|
| A1 | Trust option for the customer role: `ExternalId` parameter (**done in this commit**, `infra/matrix-iam-executor.yaml`) | Template change only; self-hosted installs are unchanged |
| A2 | Tenant record and cross-account session helper (items 1, 2), used for **one** tenant with the existing account as tenant 1 | The current dev account works through the new path, all 119 tests and the 10 demo cases still pass |
| A3 | Per-tenant secrets and ServiceNow (item 5) | Tenant 1 uses secrets from Secrets Manager |
| A4 | Thread the tenant through all actions and add isolation tests (items 3, 4) | Two test tenants: neither can see the other's tickets, servers, audit log or chat |
| A5 | Vendor event bus and many-account alarm intake (item 6) | An alarm in a second test account raises an incident for that tenant only |
| A6 | Meter and licence in the Core (item 7) | Over-limit and expired tenants are stopped; limits cannot be edited from the customer account |
| A7 | Onboarding automation, hosted console on HTTPS, operations (items 8 to 10) | A new test customer is live in under a day from one link |

A second AWS account is needed for A4 and A5 (a test customer). The user must create or approve it; nothing in this plan creates AWS resources without that approval.

## 6. Risks and how we handle them

| Risk | Handling |
|---|---|
| Cross-tenant data leak | Tenant prefix on every key, a mandatory tenant argument (no default), automated isolation tests as a release gate |
| Vendor account compromised means every customer's role is reachable | Per-customer ExternalId, short sessions, tag boundary, no secrets in code, MFA and least privilege on the vendor account, customer kill switch, CloudTrail in the customer's account |
| Customers worry about their data passing through the vendor | Data processing agreement, hosting in the customer's region, minimal retention, no server output kept beyond the ticket; offer self-hosted for those who refuse |
| Cost moves to the vendor (hosting and models) | Price the vendor-hosted tier to cover it; per-tenant model spend cap and metering |
| Model provider limits and failures | Paid keys, two working fallback slots, shorter time-outs (REL-001 3.4) |

## 7. Decisions needed

1. Where the vendor account runs, which AWS region(s), and who operates it and is on call.
2. Price of the vendor-hosted tier (LIC-001 prices were written for self-hosted).
3. Model keys: **decided, both are offered** (the customer brings their own key, or we supply one and bill it through with a per-tenant spend cap).
4. Test customer: **decided**, account 115891591036 is tenant 1 for now (a separate second account is still needed to prove isolation in step A4).
5. The data processing agreement and data-residency position (legal).

## Change history
| Version | Date | Author | Summary | Approval |
|---|---|---|---|---|
| 0.1 | 24 Nov 2026 | Product owner | First version: Model A design, build order and risks | Pending |
