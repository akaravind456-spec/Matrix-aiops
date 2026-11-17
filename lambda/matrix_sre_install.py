"""
matrix_sre_install.py - plugs the new SRE tools and the ticket gate into console_api.

Usage in the entry file (the one that has `def handler`), before learning.install(g):

    import matrix_sre_install
    matrix_sre_install.install(g)

What it does
  1. Registers the new tools into console_api's TOOLS / READ / WRITE, so they use the same Confirm flow.
  2. Adds a ticket gate to precheck(): every WRITE tool must carry a real, valid incident/change number
     that exists in ServiceNow. A made-up number is refused BEFORE anything is queued for Confirm.
  3. Maps host (EC2 Name tag) to instance id, because the console identifies servers by Name tag.
"""
import json, os

SKIP = {"kb_search", "kb_read", "create_incident", "resolve_incident", "service_action", "ticket_timeline"}  # console already has these
READ_NEW = ["system_overview", "memory_diagnostics", "port_check", "cert_check", "network_check", "large_files", "log_tail",
            "backup_status", "metric_trend", "alarm_history", "recent_changes", "logs_insights", "target_health",
            "security_group_review", "unused_resources", "cost_report"]
WRITE_NEW = {  # tool -> summary for the Confirm button
    "run_command": lambda a: "Run on %s: %s" % (a.get("host"), str(a.get("command"))[:150]),
    "log_cleanup": lambda a: "Delete rotated logs older than %s days on %s" % (a.get("days", 14), a.get("host")),
    "snapshot_create": lambda a: "Snapshot all volumes of %s before the change" % a.get("host"),
}
NEEDS_HOST = {"system_overview", "memory_diagnostics", "port_check", "cert_check", "network_check", "large_files", "log_tail",
              "backup_status", "run_command", "log_cleanup", "snapshot_create", "metric_trend", "alarm_history",
              "recent_changes", "security_group_review"}


def install(g):
    # the guardrail module reads ServiceNow settings under its own names
    os.environ.setdefault("SNOW_URL", os.environ.get("SN_BASE", ""))
    os.environ.setdefault("SNOW_USER", os.environ.get("SN_USER", ""))
    os.environ.setdefault("SNOW_PASS", os.environ.get("SN_PASS", ""))
    import matrix_guardrails as gr
    import matrix_sre_tools as st

    READ, WRITE, TOOLS = g["READ"], g["WRITE"], g["TOOLS"]
    have = {t["function"]["name"] for t in TOOLS}

    def with_instance(a):
        a = dict(a)
        if a.get("host") and not a.get("instance_id"):
            inst = g["find_instance"](a["host"])
            if not inst:
                raise RuntimeError("No EC2 instance with Name tag " + str(a["host"]))
            a["instance_id"] = inst["id"]
        return a

    def text(r):
        if isinstance(r, dict):
            if r.get("status") in ("refused", "blocked", "error", "needs_approval"):
                return "Failed: " + str(r.get("message") or r.get("error") or r.get("status"))
            if "output" in r and len(r) <= 4:
                return str(r.get("output") or r.get("error") or "Done.")[:2500]
        return json.dumps(r, default=str)[:2500]

    def user_of(u):  # console user dict -> guardrail user
        return {"name": u.get("name") or u.get("u"), "role": u.get("role", "L2")}

    def make_read(name):
        fn = st.HANDLERS[name]
        def run(a, u):
            a = with_instance(a) if name in NEEDS_HOST else dict(a)
            a["ticket"] = a.get("number") or a.get("ticket")
            a["allow_no_ticket"] = True        # read-only: a ticket is optional, a given one is still validated
            return text(fn(a, user_of(u)))
        return run

    def make_write(name):
        fn = st.HANDLERS[name]
        def run(a, u):
            a = with_instance(a)
            a["ticket"] = a.get("number") or a.get("ticket")
            a["approved"] = True               # the engineer pressed Confirm in the console
            return text(fn(a, user_of(u)))
        return run

    schema = {t["name"]: t for t in st.TOOLS}
    for name, t in schema.items():
        if name in SKIP or name in have:
            continue
        if name not in READ_NEW and name not in WRITE_NEW:
            continue
        props = dict(t["parameters"]["properties"]); req = list(t["parameters"].get("required", []))
        if "instance_id" in props:                       # console identifies servers by Name tag
            props.pop("instance_id"); props.pop("name", None)
            props["host"] = "EC2 Name tag of the server, e.g. matrix-linux-01"
            req = [r for r in req if r not in ("instance_id", "name")] + ["host"]
        if "ticket" in props:
            props.pop("ticket"); props["number"] = "Incident or change number, e.g. INC0011091"
            req = [r for r in req if r != "ticket"]
            if name in WRITE_NEW: req.append("number")
        if name in WRITE_NEW:
            t = dict(t, description=t["description"] + " Needs engineer confirmation and a valid incident/change number.")
        TOOLS.append({"type": "function", "function": {
            "name": name, "description": t["description"],
            "parameters": {"type": "object", "required": sorted(set(req)),
                           "properties": {k: (v if isinstance(v, dict) else {"type": "string", "description": v}) for k, v in props.items()}}}})
        if name in WRITE_NEW:
            WRITE[name] = (WRITE_NEW[name], make_write(name))
        else:
            READ[name] = make_read(name)

    # ---- ticket gate: every change must carry a valid ticket, checked in ServiceNow, before it is queued ----
    orig_precheck = g["precheck"]
    GATE_EXEMPT = {"raise_incident", "assign_to_me", "approve_remediation", "reject_remediation", "resolve_incident"}  # these act on an incident by number already

    def precheck(name, a):
        why = orig_precheck(name, a)
        if why or name not in g["WRITE"]:
            return why
        number = str(a.get("number", "") or "").strip()
        if name in GATE_EXEMPT:
            if name != "raise_incident" and not number:
                return "incident_number_required"
            return ""
        if not number:
            return "ticket_required: give an incident or change number"
        try:
            ok, reason, rec = gr.validate_ticket(number)
        except Exception as e:  # ServiceNow unreachable or credentials rejected: fail closed with a clear reason
            return "servicenow_unavailable: cannot verify the ticket right now (%s)" % str(e)[:80]
        if not ok:
            return "ticket_invalid: " + reason[:120]
        return ""
    g["precheck"] = precheck

    # a_chat's system prompt gets one extra rule
    g["CHAT_SYSTEM"] = g["CHAT_SYSTEM"] + (
        " An engineer's direct request to start, stop or restart an allowed service does not need a runbook: call the tool and let the engineer Confirm. "
        "Do not refuse or escalate just because a knowledge-base search failed; say the search failed and carry on with the tools you have. "
        "If a tool fails twice with the same error, stop retrying and report that error to the engineer.")
    g["CHAT_SYSTEM"] = g["CHAT_SYSTEM"] + (" Every change needs a real incident or change number from the engineer. Never invent or guess one; if you were not given one, ask for it. "
                                           "If a tool says refused, ticket_required or ticket_invalid, tell the engineer exactly that and do not retry with a different number.")
