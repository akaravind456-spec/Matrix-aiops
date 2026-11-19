# MATRIX: Pitch Script (5 minutes talk, 10 minutes demo and Q&A)

**Deck:** `MATRIX-Product-Deck.pptx` (9 slides, same order as below). **Team:** Group C, Shafeeq and Aravind.
**Plan:** slides 1 to 5 are the 5-minute pitch (about 700 spoken words). Slides 6 to 9 are on screen during the 10-minute demo and Q&A.
**Tone:** a sales pitch to leaders. Open with the problem and the "hire an engineer" idea, lead with impact, keep the technical
part short and direct. No stories. Leader words: impact, risk, governance, productivity, scale, audit, pilot.

| Slide | Speaker | Time | Message |
|---|---|---|---|
| 1 Our product | Shafeeq | 0:50 | The hire: an SRE engineer who works 24/7. That engineer is the MATRIX SRE Agent |
| 2 What and why | Shafeeq | 1:00 | Problem statement, deterministic, automated, governed, why MATRIX |
| 3 Architecture and stack | Aravind | 1:30 | How it is built, security, observability |
| 4 Deployment, cost, support | Aravind then Shafeeq | 1:10 | How it lands, how it is priced, who supports it |
| 5 Future updates | Shafeeq | 0:40 | Where it goes, including multi-cloud, and the ask |
| 6 to 9 Demo | Aravind drives | 10:00 | Live demo and Q&A |

---

## Pitch (5 minutes)

### Slide 1: Our product (Shafeeq, 0:50)
Good morning. We are Group C: Aravind and Shafeeq.

Let me start with a simple idea. **Imagine you could hire one SRE engineer who works 24 hours a day, 7 days a week. Who never
takes a day off. Who picks up your repeated L1 issues the moment they appear, resolves them quicker, writes down everything they
do, and never makes a risky change without your approval.**

Every operations leader wants that engineer. **That engineer is our MATRIX SRE Agent.** `[click]`

MATRIX is built natively on AWS and works inside the ServiceNow you already use. It learns, analyses, decides, executes and
verifies, with a person in control of anything risky. The impact: **faster fixes, fewer escalations to senior engineers, and a
complete record of everything the agent does.**

### Slide 2: What and why (Shafeeq, 1:00)
Here is the problem. Most first-line incidents repeat. The first response is slow, the fix depends on who is on shift, the notes
are written late, and risky changes are approved over chat with no record. `[click on the middle column]`

MATRIX answers that as an **SRE agent that is deterministic, automated and governed**.
- **Deterministic:** the agent can only choose from a closed list of fixes, and our code checks every choice. It cannot invent an action.
- **Automated:** from alarm to a verified fix, with no waiting for a free engineer.
- **Governed:** a person approves anything risky.

Why MATRIX? It is **AWS-native**, so there is nothing new to host. It **learns** from every closed ticket. It runs on **several AI
models** and switches automatically if one fails. Every step is **audited**. And the design is **cloud-ready**: AWS today, other
clouds next. Now Aravind will show how it is built. `[click]`

### Slide 3: Architecture and stack (Aravind, 1:30)
Thank you, Shafeeq. This is the MATRIX architecture. I will take it from the top. `[point to each layer]`

**One: autonomous incident management.** An analysis agent collects evidence. A decision agent chooses a safe fix. A person
approves critical actions. An execution agent runs the approved fix. A verification agent checks the result and closes the ticket.

**Two: the chat and tools.** An engineer can ask in plain language, and use deployment, decommission, migration and patching
tools, each behind approval.

**Three: the multi-model gateway.** NVIDIA is primary, Groq is the standby. It checks health, fails over automatically, and
controls cost.

**Four: continuous learning.** When an engineer closes a ticket, MATRIX drafts a runbook and a playbook. A person approves them,
and the next incident benefits.

**Five: security and guardrails.** Four checks: ticket, tag, command and human approval. On top of that, AWS itself enforces
least privilege with IAM, and access is role-based. These limits live in the platform, not in the AI's instructions.

The stack is on the right: Lambda, EventBridge, DynamoDB, S3, Systems Manager, CloudWatch and ServiceNow. For **observability**,
every model call and every action is recorded: which model answered, what it cost, who approved, and what changed. `[click]`

