# MATRIX AIOps: Project Memory (handover notes for the next session)

| Field | Value |
|---|---|
| Document ID | MEM-001 |
| Written | 24 November 2026 |
| Purpose | What the assistant knows so far, so work can resume without re-deriving it |
| Classification | Internal. **Contains no passwords, keys or tokens. Never add any.** |

## 1. Project in one paragraph
MATRIX is an autonomous L1 engineer: it reads CloudWatch alarms, opens and works ServiceNow incidents, diagnoses and fixes safe problems on
tagged EC2 servers, and asks one human click (Confirm) for anything risky. One Python Lambda (`matrix-console`, Python 3.12, Function URL) does everything.
Repo: `C:\Users\Shafeeq Basha\Documents\Matrix-aiops`, GitHub `akaravind456-spec/Matrix-aiops`, branch `main`. Team: Aravind and Shafeeq.

## 2. Accounts and places
| Item | Value |
|---|---|
| Main AWS account (the real, live one) | 115891591036, region ap-southeast-2. Holds the Lambda, DynamoDB `matrix-data`, S3 `matrix-ops-ak`, UI bucket, EventBridge rules, executor role `matrix-executor-dev` |
| Tester AWS account (separate) | 248124046247, same region. Root email is the owner's Gmail. Free plan with credits (about $60 left on 24 Nov 2026), already has some resources (IAM, CloudFormation, Lambda, EC2, Systems Manager were recently visited) |
| Console UI | S3 website `matrix-console-ui-115891591036`, HTTP only |
| ServiceNow | a free developer instance that hibernates; resolved incidents stay `active=true`, so filters use `stateIN1,2,3` |
| CLI | AWS CLI v2 at `C:\Users\Shafeeq Basha\awscli\Amazon\AWSCLIV2\aws.exe`; profile `matrix-readonly` is IAM user `claude-readonly` in 115891591036 (it can deploy the Lambda). Profile `tester` has only a region set; sign-in did not complete |
| Git | `C:\Program Files\Git\cmd\git.exe`; commits are by Shafeeq Basha and end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` |

## 3. Rules the owner set (follow them)
1. The owner signs in to AWS, ServiceNow and similar sites **themselves**. The assistant never types or stores their passwords. If a password is pasted into chat, tell the owner to change it.
2. Ask before anything that creates, changes or deletes in AWS, unless already authorised. Already authorised: Lambda code deploys, the UI bucket upload, demo alarms and logs, git pushes.
3. **In the tester account 248124046247: do not change anything that already exists there.** Only add new things, and ask before each create. Credits are limited.
4. Never paste keys or tokens into chat, files or commits. No force-push. Commit and push only when asked.
5. **Do not delete the console user `tester`** from `USERS`.
6. Deploy Lambda code directly **and** push to git. Use simple wording in replies.
7. Live secrets were shared earlier during development (model keys, ServiceNow password, console passwords, token secret, agent key). The owner was told to rotate them. Never repeat them.

## 4. What is built and live (main account)
- **Agent:** alarm to incident to agent (diagnose, then fix / escalate / no action), vet, auto-run on dev or approval card on prod, 15-second wait, verdict, resolve. A 5-minute sweep picks up missed tickets.
- **Chat:** ticket gate (opens INC/CHG itself), Confirm button for writes, parallel tool calls, repeat-call cap, plain-text results, guardrail refusals in plain words.
- **Planned work from chat:** deploy, migrate (image, clone, validate, cutover), decommission (assess, final backup, stop with 7-day hold; terminate needs a human tag `decommission-approved=true` and was never run), patching, resize, and "operation" (restart, reboot, start, stop, kill, clear logs).
- **Safety:** tag boundary (`matrix-managed=true`, `environment`), fix catalogue and vetting, protected processes, kill switch, a failed action never closes a ticket.
- **Licence:** signed key (Ed25519, pure Python), soft usage meter on the Dashboard, `LICENSE_ENFORCE` switch (off). Vendor signing tool `tools/matrix_licence_sign.py`. **The private key for the public key in the product is not available**; either find it or make a new pair and redeploy.
- **Docs:** 24 documents in `docs/` (see `docs/README.md`), PDF build script `tools/docs-to-pdf.mjs`, PDF pack in `dist/` (not committed). Screenshots in `docs/images/`.
- **Tests:** 128 pass (`tests/`). Run with the portable Python `%TEMP%\pyemb\py\python.exe`, `PYTHONIOENCODING=utf-8`, path `['lambda','tests','.']`.
- **Final state of test servers (main account):** only matrix-linux-01 running; matrix-linux-02, demo-01, demo-01-migrated, lifecycle-01, lifecycle-01-migrated, test-03 and test-03-migrated are stopped, with backup images. Nothing has been terminated.

## 5. Decisions taken
- **Delivery model A (vendor-hosted) is the main offer** (MDA-001): the brain runs in the vendor account, the customer installs only a cross-account role with an ExternalId plus an alarm-forwarding rule. Self-hosted with a compiled build and signed key is a premium tier. The current all-in-customer-account version is for trusted pilots only.
- **Model keys: both options** (customer brings their own, or the vendor supplies and bills through with a spend cap).
- Prices in LIC-001 are proposals, **not approved**. LIC-001 section 9 is out of date (it says no signed key exists).
- Support tiers: Standard 18% and Premium 25% of the licence (hours and response times undecided).

## 6. Model A build order (MDA-001) and where we are
| Step | Work | State |
|---|---|---|
| A1 | `ExternalId` option on the executor role template | Done, in git |
| A2 | Tenant record and cross-account session helper (`lambda/matrix_tenant.py`, `tests/test_tenant.py`, `_session` in `matrix_guardrails.py`) | In git (commit 9db3d0d). **Not deployed**: it was rolled back off the live Lambda because it was first built against the real account |
| A3 | Per-tenant secrets and ServiceNow settings | Not started |
| A4 | Tenant passed through every action, isolation tests (needs the tester account) | Not started |
| A5 | Vendor event bus for alarms from many accounts | Not started |
| A6 | Meter and licence enforced in the Core | Not started |
| A7 | Onboarding automation, HTTPS console, operations | Not started |

## 7. Open items
- Signing key decision (find the old private key or make a new pair).
- Rotate the shared secrets; clean the repo history.
- Approve prices and support hours; legal terms.
- `frontend/matrix-ui.html` has an uncommitted change that removes the licence warning banners that are in git. The owner has not decided keep or revert.
- Model slots: both `gpt-oss-120b` standby slots return HTTP 400 on tools; failover takes about 65 seconds; the primary free NVIDIA model gets rate limited. A paid key is advised for customers.
- Account vCPU limit message (T10) is still raw AWS text. The console is HTTP only.
- The compiled build script `tools/build-release.sh` needs Docker and has not been run.

## 8. Lessons and pitfalls (so they are not repeated)
- **Never write Lambda source files with PowerShell `Set-Content` or pipes.** It mangled `matrix_guardrails.py` (line breaks and encoding) and took the live Lambda down for a few minutes (HTTP 502). Use `git show ... > file` in bash, or Python, then `py_compile` every file before deploying.
- Deploy recipe: zip `lambda/*.py` flat (Python zipfile, names without folders), `lambda update-function-code`, `wait function-updated`, then run a live chat read as a check. After any deploy, check the CloudWatch log for `Runtime.UserCodeSyntaxError`.
- Python edit pitfalls in heredocs: `\b` becomes backspace and `\n` a real newline; use `chr(92)`. Source files are CRLF; keep their line endings.
- `boto3` is stubbed in the unit tests, so `boto3.Session(...)` returns None there.
- Foreground `sleep` is blocked in the shell; use background tasks.
- Resolved incidents stay `active=true` in ServiceNow; always filter by state.
- A pasted screenshot showed the owner trying the AWS **sign-up** page with a mistyped email (`gamil`). Use the sign-in page `https://248124046247.signin.aws.amazon.com/console`.
- The account-wide EC2 vCPU limit is 8, so about four t3.micro servers can run at once.

## 9. Next steps (suggested order)
1. Read-only look at the tester account (EC2, Lambda, CloudFormation, spend) without changing anything.
2. Settle the signing key; prove licence enforcement on a test Lambda.
3. Redeploy A2 only when the tenant path is tested against the tester account.
4. A3, then A4 with two accounts; then A5 to A7.
5. Update LIC-001 section 9; approve prices; fix the model slots; paid model key.

## Change history
| Version | Date | Author | Summary | Approval |
|---|---|---|---|---|
| 0.1 | 24 Nov 2026 | Assistant | First memory snapshot | n/a |
