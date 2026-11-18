# MATRIX: Speaker Script (10 minutes talk + 5 minutes demo)

**Speakers:** Shafeeq (hook, opening, business pitch and the ask) and Aravind (the technical parts and the demo controls).
**Total:** 15 minutes. Speak slowly; the script is about 1,300 words, which is 8.5 to 9.2 minutes at a calm pace, leaving a little
time for hand-overs and slide changes. `[click]` means move to the next slide or the next point on the slide.

## Timing at a glance

| # | Section | Speaker | Time |
|---|---|---|---|
| 1 | Hook and opening pitch | Shafeeq | 1:15 |
| 2 | What a desk of five costs, with and without MATRIX | Shafeeq | 1:30 |
| 3 | How MATRIX works (technical) | Aravind | 1:30 |
| 4 | Human and AI control (technical) | Aravind | 1:15 |
| 5 | Architecture and security (technical) | Aravind | 1:15 |
| 6 | Why MATRIX? Unique selling points | Shafeeq | 1:15 |
| 7 | Success metrics and adoption | Shafeeq | 0:45 |
| 8 | Roadmap and the ask | Shafeeq | 0:30 |
| | Hand-over buffer | | 0:45 |
| 9 | **Live demo** (Aravind drives, both speak) | Both | 5:00 |

---

## 1. Hook and opening pitch (Shafeeq, 1 min 15 sec)

Good morning, and thank you for your time. We are Shafeeq and Aravind, and we are here to answer one question.

**How many people does it take to answer an alarm at three in the morning, every night of the year?**

`[click]` The honest answer is about **five**. A week has 168 hours, and one engineer works about 40. So an L1 desk that never
closes needs a team of five, before leave and sickness.

And what do those five people do for most of the day? The same first checks. Log in, look at CPU, disk and services, find the
runbook, write the notes. Important work, but repetitive work.

**MATRIX is an autonomous L1 site reliability engineer for AWS and ServiceNow.** It works beside that team, every hour of every
day. It picks up each alarm within about a minute, investigates, writes the ticket, fixes what is safe to fix, and hands
everything else to your people with a clear reason.

We are not here to shrink your team. We are here to give them their time back. Please judge us on three outcomes: **faster
recovery, fewer unnecessary escalations, and a full record of everything the agent does.**

## 2. What a desk of five costs, with and without MATRIX (Shafeeq, 1 min 30 sec)

Let's put numbers on it. We used current market figures, and we label every assumption. `[click]`

| Item | Figure | Basis |
|---|---|---|
| L1 analyst, base salary (US market) | about **$50,000** a year | 2026 listings: $45,000 to $55,000 range |
| Loaded cost (tax, benefits, tools) | about **$65,000** a year | Our assumption: base salary times 1.3 |
| **A desk of five** | about **$325,000** a year, or **$27,000** a month | 5 times $65,000 |
| Cost to handle one L1 ticket | about **$15 to $22** | Industry benchmark ($15.56, 2016) and newer, less verified figures |
| MATRIX running cost, our pilot week | **under $1** platform, **$0.05** model | Measured in our dev account |
| Model cost for one investigation, paid model | about **half a cent** | Assumption: 30,000 tokens in, 2,000 out, at $0.15 and $0.60 per million |

A desk of five costs about **twenty-seven thousand dollars a month**. Hold that number in your head.

Not all of their work can be automated, but a large share repeats. Suppose MATRIX takes just **30 percent** of the repeated
first-line work. That is the capacity of one and a half engineers, about **eight thousand dollars a month** handed back to your
team, or a smaller rota for the same cover. That 30 percent is our assumption. **We measure the real figure in the pilot.**

On the other side, the running cost. In our pilot week, the platform cost under a dollar and the model five cents. A paid model
costs about half a cent per investigation. It will grow with volume, but it grows in cents, not in headcount.

These are US figures. In your region they will differ, and we will redo this with your numbers.

Now, Aravind will show you how it actually works.