### Slide 4: Deployment, cost and support (Aravind 0:30, Shafeeq 0:40)
**Aravind:** Deployment is simple. MATRIX runs inside **your own AWS account**, from one template and one form. A server comes
into scope when you tag it. We recommend a staged pilot: first watch, then confirm, then automate.

**Shafeeq:** On cost, the licence follows what you use: **servers and approver seats**. There is no per-ticket charge. AWS and AI
usage are shown on the dashboard, in dollars, so there are no surprises. We will confirm the figures with you in the pilot.

For support: three tiers, your operations team, the platform owner and product engineering. A **stop switch** works in
minutes, and everything is recorded on the ticket. `[click]`

### Slide 5: Future updates (Shafeeq, 0:40)
Where next? **Next:** single sign-on with MFA, secrets in AWS Secrets Manager, a release pipeline and alerts. **Later:**
**multi-cloud**, Windows servers, more ticketing tools, and a view across accounts. **Vision:** a self-healing enterprise, where
repeat causes go back to engineering and incidents fall, not just get fixed faster.

So back to where we started. You wanted an SRE engineer who never sleeps. **Agree a pilot, agree the measures, and give us a few
test servers, and you can have one.** Now let us show you. Aravind will drive.

---

## Demo (10 minutes including Q&A)

**Test case:** a runaway process on a test Linux server drives CPU high. The alarm is already in ALARM and the incident exists
before you start. **Do not demo the ticket being raised automatically.** The demo is an **L2 engineer working with the agent**.

| Time | Slide | Who | What to do and say |
|---|---|---|---|
| 0:00 to 1:00 | 6 | Aravind | Sign in as an L2 engineer. "An alarm is already raised. I am the L2 engineer. I ask the agent in plain language." Type: *What is wrong with the test server?* |
| 1:00 to 2:30 | 6 | Aravind | The agent runs read-only checks and explains: one process uses the CPU. "Notice it shows its evidence." Open the incident to show the work notes |
| 2:30 to 4:00 | 7 | Aravind | The agent proposes **one** fix. "It can only pick from a closed list. The card names the action and the server." Click **Confirm** as the engineer. Say: "The agent cannot approve its own action" |
| 4:00 to 5:00 | 7 | Aravind | It measures again and reports the result. If it cannot fix, it escalates and states the reason |
| 5:00 to 6:00 | 8 | Shafeeq | Knowledge page. "A closed ticket becomes a draft runbook and playbook. Checks block secrets. A person approves" |
| 6:00 to 6:45 | 9 | Shafeeq | Dashboard. "Resolved by the agent, escalations, time to resolve, cost in dollars, licence use" |
| 6:45 to 10:00 | 9 | Both | Q&A |

**Role-based access (one sentence if asked):** each user signs in with a role. Engineers see their own work, leads see the whole
team's traces, and the agent's own identity can never approve or upload anything.

**Keep one flow:** open the chat, the incident, the Knowledge page and the dashboard in the **same order as the slides**, in
separate browser windows side by side, so you never hunt for tabs.

**Close on the opening line.** At the end of the Q&A, say: "You asked for an SRE engineer who works 24/7. Meet the MATRIX SRE
Agent."

### If the demo goes wrong
- Keep a calm, neutral face. Say: **"Let me show you the saved run of the same case,"** and switch to the screenshots on slides 6 to 9.
- Do not apologise twice. Keep explaining the safety rules while the page reloads.
- If the model is slow or errors: "The next model in the chain takes over automatically." Refresh once.
- Keep a backup folder with screenshots and the recorded demo video.

---

## Q&A: short answers

| Question | Answer |
|---|---|
| Does it replace engineers? | No. It takes the repeated first checks. People keep approvals and the hard problems |
| Does it fix every L1 issue? | It handles the repeated L1 issues it has a safe fix for. Anything else it investigates, explains and hands to a person with the reason |
| What if the AI is wrong? | It can only pick from a closed list, code checks the choice against real data, and a person approves risk |
| Is it secure? | Four checks plus AWS IAM, role-based access, and everything audited. We are open about what is still to do: SSO, MFA and secrets storage |
| Does it support other clouds? | The design is cloud-ready. AWS is what works today. Multi-cloud is on the roadmap |
| What does it cost? | Licence by servers and seats, no per-ticket charge. Exact figures are confirmed with you in the pilot |
| How do we stop it? | A stop switch works in minutes. Nothing is lost |
| Where does data go? | Ticket text goes to the AI provider you choose. Pick one whose terms you accept |
| What do you measure? | Time to resolve, fixed by the agent, escalated, approvals, cost per ticket. All on the dashboard |

