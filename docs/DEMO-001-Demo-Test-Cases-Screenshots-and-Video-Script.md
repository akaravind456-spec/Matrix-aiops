# MATRIX: Demo Test Cases, Screenshots and Video Script

| Field | Value |
|---|---|
| Document ID | DEMO-001 |
| Owner | MATRIX product owner |
| Version / status | 0.1 / Draft |
| Classification | Customer-shareable after review |
| Effective date | 23 November 2026 |
| Applies to | MATRIX AIOps (this repository, `main`) |
| Related documents | MTX-02 (features), AIG-001 (agent behaviour), SUP-001 (troubleshooting) |

## 1. Purpose

This is the evidence pack for the demo: the test cases we ran against the live system, what happened, screenshots of the
console, and a shot-by-shot script for recording the demo video. All results below come from real runs on 23 November 2026
in AWS account 115891591036 (ap-southeast-2) against a ServiceNow developer instance. Nothing here is simulated.

Automated checks: 106 unit tests pass (`tests/`). The live cases below are the end-to-end checks.

## 2. Demo test cases

| # | Test case | Steps | Result | Pass |
|---|---|---|---|---|
| T1 | Agent fixes a stopped service with no human | nginx stopped on matrix-linux-02 (dev). Alarm incident raised. | Agent diagnosed, restarted nginx, checked health, resolved the ticket in about 40 seconds. Notes on the ticket are in plain words. | Yes |
| T2 | Agent closes a false alarm | Disk-High alarm raised while disk was at 35% and the alarm was back to OK. | Agent wrote "nothing to fix", closed the ticket (no action needed). | Yes |
| T3 | Restart opens its own ticket | Chat: "restart nginx on matrix-linux-02". | MATRIX opened an incident, showed Confirm and Cancel. After Confirm the restart ran and the ticket was resolved with a note (INC0010039). | Yes |
| T4 | A failed action keeps the ticket open | Restart nginx on a server without nginx, then Confirm. | The action reported the failure and the ticket stayed open with a note. | Yes |
| T5 | Deploy a new server from chat | "deploy a linux server named lifecycle-01 in ap-southeast-2b, t3.micro, dev". | Incident opened, plan shown, Confirm pressed, server launched (INC0010034). | Yes |
| T6 | Migrate it to another AZ from chat | Image, launch clone in 2a, validate, cutover. | Clone launched in ap-southeast-2a, passed instance, system and SSM checks, original stopped (INC0010035). | Yes |
| T7 | Decommission from chat | Assess, final backup image, stop. Repeated for four servers. | Each got its own incident, a backup image, and a stop with a 7-day hold. Nothing was terminated (INC0010033, 36, 37, 38). | Yes |
| T8 | Guardrails | Kill PID 1, kill a protected process, stop `sshd`, forged Confirm token, "terminate every server". | All refused with a plain reason; nothing changed. | Yes |
| T9 | Planned-work ticket gate | Planned work with no ticket. | MATRIX opens one itself; a closed ticket is never reused. | Yes |
| T10 | Account limit handled | Launch a clone while 4 servers ran (8 vCPU limit). | AWS refused. After freeing capacity the launch worked. The chat still shows the raw AWS wording. | Partly |

## 3. Screenshots

Taken from the S3-hosted console on 23 November 2026. Files are in `docs/images/`. Section 3.1 has one screenshot for each test case;
section 3.2 shows the step-by-step chat flows; section 3.3 shows the general console screens.

### 3.1 One screenshot per test case

**T1. Agent fixes a stopped service with no human (INC0010030).** The ticket notes show the fix, the health check, the status check and the automatic resolve.

![T1](images/T1-agent-fixes-nginx-INC0010030.png)

**T2. Agent closes a false alarm (INC0010027).** The agent checked disk, CPU, memory and the alarm, wrote "nothing to fix" and resolved the ticket.

![T2](images/T2-no-action-needed-INC0010027.png)

**T3. Restart opens its own ticket (INC0010039).** Chat screenshots of the Confirm card and the result are in 3.3. The ticket:

![T3](images/T3-restart-auto-ticket-INC0010039.png)

**T4. A failed action keeps the ticket open (INC0010028).** The restart failed (no nginx on that server) and the note says the ticket was not resolved.

![T4](images/T4-failed-action-stays-open-INC0010028.png)

**T5. Deploy a new server from chat (INC0010034).**

![T5](images/T5-deploy-INC0010034.png)

**T6. Migrate to another AZ from chat (INC0010035).**

![T6](images/T6-migrate-INC0010035.png)

**T7. Decommission from chat (INC0010033 and INC0010036).** Assessment, final backup image, stop with a 7-day hold, then the ticket resolved. (INC0010036 was titled "Migration" because the server name contained "migrated"; this is fixed for new tickets.)

![T7](images/T7-decommission-INC0010033-and-36.png)

**T8. Guardrails.** Asking to kill process 1 and stop sshd is refused in plain words and nothing changes.

![T8](images/T8-guardrail-refusal.png)

**T9. Planned-work ticket gate.** No ticket number was typed in T3, T5, T6 or T7; MATRIX opened each one. See those screenshots.

**T10. Account limit.** No screenshot: the AWS `VcpuLimitExceeded` error was seen in the chat during the run, and it could not be reproduced without launching extra servers. The wording is still raw AWS text.

### 3.2 Step-by-step screenshots of the chat flows

These were taken on 23 November 2026 from the hosted console while running a fresh server called `demo-01` through the whole cycle.
Each step shows what the engineer typed, the Confirm card MATRIX raised, and the result. The incident was opened by MATRIX each time.