## 3. How MATRIX works (Aravind, 1 min 30 sec)

Thank you, Shafeeq. Let me show you what happens under the hood. `[click]`

**One.** A CloudWatch alarm goes into alarm. An EventBridge rule calls our Lambda directly. A five-minute sweep catches any alarm
that was missed.

**Two.** MATRIX creates the ServiceNow incident through the REST API, with the server filled in and the AI group assigned. If an
incident for that alarm is already open, a duplicate guard stops a second one.

**Three.** It diagnoses. The model is given **read-only tools only**: health check, top CPU processes, disk, service status,
alarms. It also searches the knowledge index for the matching runbook. It has up to eight steps, and every step is written to
the ticket.

**Four.** It proposes **one fix**, as a function call, from a closed list of three. Then our code checks the proposal. The service
must be on the allow-list. A process ID and name must appear in the output the agent actually saw, and not be on the never-kill
list. If the model invents something, it is rejected and the incident is escalated.

**Five.** Low-risk fixes in dev, and patterns it has solved three times before, run automatically. Everything else becomes an
approval card in the console, and the approver's name is recorded.

**Six.** It waits, measures again, and judges recovery from the live output. If the problem is gone, it resolves the ticket. If
not, it escalates to L2 with the reason.

**Seven.** When a person resolves an escalation, MATRIX drafts a knowledge article and a playbook for review.

## 4. Human and AI control (Aravind, 1 min 15 sec)

The question every team asks: how much control does the AI get? Our answer is four levels. `[click]`

**Human only.** The executor role in AWS has an explicit **deny** for terminating instances, resizing, IAM changes and deleting
volumes. Even the optional decommission role needs a human to add a tag first, and the server must have been stopped for a hold period, seven days by default.

**AI assistant.** Read-only checks from chat, with the same tools. Nothing changes.

**Human plus AI.** A write tool shows an action card and waits for **Confirm**. The ticket number is validated in ServiceNow
before anything runs. Planned work such as patching, migration or a new server also needs an approved change.

**Autonomous.** Only three fixes: restart a listed service, clean old logs, or stop one runaway process. Nothing else is
reachable from an alarm.

`[click]` The limits are in code and in AWS permissions, not in the model's instructions. So telling the agent to "do it anyway"
changes nothing.

## 5. Architecture and security (Aravind, 1 min 15 sec)

Now the stack, from the top. `[click]`

The whole product is **one Python Lambda**, behind a Function URL, with a browser console. Triggers come from EventBridge. State
lives in managed services: **DynamoDB** for traces, approvals and learning drafts, **S3** for runbooks and the knowledge index.
ServiceNow remains the record of truth for tickets, work notes and knowledge.

Actions on servers go through **Systems Manager**, so there is no SSH and no inbound port. The Lambda assumes a **scoped
executor role** that can only touch instances tagged `matrix-managed` in the right environment. Every action goes to an audit
log.

The AI layer is a **gateway** with a primary model and up to three standbys. In our setup, NVIDIA is primary and Groq is the
standby. A rate limit, a rejected key or a missing model skips that model and tries the next, so one provider failing does not
stop the agent.

It deploys from one CloudFormation template. And it can be **stopped in minutes**: disable the alarm rule, or throttle the
function. Nothing is lost, because the tickets and alarms stay.

Over to Shafeeq.

## 6. Why MATRIX? Our unique selling points (Shafeeq, 1 min 15 sec)

A fair question: we already have monitoring and scripts. Why another tool? Monitoring tells you something is wrong. Scripts run
what you wrote. **MATRIX decides what to check, acts within limits, checks the result and updates the ticket.** `[click]`

Five things make it different.

**First, it works where you already work.** Your ServiceNow and your AWS account. Nothing new to run.

**Second, it is controlled by design.** A fixed fix list, code that checks the model, and hard limits in AWS.

**Third, it learns.** A resolved escalation becomes a draft article and playbook. A person approves it in the console, and it is
published into ServiceNow and AWS.