---

## Checklist: the feedback and how this version answers it

| Feedback | How it is handled |
|---|---|
| Do not commit to cost numbers, no "approximately" | No cost figures anywhere in the deck or script |
| Do not say "three steps" | Removed. The flow is shown as five named stages |
| Do not say AWS "isn't allowing" | Reworded: "AWS itself enforces least privilege with IAM" |
| Do not mention automatic tickets not being logged | Not mentioned |
| MATRIX name in the architecture diagram | The diagram title and layers carry MATRIX AIOps |
| Do not say "3 minutes" | Removed |
| Face reaction when the demo goes wrong | "If the demo goes wrong" section |
| Agent stopped without saying why | See open item 1 below |
| RBAC, normal users and admin privileges | Slide 3 chip, one-sentence answer above. See open item 2 |
| Start with what the agent can do | Slide 1 opens with the hire, then the five stages and the impact |
| Script 5 minutes, direct on technical parts | Pitch is 5 minutes, architecture walk is direct |
| Mention Group C, no story | Slide 1 intro. The hire idea is a short framing, not a story |
| SRE agent, problem statement, deterministic, automated | Slides 1 and 2 |
| Do not demo the ticket being raised | Demo starts with the alarm and ticket already there |
| Show the L2 engineer interacting with the agent | Slides 6 and 7 |
| Tabs break the flow | One window order, matching the slides |
| Explain the architecture diagram | Slide 3, layer by layer |
| Multi-cloud | Slides 2 and 5, as roadmap |
| Cost model was weak | Slide 4: licence model, usage visible, pilot to confirm |
| Deployment and support model | Slide 4 |
| Overall observability | Slide 3 (spoken) and the observability banner |
| Words leaders want | Impact, governance, risk, productivity, audit, scale, pilot |
| Sales voice, not an engineer's | Benefit first in every line |
| Impact at the start and the end | Slide 1 and the closing line |
| Intro about us, transitions | Slide 1, and a hand-over line on every slide |
| Governance and security | Slide 3, five layers and four checks |
| Opening: hire an SRE engineer who works 24/7 | Slide 1, and it returns at the end of slide 5 and the demo |

## Checklist: the 14 submission requirements

| # | Requirement | Where |
|---|---|---|
| 1 | Problem statement and solution approach | Slides 1 and 2; `docs/MTX-01` |
| 2 | Product architecture | Slide 3; `docs/MATRIX-Product-Reference.md` |
| 3 | Product features | Slides 2, 3; `docs/MTX-02` |
| 4 | Tech stack | Slide 3 right side |
| 5 | Test case used to demo | Slide 6 banner and the demo section |
| 6 | Deployment strategy | Slide 4; `docs/MTX-03`, `DEP-001` |
| 7 | Cost model | Slide 4; `docs/MTX-03`, `COM-001`, `LIC-001` |
| 8 | Support and maintenance | Slide 4; `docs/MTX-03`, `SUP-001` |
| 9 | Source code | GitHub `akaravind456-spec/Matrix-aiops`. Add the link on slide 9 |
| 10 | Product images | Slides 6 to 9 (add screenshots) |
| 11 | Demo video | Record the demo run once. Add the link on slide 9 |
| 12 | Security layers | Slide 3; `docs/MTX-04`, `SEC-001` |
| 13 | AI observability | Slide 3; `docs/MTX-04` |
| 14 | Future scope | Slide 5 |

## Open items before the presentation
1. **Agent stops without saying why.** The team saw this in the last demo. Ask me to add a visible reason (for example "stopped:
   step limit reached" or "stopped: model unavailable") to the work notes and the chat. I have not changed this yet.
2. **Admin versus normal user.** The product today has roles (engineer, lead) and a blocked agent identity. A full admin-privilege
   model is not built. Say only what is true, as in the answer above, or ask me to add it.
3. **"Resolves every L1 issue."** The opening idea is a hook. In answers, say "the repeated L1 issues it has a safe fix for",
   as in the Q&A, so leaders do not take it as a promise for every case.
4. **Screenshots and links.** Slides 6 to 9 have labelled frames. Replace them, and add the source code and demo video links on slide 9.
   Do not show a settings page, because it shows secrets.
5. **Rotate every key and password that was pasted into chat before presenting.**
