# MATRIX tool catalog

READ = runs straight away. WRITE = the engineer must press Confirm, and the global ticket gate
(`matrix_sre_install.py`) first checks that the `number` is a real, valid ticket in ServiceNow.
Planned-work tools additionally require a **CHG** that ServiceNow says is *approved* and in *Scheduled/Implement* state
(`matrix_ops_skills._change`). The agent can never approve its own change.

The autonomous L1 agent (`autonomy.py`) can only use its fixed fix list (restart_service, clear_old_logs, kill_process).
Every tool below is available in **chat only**.

## Patching
| Tool | Type | What it does |
|---|---|---|
| `patch_scan` | READ | Lists available security updates (`MATRIX_PATCH_SCAN`) |
| `patch_status` | READ | Progress of a scan or install; status checks when done |
| `patch_install` | WRITE | Rollback AMI of each server first, then `AWS-RunPatchBaseline` Install |

## Migration
| Tool | Type | What it does |
|---|---|---|
| `migration_assess` | READ | Type, AZ, volumes, network, IAM profile, EIPs, tags |
| `migration_replicate` | WRITE | AMI of the source (no reboot) |
| `migration_image_status` | READ | Is the image available (any region) |
| `migration_copy_image` | WRITE | Copy the image to another region |
| `migration_launch` | WRITE | New server from the image, tagged `matrix-managed` |
| `migration_validate` | READ | Status checks and SSM agent (also used after a new deployment) |
| `migration_cutover` | WRITE | Needs a healthy target; stops the source, moves the Elastic IP |
| `migration_rollback` | WRITE | Starts the source, gives back the EIP, stops the target |

## Deployment
| Tool | Type | What it does |
|---|---|---|
| `deployment_plan` | READ | Shows size, disk, network and tags. Creates nothing |
| `deployment_apply` | WRITE | Creates the server (SSM only, IMDSv2, encrypted disk) via `matrix_guardrails.deploy_ec2` |

## Decommission (in this order)
| Step | Tool | Type | Safety rule |
|---|---|---|---|
| 1 | `decommission_assess` | READ | Warns about Elastic IPs, load balancer targets, recent CPU use |
| 2 | `decommission_snapshot` | WRITE | Final backup AMI of all volumes |
| 3 | `decommission_stop` | WRITE | Refuses unless the backup image is *available* |
| 4 | `decommission_terminate` | WRITE | Only if ALL are true: stopped for `DECOM_HOLD_DAYS` (default 7), backup available, a human added the tag `decommission-approved=true`, approved CHG, and the optional `matrix-decommission-<env>` role is enabled |
| 5 | `snow_update_cmdb_ci` | WRITE | `install_status=retired` |
| 6 | `snow_close_change` | WRITE | Close the change with a close code |

The normal executor role keeps its hard deny on `ec2:TerminateInstances`. Terminate is only possible through the separate
role, which is off by default (`EnableDecommissionRole=false` in `infra/matrix-iam-executor.yaml`).
Resize (`ModifyInstanceAttribute`) is also hard-denied and was deliberately not added.

## ServiceNow
| Tool | Type | What it does |
|---|---|---|
| `snow_create_incident` | READ* | Creates an incident (asks for CI, summary, error log first) |
| `snow_create_change` | READ* | Creates a change with implementation, backout and test plans |
| `snow_create_sr_task` | READ* | REQ, RITM and SCTASK for a routine request |
| `snow_add_work_note` | READ* | Internal work note (secrets masked) |
| `snow_get_ticket` | READ | State, approval, assignment, window |
| `snow_escalate` | READ* | Reassign to L2/L3 with a reason |
| `snow_search_tickets` | READ | Search by summary words and/or CI |
| `snow_check_change_approval` | READ | Approved? Right state? Ready to execute? |
| `snow_get_cmdb_ci` | READ | CI class, IP, OS, status, owner |
| `snow_search_kb` | READ | Published knowledge articles |
| `snow_get_sla` | READ | SLA stage, time left, breached |
| `snow_update_ticket` | WRITE | Priority, urgency, impact, category, risk, summary, group, assignee (no state changes) |
| `snow_close_change` | WRITE | Close with `successful`, `successful_with_issues` or `unsuccessful` |
| `snow_create_problem` | WRITE | Problem record, links an incident |
| `snow_link_ticket` | WRITE | Incident to CHG (`rfc`) or PRB (`problem_id`) |
| `snow_attach_evidence` | WRITE | Attach output or logs as a text file (secrets masked) |
| `snow_update_cmdb_ci` | WRITE | Install or operational status |

\* Registered as READ by the original `matrix_ops_install.py`, so no Confirm button. They write to ServiceNow only.
The agent user's ServiceNow roles are the real limit; keep that account's ACLs tight.

## Known limits
- Cross-region migration needs the executor role and instance profile to exist in the target region, and the role's
  resources are scoped to the stack's own region. Same-region and cross-AZ moves work as is.
- `snow_close_change` only works if ServiceNow's change state model allows the move from the current state.
- The ticket gate only validates INC and CHG numbers, so WRITE tools cannot be filed under REQ/RITM/SCTASK numbers.
- `find_instance` looks up servers by Name tag and returns the first match. A just-terminated server with the same name can still
  show for about an hour.