**Fourth, it covers more than L1 fixes.** Patching, migration, new servers and a staged decommission, each behind approval.

**Fifth, the cost is visible and low.** Tokens turn into dollars on the dashboard, next to AWS spend.

## 7. Success metrics and adoption (Shafeeq, 45 sec)

Technology matters only if it moves the business. We will measure **time to resolve, autonomous resolution rate,
human-intervention rate, escalations, SLA adherence and cost per ticket.** `[click]` The dashboard shows them, so nobody
reports them by hand.

To be transparent: we have **not published measured results**, and we will not claim any. What we can show is one real run:
alarm to ticket, diagnosis, an approved fix and a written result, in about **three minutes**, with every step on the ticket.

We recommend three stages: watch and recommend, then engineers confirm, then automatic for approved routine work in dev. One tag
on a server puts it in scope.

## 8. Roadmap and the ask (Shafeeq, 30 sec)

Today: Linux servers, ServiceNow and a dev pilot. Next: single sign-on, secrets in AWS Secrets Manager, a deployment pipeline, a
per-team cost report and Windows. The vision is a self-healing environment. We want to earn it with controls and measurements.

So our ask is simple: **agree a pilot scope, agree the metrics, and give us a set of non-production servers to start.**

Now, let us show you. Aravind will drive.

---

## 9. Live demo (both, 5 min)

**Roles.** Aravind drives the screen and explains what the system is doing. Shafeeq opens, adds the business meaning, and closes.
**Tabs to have open:** the console (Dashboard), CloudWatch alarm page, ServiceNow incident list, the console Knowledge page.

| Time | Voice | What to show | What to say |
|---|---|---|---|
| 0:00 to 0:30 | Shafeeq | **Dashboard**: open incidents, approvals, autonomous rate, cost card | "This is the console. At a glance: what is waiting, how MATRIX is performing, and what it costs." |
| 0:30 to 1:15 | Aravind | **Alarm, then the ticket**: CloudWatch alarm in alarm; switch to ServiceNow and refresh | "The alarm is firing. Nobody created a ticket. Here it is: assigned to the AI group, with the server filled in." |
| 1:15 to 2:00 | Aravind | **Work notes** on the incident | "These notes are written by MATRIX as it works: the runbook it used, and the diagnosis. It found a process using 98% of the CPU." |
| 2:00 to 2:45 | Aravind | **Approval card** in the console, then Confirm | "It proposes one fix: stop that process. It is not a pre-approved pattern, so it waits. The engineer sees the action, server and evidence, and confirms." |
| 2:45 to 3:30 | Aravind | **Result** in ServiceNow | "It measures again and writes the result to the ticket. If the problem is gone it resolves the ticket. If not, it escalates with the reason." |
| 3:30 to 4:15 | Shafeeq | **Knowledge page**: a learning draft waiting for review (View draft) | "This is how it learns. A resolved escalation produced a draft article and playbook. Safety checks ran first. A person approves it, and it is published." Do not click Approve unless the checks are green |
| 4:15 to 5:00 | Shafeeq | **Cost card** and close | "Model tokens turned into dollars, AWS before credits. Alarm to approved fix in minutes, every step on the ticket, and a person in control. That is MATRIX." |

### Before you go on stage (checklist, 15 minutes before)

1. The latest code is deployed in the Lambda, including `autonomy.py` (stale alarm fix) and `matrix_alarm_intake.py`. Run the Test event `{"matrix_task": "alarm_sweep"}`: no error.
2. The two EventBridge rules are enabled. No old alarm action is attached, or you will get a second ticket.
3. **Resolve any open incident for the demo alarm.** An open one blocks a new ticket.
4. Let the alarm return to **OK**. About **3 minutes before you present**, start the CPU load on the test server, so the alarm is firing and the incident exists when you begin.
5. Set `STATS_SINCE` to today, so old test records do not show on the dashboard.
6. Check **Observability**: the primary model and at least one standby are healthy.
7. Sign in on the machine you will present from, and test that the pop-up appears.
8. Do not show settings pages; they contain secrets.
9. **Rotate any key that was ever pasted into chat or a document before this demo.**

