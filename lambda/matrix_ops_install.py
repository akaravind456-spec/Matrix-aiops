"""
matrix_ops_install.py - plugs matrix_snow_tools and matrix_ops_skills into console_api.

Usage in the entry file, right after matrix_sre_install.install(g) and before learning.install(g):

    import matrix_ops_install
    matrix_ops_install.install(g)

How it fits your console
  * Ticket tools and read-only checks go into READ (run immediately).
  * Anything that changes a server goes into WRITE: it shows the Confirm button, and your existing ticket gate in
    matrix_sre_install requires a real, valid number first. The engineer's Confirm sets approved=True.
  * Servers are identified by EC2 Name tag (host), like the rest of your console.
  * Skipped on purpose because the console already has them: resolve_incident (and raise_incident exists too;
    snow_create_incident is the stricter version that asks for CI, summary and error log first).
"""
import json
import matrix_snow_tools as sn
import matrix_ops_skills as ops

_S = {"type": "string"}
_NUM = {"type": "string", "description": "Change number (CHG...) that is approved and scheduled, e.g. CHG0030012"}
_HOST = {"type": "string", "description": "EC2 Name tag of the server, e.g. matrix-linux-01"}
_HOSTS = {"type": "array", "items": _S, "description": "EC2 Name tags of the servers, e.g. [\"matrix-linux-01\"]"}

# name -> (description, properties, required)
OPS_READ = {
    "patch_scan": ("Read-only scan for missing patches on one or more servers.", {"hosts": _HOSTS, "number": _S}, ["hosts"]),
    "patch_status": ("Check progress of a running patch job and validate the servers when it finishes.",
                     {"command_id": _S, "hosts": _HOSTS, "number": _S}, ["command_id", "hosts"]),
    "migration_assess": ("Read-only inventory of a server before migrating it (type, volumes, network, IAM, tags).",
                         {"host": _HOST, "number": _S}, ["host"]),
    "migration_image_status": ("Check whether a migration image is available.", {"image_id": _S, "region": _S}, ["image_id"]),
    "migration_validate": ("Check the migrated server's status checks and SSM agent.",
                           {"host": _HOST, "instance_id": _S, "region": _S, "number": _S}, []),
    "deployment_plan": ("Read-only preview of a new server: size, disk, network, tags. Creates nothing.",
                        {"name": _S, "instance_type": _S, "vcpu": {"type": "integer"}, "ram_gb": {"type": "number"},
                         "disk_gb": {"type": "integer"}, "number": _S}, ["name"]),
    "decommission_assess": ("Read-only check before retiring a server: Elastic IPs, load balancer membership, recent CPU use, existing final backups.",
                            {"host": _HOST, "number": _S}, ["host"]),
}
OPS_WRITE = {
    "patch_install": ("Take rollback AMIs then install patches. Needs an approved, scheduled change and engineer Confirm.",
                      {"hosts": _HOSTS, "number": _NUM, "reboot_option": {"type": "string", "enum": ["RebootIfNeeded", "NoReboot"]}},
                      ["hosts", "number"],
                      lambda a: "Patch %s (rollback AMIs first, change %s)" % (", ".join(a.get("hosts") or []), a.get("number"))),
    "migration_replicate": ("Create an AMI of the source server for migration. Needs an approved change and Confirm.",
                            {"host": _HOST, "number": _NUM, "target_region": _S}, ["host", "number"],
                            lambda a: "Create migration image of %s" % a.get("host")),
    "migration_copy_image": ("Copy a migration image to another region. Needs an approved change and Confirm.",
                             {"image_id": _S, "target_region": _S, "number": _NUM}, ["image_id", "target_region", "number"],
                             lambda a: "Copy image %s to %s" % (a.get("image_id"), a.get("target_region"))),
    "migration_launch": ("Launch the target server from the migration image. Needs an approved change and Confirm.",
                         {"image_id": _S, "subnet_id": _S, "instance_type": _S,
                          "security_group_ids": {"type": "array", "items": _S}, "number": _NUM,
                          "iam_profile_name": _S, "name_tag": _S, "region": _S},
                         ["image_id", "subnet_id", "instance_type", "security_group_ids", "number"],
                         lambda a: "Launch %s (%s) from %s" % (a.get("name_tag") or "target", a.get("instance_type"), a.get("image_id"))),
    "migration_cutover": ("Stop the source and move the Elastic IP to the validated target. Needs approved change and Confirm.",
                          {"host": _HOST, "target_instance_id": _S, "number": _NUM, "eip_allocation_id": _S},
                          ["host", "target_instance_id", "number"],
                          lambda a: "CUTOVER: stop %s, traffic to %s" % (a.get("host"), a.get("target_instance_id"))),
    "migration_rollback": ("Restart the source server and stop the target. Needs an approved change and Confirm.",
                           {"host": _HOST, "target_instance_id": _S, "number": _NUM, "eip_allocation_id": _S},
                           ["host", "target_instance_id", "number"],
                           lambda a: "ROLLBACK: start %s, stop %s" % (a.get("host"), a.get("target_instance_id"))),
    "deployment_apply": ("Create a new server (SSM only, tagged matrix-managed). Needs an approved change and Confirm.",
                         {"name": _S, "instance_type": _S, "vcpu": {"type": "integer"}, "ram_gb": {"type": "number"},
                          "disk_gb": {"type": "integer"}, "number": _NUM}, ["name", "number"],
                         lambda a: "DEPLOY new server %s (%s, %s GB disk)" % (
                             a.get("name"),
                             ops.size_args(a.get("instance_type"), a.get("vcpu"), a.get("ram_gb"))[0] or "%s vCPU / %s GB RAM" % (a.get("vcpu"), a.get("ram_gb")),
                             a.get("disk_gb") or 8)),
    "decommission_snapshot": ("Create the final backup image of a server before retiring it. Needs an approved change and Confirm.",
                              {"host": _HOST, "number": _NUM}, ["host", "number"],
                              lambda a: "Final backup image of %s" % a.get("host")),
    "decommission_stop": ("Stop a server being retired. Refuses unless a final backup image is available. Needs an approved change and Confirm.",
                          {"host": _HOST, "number": _NUM}, ["host", "number"],
                          lambda a: "DECOMMISSION: stop %s (kept stopped for the hold period)" % a.get("host")),
    "decommission_terminate": ("Terminate a stopped, backed-up server after the hold period. Needs the decommission-approved=true tag set by a human, an approved change and Confirm.",
                               {"host": _HOST, "number": _NUM}, ["host", "number"],
                               lambda a: "TERMINATE %s permanently (backup image is kept)" % a.get("host")),
}
SNOW_NAMES = ["snow_create_incident", "snow_create_change", "snow_create_sr_task", "snow_add_work_note",
              "snow_get_ticket", "snow_escalate",
              "snow_search_tickets", "snow_check_change_approval", "snow_get_cmdb_ci", "snow_search_kb", "snow_get_sla"]
