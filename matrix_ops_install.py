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
}
SNOW_NAMES = ["snow_create_incident", "snow_create_change", "snow_create_sr_task", "snow_add_work_note",
              "snow_get_ticket", "snow_escalate"]


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

    g["CHAT_SYSTEM"] = g["CHAT_SYSTEM"] + (
        " To open an incident use snow_create_incident, and ask the engineer for the CI, a one-line summary and the error log or "
        "description first; never guess them. Use snow_create_change for changes and snow_create_sr_task for routine requests. "
        "Write a work note with snow_add_work_note after each investigation step and each action. "
        "Patching and migration order: scan or assess first, raise a change with plans and a window, wait for a human to approve it "
        "in ServiceNow (you cannot approve your own change), then run patch_install or the migration steps in order: "
        "migration_replicate, migration_image_status, migration_launch, migration_validate, migration_cutover. "
        "If a tool says needs_approval, change not approved, or ticket_invalid, tell the engineer exactly that and do not retry.")
