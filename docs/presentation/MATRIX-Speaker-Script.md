# MATRIX: Speaker Script (10 minutes talk + 5 minutes demo)

**Speakers:** Shafeeq (the hook, the money, why us, the ask) and Aravind (how it works, and the demo screen).
**Total:** 15 minutes. About 1,000 words to speak, which is 7 to 8 minutes at a calm pace, leaving about 2 minutes for slide changes, pauses and hand-overs.
`[click]` means move to the next slide.

**Golden rules:** short sentences. One idea per slide. Say "for example". Pause after every number.

## If the audience remembers only three things

1. MATRIX is an **AI engineer for the first line of support**. It works all day and night.
2. It is **safe**: it can only do a few simple fixes, and a person approves anything risky.
3. It **writes everything down** on the ticket, so nothing is hidden.

## Timing at a glance

| # | Section | Speaker | Time |
|---|---|---|---|
| 1 | Hook and opening | Shafeeq | 1:15 |
| 2 | What it costs | Shafeeq | 1:15 |
| 3 | How it works | Aravind | 1:30 |
| 4 | How we keep it safe | Aravind | 1:15 |
| 5 | What is under the hood | Aravind | 1:00 |
| 6 | Why MATRIX | Shafeeq | 1:15 |
| 7 | How we measure success | Shafeeq | 0:45 |
| 8 | The ask | Shafeeq | 0:30 |
| | Buffer for slides | | 1:15 |
| 9 | **Live demo** | Both | 5:00 |

---

## 1. Hook and opening (Shafeeq, 1 min 15 sec)

Good morning, everyone. We are Shafeeq and Aravind.

Let me start with a simple question. **If you could hire one more L1 engineer, who never sleeps, never takes a day off, and
writes down everything they do, would you hire them?**

`[click]` Most teams would say yes straight away. Problems do not wait for office hours, so to cover every hour of the week
you need about **five** people. And most of their day goes on the same first steps, again and again. Check the server. Look at
the problem. Find the instructions. Write the notes.

That is the engineer we built. **MATRIX** is an **AI engineer for the first line of support**. It works with your team, every
hour of the day. When an alarm goes off, it opens the ticket, looks at the problem, fixes it if the fix is safe, and passes it
to a person if it is not.

We are not here to cut your team. We want to give them their time back.

We would like you to judge us on three things: **faster fixes, fewer problems passed to senior engineers, and a full record of
everything the AI does.**

## 2. What it costs (Shafeeq, 1 min 15 sec)

Now, the money. We used market prices, and we will tell you when something is our assumption. `[click]`

- A support engineer costs about **$65,000 a year** all in. Five of them is about **$27,000 every month**.
- MATRIX, in our test week, cost **less than one dollar** to run, plus **five cents** for the AI.
- Now imagine MATRIX does just **30 percent** of the repeated work. That gives your team about **$8,000 of time back every month**.

Please note: the 30 percent is our assumption. **We measure the real number in a pilot.** And these are US prices; we will
redo this with yours.

The point is simple. People cost grows with headcount. MATRIX cost grows in cents.

Now Aravind will show how it works.

## 3. How it works (Aravind, 1 min 30 sec)

Thank you, Shafeeq. It works in five simple steps. `[click]`

**Step one: the alarm.** Something goes wrong on a server, and AWS raises an alarm. MATRIX hears it straight away.

**Step two: the ticket.** MATRIX opens a ticket in ServiceNow, names the server, and gives it to the AI team. If a ticket is
already open for that alarm, it does not make a second one.

**Step three: investigate.** MATRIX looks at the server. It can only *look* at this stage. It checks the CPU, the disk and the
services. It also reads your own instructions, your runbook. Every step is written on the ticket.

**Step four: fix.** MATRIX picks **one** fix from a short, safe list. And here is the important part. Our code checks the
choice. If the AI makes something up, the code says no, and the ticket goes to a person.

**Step five: check.** After the fix, MATRIX looks again. If the problem is gone, it closes the ticket. If not, it hands it to a
senior engineer and explains why.

And one more thing. When a person solves a hard ticket, MATRIX learns from it and writes a draft guide for next time.

## 4. How we keep it safe (Aravind, 1 min 15 sec)

People always ask: how much control does the AI get? We use three simple rules. `[click]`

**Rule one: only three fixes.** MATRIX can restart a service, clean old log files, or stop one runaway program. That is all.

**Rule two: a person approves anything risky.** MATRIX shows a card: what it will do, and on which server. A person clicks
Confirm. Small, safe fixes in a test environment can run on their own.

**Rule three: some things are impossible.** MATRIX can never delete a server, resize it, or change security settings. This is
not a promise from the AI. **AWS itself blocks it.**

`[click]` So if someone tells the AI "do it anyway", nothing happens. The limits are in the system, not in the AI's instructions.

## 5. What is under the hood (Aravind, 1 min)

Let me show you what it is built from. `[click]`

It is **one small program in your own AWS account**. There are no servers to look after.

It uses three things you already have: **ServiceNow** for tickets, **AWS** for the servers, and an **AI model** to do the
thinking. It talks to servers the safe, standard AWS way, so we do not open any new doors into your network.

It has **backup AI models**. If one stops working, the next one takes over, and nobody notices.

Everything it does is **recorded**: on the ticket, and in a log.

And if you ever want it to stop, you can stop it **in a few minutes**, with one switch. No tickets are lost.

Over to Shafeeq.

## 6. Why MATRIX (Shafeeq, 1 min 15 sec)