# ServiceNow tools that change records: they get the engineer's Confirm button like server changes do
SNOW_WRITE = {
    "snow_update_ticket": lambda a: "Update %s in ServiceNow: %s" % (a.get("number"), ", ".join(sorted((a.get("fields") or {}).keys() | {k for k in ("assignment_group", "assigned_to") if a.get(k)})) or "fields"),
    "snow_close_change": lambda a: "Close change %s as %s" % (a.get("number"), a.get("close_code")),
    "snow_create_problem": lambda a: "Open a problem: %s" % str(a.get("short_description"))[:100],
    "snow_link_ticket": lambda a: "Link %s to %s" % (a.get("number"), a.get("to_number")),
    "snow_attach_evidence": lambda a: "Attach %s to %s" % (a.get("file_name") or "evidence.txt", a.get("number")),
    "snow_update_cmdb_ci": lambda a: "Update CI %s: %s" % (a.get("name"), ", ".join(k for k in ("install_status", "operational_status") if a.get(k)) or "comments"),
}


def install(g):
    READ, WRITE, TOOLS = g["READ"], g["WRITE"], g["TOOLS"]
    have = {t["function"]["name"] for t in TOOLS}

    def inst(host):
        i = g["find_instance"](host)
        if not i:
            raise RuntimeError("No EC2 instance with Name tag " + str(host))
        return i["id"]

    def ids(a):
        hs = a.get("hosts") or ([a["host"]] if a.get("host") else [])
        if not hs:
            raise RuntimeError("host is required")
        return [inst(h) for h in hs]

    def text(r):
        if not isinstance(r, dict):
            return str(r)[:2500]
        if r.get("needs_info"):
            return "Need more information before this can run: %s. %s" % (", ".join(r["needs_info"]), r.get("ask", ""))
        if r.get("status") == "needs_approval":
            return "Failed: needs_approval - the engineer must Confirm first"
        if r.get("ok") is False:
            return "Failed: " + str(r.get("error") or r.get("message") or "unknown error")
        return json.dumps(r, default=str)[:2500]

    # ---- per-tool translation from console arguments to skill arguments
    num = lambda a: a.get("number")
    MAP = {
        "patch_scan": lambda a: dict(instance_ids=ids(a), ticket=num(a)),
        "patch_status": lambda a: dict(command_id=a["command_id"], instance_ids=ids(a), ticket=num(a)),
        "patch_install": lambda a: dict(instance_ids=ids(a), change_number=num(a), approved=True,
                                        reboot_option=a.get("reboot_option", "RebootIfNeeded")),
        "migration_assess": lambda a: dict(instance_id=inst(a["host"]), ticket=num(a)),
        "migration_image_status": lambda a: dict(image_id=a["image_id"], region=a.get("region")),
        "migration_validate": lambda a: dict(instance_id=a.get("instance_id") or inst(a["host"]), ticket=num(a),
                                             region=a.get("region")),
        "migration_replicate": lambda a: dict(instance_id=inst(a["host"]), change_number=num(a), approved=True,
                                              target_region=a.get("target_region")),
        "migration_copy_image": lambda a: dict(image_id=a["image_id"], target_region=a["target_region"],
                                               change_number=num(a), approved=True),
        "migration_launch": lambda a: dict(image_id=a["image_id"], subnet_id=a["subnet_id"],
                                           instance_type=a["instance_type"], security_group_ids=a["security_group_ids"],
                                           change_number=num(a), approved=True, iam_profile_name=a.get("iam_profile_name"),
                                           name_tag=a.get("name_tag"), region=a.get("region")),
        "migration_cutover": lambda a: dict(source_id=inst(a["host"]), target_id=a["target_instance_id"],
                                            change_number=num(a), approved=True, eip_allocation_id=a.get("eip_allocation_id")),
        "migration_rollback": lambda a: dict(source_id=inst(a["host"]), target_id=a["target_instance_id"],
                                             change_number=num(a), approved=True, eip_allocation_id=a.get("eip_allocation_id")),
        "deployment_plan": lambda a: dict(name=a["name"], instance_type=a.get("instance_type"), vcpu=a.get("vcpu"),
                                          ram_gb=a.get("ram_gb"), disk_gb=a.get("disk_gb") or 8, ticket=num(a)),
        "deployment_apply": lambda a: dict(name=a["name"], instance_type=a.get("instance_type"), vcpu=a.get("vcpu"),
                                           ram_gb=a.get("ram_gb"), disk_gb=a.get("disk_gb") or 8, change_number=num(a),
                                           approved=True, requested_by=a.get("_user") or "MATRIX"),
        "decommission_assess": lambda a: dict(instance_id=inst(a["host"]), ticket=num(a)),
        "decommission_snapshot": lambda a: dict(instance_id=inst(a["host"]), change_number=num(a), approved=True),
        "decommission_stop": lambda a: dict(instance_id=inst(a["host"]), change_number=num(a), approved=True),
        "decommission_terminate": lambda a: dict(instance_id=inst(a["host"]), change_number=num(a), approved=True),
    }

    def add_tool(name, desc, props, req):
        if name in have:
            return False
        TOOLS.append({"type": "function", "function": {
            "name": name, "description": desc,
            "parameters": {"type": "object", "required": req, "properties": props}}})
        return True

    def make_ops(name):
        def run(a, u):
            try:
                return text(getattr(ops, name)(**MAP[name](a)))   # looked up at call time
            except Exception as e:
                return "Failed: " + str(e)[:300]
        return run

    def make_snow(name):
        def run(a, u):
            allowed = {k: v for k, v in a.items() if v not in (None, "")}
            return text(getattr(sn, sn.HANDLERS[name].__name__)(**allowed))
        return run

    for name, (desc, props, req) in OPS_READ.items():
        if add_tool(name, desc, props, req):
            READ[name] = make_ops(name)
    for name, (desc, props, req, summary) in OPS_WRITE.items():
        if add_tool(name, desc, props, req):
            WRITE[name] = (summary, make_ops(name))
    for spec in sn.TOOL_SPECS:
        if spec["name"] in SNOW_NAMES and add_tool(spec["name"], spec["description"],
                                                    spec["input_schema"]["properties"],
                                                    spec["input_schema"].get("required", [])):
            READ[spec["name"]] = make_snow(spec["name"])
        elif spec["name"] in SNOW_WRITE and add_tool(spec["name"], spec["description"],
                                                      spec["input_schema"]["properties"],
                                                      sorted(set(spec["input_schema"].get("required", [])) | {"number"})):
            WRITE[spec["name"]] = (SNOW_WRITE[spec["name"]], make_snow(spec["name"]))

    g["CHAT_SYSTEM"] = g["CHAT_SYSTEM"] + (
        " To open an incident use snow_create_incident, and ask the engineer for the CI, a one-line summary and the error log or "
        "description first; never guess them. Use snow_create_change for changes and snow_create_sr_task for routine requests. "
        "Write a work note with snow_add_work_note after each investigation step and each action. "
        "Patching and migration order: scan or assess first, raise a change with plans and a window, wait for a human to approve it "
        "in ServiceNow (you cannot approve your own change), then run patch_install or the migration steps in order: "
        "migration_replicate, migration_image_status, migration_launch, migration_validate, migration_cutover. "
        "New server order: deployment_plan (show the engineer the plan), raise a change, wait for approval, deployment_apply, then migration_validate and a work note. "
        "Decommission order: decommission_assess (report every warning), raise a change, wait for approval, decommission_snapshot, "
        "wait until migration_image_status shows available, decommission_stop, then after the hold period and a human adding the tag decommission-approved=true, decommission_terminate, "
        "then snow_update_cmdb_ci with install_status=retired and snow_close_change. Never skip a step and never terminate in the same session as the stop. "
        "Before planned work call snow_check_change_approval; if it says ready_to_execute is false, tell the engineer why and stop. "
        "If a tool says needs_approval, change not approved, or ticket_invalid, tell the engineer exactly that and do not retry.")
