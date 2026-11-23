# MATRIX documentation

Start with the **Product Overview**, then read what fits your role.

## Product documents

| ID | Document | Read it to |
|---|---|---|
| PRD-001 | [Product Overview](PRD-001-Product-Overview.md) | Understand what MATRIX is, what it does and what it does not do |
| ARC-001 | [Architecture and Governance](ARC-001-Architecture-and-Governance.md) | See the components, data, controls and who approves what |
| AIG-001 | [Agent Behavior and Action Lifecycle](AIG-001-Agent-Behavior-and-Action-Lifecycle.md) | Know exactly what the agent may do and how it decides |
| DEP-001 | [Deployment Model](DEP-001-Deployment-Model.md) | Plan an installation: options, requirements, sizing, responsibilities |
| COM-001 | [Cost and Chargeback Model](COM-001-Cost-and-Chargeback-Model.md) | Know what MATRIX costs and how to charge teams for it |
| SEC-001 | [Threat Model](SEC-001-Threat-Model.md) | Review the risks, the controls and the open weaknesses |
| RSK-001 | [Kill Switch and Agent Incident Response](RSK-001-Kill-Switch-and-Agent-Incident-Response.md) | Stop MATRIX quickly and respond to something it did |
| SUP-001 | [Support and Troubleshooting](SUP-001-Support-and-Troubleshooting.md) | Fix common faults and ask for help well |
| LIC-001 | [Licensing and Pricing](LIC-001-Licensing-and-Pricing.md) | See the proposed plans, prices, soft limits and the usage meter |
| IPR-001 | [Code Protection, Support and Maintenance Plan](IPR-001-Code-Protection-and-Support-Plan.md) | Decide how to protect the code and how updates and support work |
| GUIDE-001 | [Step-by-Step Case Walkthroughs](GUIDE-001-Step-by-Step-Case-Walkthroughs.md) | Follow each case step by step with a screenshot for every step |
| REL-001 | [Go-to-Market Readiness Plan](REL-001-Go-To-Market-Readiness-Plan.md) | See what is done and what is left before selling: install, licence, protection, function, support |
| DEMO-001 | [Demo Test Cases, Screenshots and Video Script](DEMO-001-Demo-Test-Cases-Screenshots-and-Video-Script.md) | See the live test results, console screenshots and the demo recording script |

## Customer pack (four short documents)

Shorter, customer-shareable summaries of the documents above. Read these first when presenting to a customer or leader.

| ID | Document | Covers |
|---|---|---|
| MTX-01 | [Problem, Approach and Scalability](MTX-01-Problem-Approach-and-Scalability.md) | The problem, success measures, approach, adoption stages, scaling and limits |
| MTX-02 | [Product Features, Architecture and Tech Stack](MTX-02-Product-Features-Architecture-and-Tech-Stack.md) | Features, components, governance, model gateway, technology |
| MTX-03 | [Deployment, Cost and Support](MTX-03-Deployment-Cost-and-Support.md) | Install options, measured cost, value method, support tiers |
| MTX-04 | [Cybersecurity and AI Observability](MTX-04-Cybersecurity-and-AI-Observability.md) | Threats, stop ladder, what is recorded, evidence, NIST alignment |

## Working guides

| File | Use |
|---|---|
| [deployment-guide.md](deployment-guide.md) | Click-by-click steps to install MATRIX in a new AWS account |
| [env-template.md](env-template.md) | Every Lambda setting (names only, never values) |
| [tool-catalog.md](tool-catalog.md) | Every tool the chat can use and its safety rule |

## Reading paths

| You are | Read |
|---|---|
| New to the product | PRD-001, then AIG-001 |
| Installing it | DEP-001, `deployment-guide.md`, `env-template.md` |
| Approving the design or auditing | ARC-001, AIG-001, SEC-001, RSK-001 |
| Managing the budget | COM-001 |
| On call | RSK-001, SUP-001 |

## Status of these documents

All are **version 0.1 draft** from the code and from the behavior seen while building the system. Owners, approvers, response
targets and rates shown as `[to be named]` or `[to be decided]` need a decision. There is no evaluation report or customer
legal pack (licence, terms, privacy notice) yet: an evaluation needs real test results, and the legal documents need
review by your legal team.