### If something fails (backup plan)

| Problem | What to do |
|---|---|
| No incident appears | Run the sweep test event in Lambda, or open the ticket from your rehearsal and say "this is from our last run" |
| The agent is slow | Keep talking about the control levels (section 4) and refresh every 20 seconds |
| A model error appears | Say "the next model takes over automatically" and refresh; the failover is a feature |
| Everything is down | Show screenshots of a finished incident (notes, approval, result) and the dashboard; keep them in a folder named Backup |

---

## Likely questions, and honest answers

| Question | Answer |
|---|---|
| So you are replacing five engineers? | No. MATRIX takes the repeated first-line checks and notes. People keep approvals and every L2 decision. Whether that frees time or reduces the rota depends on your ticket mix, and we size it with your numbers. The "five" is arithmetic for 24 by 7 cover (168 hours a week against about 40 per person), not a promise of headcount savings. |
| Where do the prices come from? | Salary ranges are 2026 US listings (about $45,000 to $55,000 for L1). The loaded multiplier of 1.3 is our assumption. The $15 to $22 ticket cost is an industry benchmark whose best-dated source is 2016, so treat it as indicative. The 30 percent is an assumption we will measure in the pilot. |
| What if the AI is wrong? | It can only choose from three fixes, code checks its proposal against real server output, and anything beyond low-risk dev work waits for a person. The AWS role also blocks destructive actions. |
| What about prompt injection, for example malicious text in a ticket? | The model can only call allow-listed tools and every proposal is checked in code, so injected text cannot create new abilities. It could mislead a diagnosis, which is why humans confirm. |
| Does our data leave AWS? | Ticket text and tool output go to the model provider you configure. Choose a provider whose terms you accept. |
| Is it production ready? | It is a pilot in a dev account on Linux servers. The documents list the open items (single sign-on, secrets in Secrets Manager, a deployment pipeline). |
| What does it cost to run? | In our first measured week the platform was under a dollar and the model five cents. It will rise with volume. The chargeback model explains how to share it. |
| Why not just scripts and automation? | Scripts run what you wrote. MATRIX decides which check to run, writes the notes, and learns from resolved tickets, inside the same limits. |
| What if we have no Change module in ServiceNow? | A setting lets planned work be tracked on an incident; the engineer's Confirm remains the approval. |
| How do we stop it? | In minutes: disable the alarm rules, or throttle the function. There is a seven-step ladder. |

## Sources for the market figures (checked 18 November 2026)

- L1 salary: [Salary.com, IT Help Desk Analyst](https://www.salary.com/research/salary/position/it-help-desk-analyst-salary) (about $56,800 average, about $49,300 entry level) and [PayScale, Help Desk Analyst](https://www.payscale.com/research/US/Job=Help_Desk_Analyst/Salary/7984c68f/Late-Career-Help-Desk-Desktop-Support-Tier-1) (early career about $40,000 to $49,000). We used a planning figure of $50,000.
- Cost per L1 ticket: [eesel.ai benchmark summary](https://www.eesel.ai/blog/cost-per-ticket-benchmarks), which cites a 2016 MetricNet figure of $15.56 for Level 1. Newer figures near $22 are repeated by secondary sites without a clear source. Replace with your own service desk's figure when you have it.
- Model price: Groq's published list price for `openai/gpt-oss-120b` ($0.15 in, $0.60 out per million tokens). NVIDIA's free endpoint is $0.

## Delivery tips

- Shafeeq owns the hook, the money and the ask; Aravind owns everything technical and the demo screen. Hand over by name.
- Do not read the slides; use them as prompts. One idea per slide.
- Slow down on the number "five" and on the three outcomes: these are what leaders remember.
- Say "assumption" every time you use one. It builds trust.
- If time runs short, shorten section 5; never drop the demo.