#### Flow A. Deploy a new server (INC0010041)
1. Ask in plain words. MATRIX opens the incident, shows the plan and a Confirm card.

![Deploy step 1](images/steps/deploy-1-request-and-confirm.png)

2. Press Confirm. The server is launched and the result is shown.

![Deploy step 2](images/steps/deploy-2-launched.png)

#### Flow B. Migrate it to another availability zone (INC0010042)
1. Ask to migrate. MATRIX opens the incident and asks to create the backup image first.

![Migrate step 1](images/steps/migrate-1-request-image-confirm.png)

2. Press Confirm. The image is being created (it takes a few minutes).

![Migrate step 2](images/steps/migrate-2-image-created.png)

3. Ask to launch the clone in the other zone. A Confirm card appears.

![Migrate step 3](images/steps/migrate-3-launch-clone-confirm.png)

4. Press Confirm. The clone is launched; the original is untouched. (If the image is not ready yet, MATRIX refuses with "not available yet" instead of guessing.)

![Migrate step 4](images/steps/migrate-4-clone-launched.png)

5. After the clone passes its health checks, ask to finish. MATRIX validates it and asks to confirm the cutover.

![Migrate step 5](images/steps/migrate-5-cutover-confirm.png)

6. Press Confirm. The old server is stopped and the clone is live. The result is a plain sentence.

![Migrate step 6](images/steps/migrate-6-cutover-done.png)

#### Flow C. Decommission a server (stopped, never terminated)
1. Ask to decommission. MATRIX checks for Elastic IPs and load balancers, then asks to create the final backup image.

![Decommission step 1](images/steps/decommission-1-request-backup-confirm.png)

2. Press Confirm. The backup image is being created.

![Decommission step 2](images/steps/decommission-2-backup-started.png)

3. When the image is available, ask to stop the server. A Confirm card appears.

![Decommission step 3](images/steps/decommission-3-stop-confirm.png)

4. Press Confirm. The server is stopped and kept stopped for 7 days. Termination stays a separate step that needs a person to add a tag.

![Decommission step 4](images/steps/decommission-4-stopped-hold.png)

#### Flow D. Restart with an automatic ticket
See section 3.3 (restart with Confirm, then the closed ticket).

### 3.3 General console screens

#### Dashboard
What MATRIX is doing, what needs a person, performance and cost.

![Dashboard](images/01-dashboard.png)

#### Chat home
Plain-language chat with suggested actions.

![Chat home](images/02-chat-home.png)

#### Restart opens a ticket and asks for Confirm
No incident number was typed. MATRIX opened the incident and queued the action.

![Restart with Confirm](images/03-chat-restart-ticket-confirm.png)

#### After Confirm: result and closed ticket
The result is shown in the chat and the ticket is resolved with a work note.

![Confirmed and closed](images/06-chat-confirmed-ticket-closed.png)

#### AI observability
Traces, latency, tool calls, model slots and failures.

![Observability](images/04-observability.png)

#### Knowledge and runbooks
The runbooks the agent follows, from ServiceNow and the ops bucket.

![Knowledge and runbooks](images/05-knowledge-runbooks.png)

## 4. Demo video script (about 6 minutes)

The video is recorded by a person from the hosted console (screen capture with voice-over). Keep the browser at 1440 by 900.
Before recording: sign in once, keep ServiceNow open in a second tab, wake the ServiceNow instance, and make sure
matrix-linux-02 is running.

| Time | Screen | Say | Do |
|---|---|---|---|
| 0:00 | Dashboard | "MATRIX is an autonomous L1 engineer. It works inside ServiceNow and AWS. Anything risky waits for one human click." | Show the cards: autonomous rate, cost, licence meter |
| 0:40 | Slide or Product Overview | "The problem: alarms, repeated fixes, and night pages. MATRIX reads the alarm, checks, fixes what is safe and explains everything on the ticket." | Show the five steps (alarm, ticket, diagnose, fix, verify) |
| 1:10 | Terminal or AWS | "To prove it, I stop nginx on a dev server." | Stop nginx on matrix-linux-02 (through the chat with Confirm, or SSM) |
| 1:40 | Dashboard or chat | "The alarm raises an incident." | Raise the alarm incident |
| 2:00 | ServiceNow ticket | "Watch the notes: it follows the runbook, finds nginx inactive, restarts it, checks health, and resolves the ticket. No human." | Show the timeline, about 40 seconds |
| 3:00 | Chat | "Now a human request. I ask it to restart nginx. I do not type an incident number." | Send "restart nginx on matrix-linux-02" |
| 3:25 | Chat | "MATRIX opened the ticket itself and waits for my Confirm." | Point at the Confirm card, press Confirm |
| 3:50 | Chat and ServiceNow | "Result in chat, and the ticket is resolved with a work note." | Show both |
| 4:10 | Chat | "Planned work uses the same pattern: deploy, migrate to another AZ, then decommission, each behind a ticket." | Show a prepared chat for a migration or decommission, or the ticket list INC0010033 to 38 |
| 4:50 | Chat | "Guardrails: it will not kill process 1 or stop SSH." | Type "kill PID 1", show the refusal |
| 5:15 | Observability | "Every run is traced: model, tools, time and cost." | Open one trace |
| 5:40 | Dashboard | "Customers run it in their own AWS account. Close: low human effort, high safe resolution." | Return to the dashboard |

Recording tips: use short pauses while the agent works, speed up waits in editing, and never show passwords, keys or the Function URL
token. Hide the sign-in screen when recording.

## Change history
| Version | Date | Author | Summary | Approval |
|---|---|---|---|---|
| 0.1 | 23 Nov 2026 | Product owner | First version: live test results, six screenshots, video script | Pending |
