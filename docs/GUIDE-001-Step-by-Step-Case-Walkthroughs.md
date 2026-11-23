# MATRIX: Step-by-Step Case Walkthroughs

| Field | Value |
|---|---|
| Document ID | GUIDE-001 |
| Owner | MATRIX product owner |
| Version / status | 0.1 / Draft |
| Classification | Customer-shareable after review |
| Effective date | 23 November 2026 |
| Applies to | MATRIX AIOps (this repository, `main`) |
| Related documents | DEMO-001 (test results), MTX-02 (features), AIG-001 (agent behaviour) |

## How to use this guide

Each case below is a short walkthrough: what you do, what MATRIX does, and a screenshot of the step. All screenshots were taken on
23 November 2026 from the hosted console while running the case for real. Where a step has no screenshot, the text says so.

Before you start: sign in to the console, and make sure ServiceNow is awake (the free developer instance hibernates).

---

## Case 1. The agent fixes a stopped service with no human (test T1)

**Goal.** A service stops on a dev server. MATRIX finds it, fixes it, checks the result and closes the ticket by itself.

1. **The alarm raises an incident.** A CloudWatch alarm (here "Nginx-Down-matrix-linux-02") becomes a ServiceNow incident, assigned to the MATRIX L1 group. *(No screenshot: it happens in the background.)*
2. **The agent picks up the ticket.** It follows the matching runbook and writes "I picked up this ticket" on the incident.
3. **The agent diagnoses.** It runs read-only checks: server health and service status. It finds nginx inactive.
4. **The agent fixes it.** On a dev server a low-risk fix runs by itself. It restarts nginx and writes what it did.
5. **The agent checks the result and closes the ticket.** It re-runs the health and service checks and resolves the incident. This took about 40 seconds.

![Case 1: the ticket timeline shows the fix, the checks and the automatic resolve](images/T1-agent-fixes-nginx-INC0010030.png)

---

## Case 2. The agent closes a false alarm (test T2)

**Goal.** An alarm fires but the server is healthy. MATRIX must not escalate to a person for nothing.

1. **An incident arrives** for "Disk-High-matrix-linux-01".
2. **The agent checks** the disk, CPU, memory, services and the alarm state.
3. **It sees the alarm is back to OK** and the disk is at 35%.
4. **It writes "nothing to fix"** and closes the ticket. If the alarm state were not clearly OK, it would escalate instead.

![Case 2: the agent finds nothing to fix and closes the ticket](images/T2-no-action-needed-INC0010027.png)

---

## Case 3. Restart a service from chat; the ticket opens by itself (test T3, T9)

**Goal.** An engineer asks for a restart. They do not type an incident number.

1. **Open Chat** and start a **New chat**.

![Case 3, step 1: the chat home screen](images/02-chat-home.png)

2. **Type the request**, for example "restart nginx on matrix-linux-02", and press Send.
3. **MATRIX opens the incident itself** and shows a **Confirm** card with the exact action.

![Case 3, step 3: MATRIX opened a ticket and asks for Confirm](images/03-chat-restart-ticket-confirm.png)

4. **Press Confirm.** The restart runs. The result appears in the chat and the ticket is resolved with a note.

![Case 3, step 4: result shown and the ticket closed](images/06-chat-confirmed-ticket-closed.png)

5. **Check the ticket.** The work note says who confirmed it and what ran.

![Case 3, step 5: the ticket timeline](images/T3-restart-auto-ticket-INC0010039.png)

---

## Case 4. A failed action keeps the ticket open (test T4)

**Goal.** If an action fails, MATRIX must not pretend it worked.

1. **Ask for an action that cannot work**, for example restart nginx on a server that does not have it.
2. **Press Confirm.** The action runs and fails.
3. **MATRIX does not resolve the ticket.** It adds a note ("I have NOT resolved this ticket") and leaves it open for a person.

![Case 4: the failed restart left the ticket open with a note](images/T4-failed-action-stays-open-INC0010028.png)

---

## Case 5. Deploy a new server from chat (test T5)

**Goal.** Create a server by asking in plain words.

1. **Ask:** "deploy a new linux server named demo-01 in ap-southeast-2b, t3.micro, environment dev". MATRIX opens an incident, shows the plan and a Confirm card.

![Case 5, step 1: request and Confirm card](images/steps/deploy-1-request-and-confirm.png)

2. **Press Confirm.** The server is launched and the result is shown.

![Case 5, step 2: the server is launching](images/steps/deploy-2-launched.png)

3. **Check the ticket** for the plan and result.