You may ask: we already have monitoring and scripts. Why do we need this? Monitoring *tells* you there is a problem. A script
*does what it is told*. **MATRIX looks, decides, acts safely, checks, and writes it down.** `[click]`

Five reasons.

**One: it fits what you have.** Your ServiceNow and your AWS. Nothing new to learn.

**Two: it is safe.** A short list of fixes, and a person approves risk.

**Three: it learns.** Every hard ticket makes it smarter, and a person approves what it learns.

**Four: it does more than fixes.** It can help with patching, moving servers and building new ones, always with approval.

**Five: you can see the cost.** The dashboard shows it in dollars.

## 7. How we measure success (Shafeeq, 45 sec)

We will measure six things: **how fast problems are fixed, how many MATRIX fixes alone, how many need a person, how many go to
senior engineers, whether you meet your service targets, and the cost per ticket.** `[click]` The dashboard shows all of this.
Nobody has to count by hand.

We want to be honest. We have **not** published results yet. What we have is one real example: from alarm to approved fix, in
about **three minutes**, with every step written down. A pilot gives us proper numbers.

We suggest three stages: first MATRIX only watches and suggests. Then people confirm its fixes. Then it handles simple, safe
work by itself.

## 8. The ask (Shafeeq, 30 sec)

Today, MATRIX works on Linux servers with ServiceNow. Next we will add easier sign-in, safer password storage and Windows.

So our ask is simple. **Agree a pilot. Agree the measures. Give us a few test servers to start.**

Now let us show you. Aravind will drive.

---

## 9. Live demo (both, 5 minutes)

**Roles.** Aravind clicks and explains. Shafeeq starts, explains why it matters, and closes.
**Keep these tabs open:** the Dashboard, the AWS alarm page, ServiceNow incidents, and the Knowledge page.

| Time | Who | What to show | What to say (simple) |
|---|---|---|---|
| 0:00 to 0:30 | Shafeeq | Dashboard | "This is the home screen. What is waiting, how MATRIX is doing, and what it costs." |
| 0:30 to 1:15 | Aravind | The alarm, then the ticket | "The alarm is ringing. Nobody made a ticket. Here it is, with the server and the AI team already filled in." |
| 1:15 to 2:00 | Aravind | The notes on the ticket | "MATRIX writes these as it works. It found one program using almost all the CPU." |
| 2:00 to 2:45 | Aravind | The approval card, then Confirm | "It suggests one fix: stop that program. A person checks the card and clicks Confirm." |
| 2:45 to 3:30 | Aravind | The result on the ticket | "It looks again and writes the result. If fixed, it closes the ticket. If not, it passes it on with the reason." |
| 3:30 to 4:15 | Shafeeq | Knowledge page: a draft guide (View draft) | "This is how it learns. It wrote a draft guide from a solved ticket. A person approves it first." Do not click Approve unless the checks are green |
| 4:15 to 5:00 | Shafeeq | Cost card | "Cost in dollars. From alarm to fix in minutes, every step written down, and a person in control. That is MATRIX." |

### Before you go on (15 minutes before)

1. Put the newest code in AWS. In Lambda, run the test `{"matrix_task": "alarm_sweep"}`: it should show no error.
2. Check the two alarm rules are switched on, and no old alarm action is attached.
3. **Close any open ticket for the demo alarm.** An open ticket stops a new one.
4. Make sure the alarm is back to OK. About **3 minutes before you start**, start the CPU load, so the alarm is ringing when you begin.
5. Check the AI models are healthy on the Observability page.
6. Do not open any settings page. They show secrets.
7. **Change any password or key that was ever pasted into a chat.**

### If something goes wrong

| Problem | What to do |
|---|---|
| No ticket appears | Run the sweep test in Lambda, or open the ticket from your practice run and say "this is from our last run" |
| It is slow | Keep explaining the three safety rules and refresh every 20 seconds |
| An AI error appears | Say "the next AI takes over automatically" and refresh |
| Nothing works | Show saved screenshots of a finished ticket and keep them in a folder called Backup |

---

## Easy answers to likely questions

| Question | Simple answer |
|---|---|
| Are you replacing five engineers? | No. MATRIX does the repeated first checks. People keep approvals and the hard problems. We work out the saving together, using your numbers. |
| Where do the prices come from? | Support engineer pay is from 2026 salary sites, about $50,000 base. The extra 30 percent for benefits is our assumption. The 30 percent of work is also our assumption, and the pilot will measure it. |
| What if the AI is wrong? | It can only pick from three safe fixes. Our code checks its choice. A person approves anything risky. |
| Does our data leave AWS? | The text of a ticket goes to the AI company you choose. Pick one whose terms you accept. |
| Is it ready for production? | It is a pilot on Linux test servers. We have a list of what is still to do. |
| How do we stop it? | One switch, a few minutes. Nothing is lost. |
| Why not just scripts? | A script does only what you wrote. MATRIX decides what to check, writes the notes, and learns. |

## Sources for the prices (checked 18 November 2026)

- Support engineer pay: [Salary.com](https://www.salary.com/research/salary/position/it-help-desk-analyst-salary) and [PayScale](https://www.payscale.com/research/US/Job=Help_Desk_Analyst/Salary/7984c68f/Late-Career-Help-Desk-Desktop-Support-Tier-1). We used $50,000 base and added 30 percent (our assumption) for tax and benefits.
- Cost per ticket benchmark, if asked: [eesel.ai summary](https://www.eesel.ai/blog/cost-per-ticket-benchmarks): about $15 to $22, from old data (2016 at best). Not used on the slides.
- Our own pilot-week cost: from the MATRIX dashboard.