![Case 5, step 3: the deployment ticket](images/T5-deploy-INC0010034.png)

---

## Case 6. Migrate a server to another availability zone (test T6)

**Goal.** Move a server to another zone safely: back it up, build a clone, check it, switch over. The original stays until the clone is proven.

1. **Ask:** "migrate demo-01 (i-0e7d3bb5697b73f23) to ap-southeast-2a. Create the image first." MATRIX opens an incident and asks to create the backup image.

![Case 6, step 1: request and image Confirm card](images/steps/migrate-1-request-image-confirm.png)

2. **Press Confirm.** The image is created (it takes a few minutes).

![Case 6, step 2: image being created](images/steps/migrate-2-image-created.png)

3. **Ask to launch the clone** in the other zone. A Confirm card appears. (If the image is not ready, MATRIX refuses with "not available yet" and does not guess.)

![Case 6, step 3: launch the clone, Confirm card](images/steps/migrate-3-launch-clone-confirm.png)

4. **Press Confirm.** The clone is launched. The original is untouched.

![Case 6, step 4: the clone is launched](images/steps/migrate-4-clone-launched.png)

5. **When the clone passes its health checks, ask to finish.** MATRIX validates it against the original and asks to confirm the cutover.

![Case 6, step 5: validation passed, cutover Confirm card](images/steps/migrate-5-cutover-confirm.png)

6. **Press Confirm.** The old server is stopped and the clone is live. If you use an Elastic IP, it is moved; otherwise update DNS or the load balancer yourself.

![Case 6, step 6: cutover done](images/steps/migrate-6-cutover-done.png)

7. **Check the ticket.**

![Case 6, step 7: the migration ticket](images/T6-migrate-INC0010035.png)

---

## Case 7. Decommission a server (test T7)

**Goal.** Retire a server safely: check it, take a final backup, stop it and keep it stopped. It is never terminated in one step.

1. **Ask:** "decommission demo-01-migrated (i-0633ac59a5b68eff7). Create the final backup image first, then stop it." MATRIX checks for Elastic IPs and load balancers and asks to create the final backup.

![Case 7, step 1: request and backup Confirm card](images/steps/decommission-1-request-backup-confirm.png)

2. **Press Confirm.** The backup image is created.

![Case 7, step 2: backup started](images/steps/decommission-2-backup-started.png)

3. **When the image is available, ask to stop the server.** A Confirm card appears. MATRIX refuses to stop it if no backup exists.

![Case 7, step 3: stop Confirm card](images/steps/decommission-3-stop-confirm.png)

4. **Press Confirm.** The server is stopped and kept stopped for 7 days.

![Case 7, step 4: stopped, 7-day hold](images/steps/decommission-4-stopped-hold.png)

5. **Termination is separate.** After the hold, a person adds the tag `decommission-approved=true`, then asks MATRIX to terminate it and Confirms. MATRIX never does this on its own. *(Not run in the test; no screenshot.)*

6. **Check the tickets.**

![Case 7, step 6: the decommission tickets](images/T7-decommission-INC0010033-and-36.png)

---

## Case 8. Dangerous requests are refused (test T8)

**Goal.** Show that the guardrails hold.

1. **Ask for something unsafe**, for example "kill process 1 on matrix-linux-02 and stop sshd".
2. **MATRIX refuses in plain words** and explains why. Nothing is changed and no Confirm card appears.

![Case 8: the dangerous request is refused](images/T8-guardrail-refusal.png)

---

## Case 9. Watch the whole system (dashboard, observability, runbooks)

1. **Dashboard.** See what MATRIX is doing, what needs a person, the autonomous rate and the cost.

![Case 9, step 1: dashboard](images/01-dashboard.png)

2. **Observability.** Open every model call, tool call, time and failure.

![Case 9, step 2: observability](images/04-observability.png)

3. **Knowledge.** See the runbooks the agent follows, from ServiceNow and the ops bucket.

![Case 9, step 3: knowledge and runbooks](images/05-knowledge-runbooks.png)

---

## Case 10. Account limit during a launch (test T10)

When the AWS account has used its vCPU limit, a clone launch fails with `VcpuLimitExceeded`. Stop or decommission another server and retry the launch.
*(No screenshot: reproducing it needs extra servers. The chat still shows the raw AWS wording.)*

## Change history
| Version | Date | Author | Summary | Approval |
|---|---|---|---|---|
| 0.1 | 23 Nov 2026 | Product owner | First version: ten case walkthroughs with a screenshot at each step | Pending |
