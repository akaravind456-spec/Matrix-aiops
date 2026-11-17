"""
matrix_sre_tools.py - new SRE tools for the MATRIX agent.

Add TOOLS to the list you already send to the LLM, and route calls through call_tool().
Existing tools (ec2_power, patch_install, run_playbook, terraform_apply, deploy_server, migrate_*, data_sync)
must be wrapped with gated() so they cannot run on a made-up CHG/INC number.
"""
import json, time, datetime, functools
import boto3
import matrix_guardrails as g
from matrix_projects_cost import cost_page_data

# ---------------------------------------------------------------- gate for EVERY mutating tool
def gated(fn, ticket_required_in_dev=True):
    """Wrap an existing tool: validates the ticket in ServiceNow before the tool runs."""
    @functools.wraps(fn)
    def wrapper(args, user):
        if g.ENV != "dev" or ticket_required_in_dev:
            ok, why, rec = g.validate_ticket(args.get("ticket"))
            if not ok:
                return {"status": "refused", "message": f"I can't proceed: {why}."}
            args["_rec"] = rec
        return fn(args, user)
    return wrapper
# Example: TOOL_HANDLERS["ec2_power"] = gated(existing_ec2_power)

# ---------------------------------------------------------------- helpers
def _run(args, user, **kw):
    return g.execute({"ticket": args.get("ticket"), "instance_id": args["instance_id"],
                      "requested_by": user["name"], "role": user["role"],
                      "approved": args.get("approved", False),
                      "allow_no_ticket": args.get("allow_no_ticket", False), **kw})

def _cw(): return g._session().client("cloudwatch")

def _resolve(args):
    """Accepts instance_id or Name tag; returns instance id."""
    if args.get("instance_id"): return args["instance_id"]
    r = g._session().client("ec2").describe_instances(Filters=[{"Name": "tag:Name", "Values": [args["name"]]}])
    inst = [i for x in r["Reservations"] for i in x["Instances"]]
    if len(inst) != 1: raise ValueError(f"{len(inst)} instances match Name={args['name']}")
    return inst[0]["InstanceId"]

# ---------------------------------------------------------------- tools: on-host (via SSM playbooks)
def system_overview(a, u):  return _run(a, u, document="MATRIX_OVERVIEW")
def memory_diagnostics(a, u): return _run(a, u, document="MATRIX_MEM_DIAGNOSTICS")
def port_check(a, u):       return _run(a, u, document="MATRIX_PORT_CHECK")
def cert_check(a, u):       return _run(a, u, document="MATRIX_CERT_EXPIRY_CHECK", doc_params={"Host": a.get("host", "localhost"), "Port": a.get("port", 443)})
def network_check(a, u):    return _run(a, u, document="MATRIX_NET_CHECK", doc_params={"Host": a["host"], "Port": a.get("port", 443)})
def large_files(a, u):      return _run(a, u, document="MATRIX_LARGE_FILES", doc_params={"Path": a.get("path", "/var")})
def log_tail(a, u):         return _run(a, u, document="MATRIX_LOG_TAIL", doc_params={"LogFile": a["log_file"], "Lines": a.get("lines", 100)})
def backup_status(a, u):    return _run(a, u, document="MATRIX_BACKUP_STATUS")
def log_cleanup(a, u):      return _run(a, u, document="MATRIX_LOG_CLEANUP", doc_params={"Days": a.get("days", 14)})  # needs approval
def service_action(a, u):   return _run(a, u, service=a["service"], action=a["action"])                              # start/stop/restart need approval
def run_command(a, u):      return _run(a, u, command=a["command"])                                                    # classified by guardrails

# ---------------------------------------------------------------- tools: AWS side
def metric_trend(a, u):
    """CPU / network / disk trend for the last N hours (CloudWatch). Memory/disk need the CW agent metrics."""
    iid = _resolve(a); hrs = int(a.get("hours", 6))
    metric = {"cpu": ("AWS/EC2", "CPUUtilization"), "network_in": ("AWS/EC2", "NetworkIn"),
              "network_out": ("AWS/EC2", "NetworkOut"), "status_failed": ("AWS/EC2", "StatusCheckFailed"),
              "mem": ("CWAgent", "mem_used_percent"), "disk": ("CWAgent", "disk_used_percent")}[a.get("metric", "cpu")]
    now = datetime.datetime.utcnow()
    r = _cw().get_metric_statistics(Namespace=metric[0], MetricName=metric[1],
        Dimensions=[{"Name": "InstanceId", "Value": iid}], StartTime=now - datetime.timedelta(hours=hrs), EndTime=now,
        Period=300 if hrs <= 12 else 3600, Statistics=["Average", "Maximum"])
    pts = sorted(r["Datapoints"], key=lambda p: p["Timestamp"])
    if not pts: return {"status": "ok", "message": "No datapoints (metric not published for this instance)."}
    return {"status": "ok", "instance_id": iid, "metric": a.get("metric", "cpu"), "hours": hrs,
            "avg": round(sum(p["Average"] for p in pts) / len(pts), 2), "max": round(max(p["Maximum"] for p in pts), 2),
            "last": round(pts[-1]["Average"], 2), "points": [(p["Timestamp"].strftime("%H:%M"), round(p["Average"], 1)) for p in pts][-24:]}

def alarm_history(a, u):
    iid = _resolve(a)
    cw = _cw(); out = []
    for al in cw.describe_alarms(AlarmTypes=["MetricAlarm"])["MetricAlarms"]:
        if any(d["Value"] == iid for d in al.get("Dimensions", [])):
            for h in cw.describe_alarm_history(AlarmName=al["AlarmName"], HistoryItemType="StateUpdate", MaxRecords=5)["AlarmHistoryItems"]:
                out.append({"alarm": al["AlarmName"], "when": h["Timestamp"].isoformat(), "what": h["HistorySummary"]})
    return {"status": "ok", "history": sorted(out, key=lambda x: x["when"], reverse=True)[:15]}

def recent_changes(a, u):
    """CloudTrail: who changed this instance recently (stop/start/modify/terminate/SG changes)."""
    iid = _resolve(a); hrs = int(a.get("hours", 24))
    ct = g._session().client("cloudtrail")
    ev = ct.lookup_events(LookupAttributes=[{"AttributeKey": "ResourceName", "AttributeValue": iid}],
                          StartTime=datetime.datetime.utcnow() - datetime.timedelta(hours=hrs), MaxResults=30)["Events"]
    return {"status": "ok", "events": [{"time": e["EventTime"].isoformat(), "event": e["EventName"],
            "user": e.get("Username", "?")} for e in ev]}

def logs_insights(a, u):
    """Run a CloudWatch Logs Insights query. Read-only. query example: fields @timestamp, @message | filter @message like /ERROR/ | limit 20"""
    logs = g._session().client("logs"); hrs = int(a.get("hours", 1))
    q = logs.start_query(logGroupName=a["log_group"], startTime=int(time.time()) - hrs * 3600, endTime=int(time.time()),
                         queryString=a["query"][:1000], limit=50)["queryId"]
    for _ in range(20):
        time.sleep(1.5); r = logs.get_query_results(queryId=q)
        if r["status"] in ("Complete", "Failed", "Cancelled"): break
    return {"status": r["status"].lower(), "rows": [{c["field"]: c["value"] for c in row} for row in r.get("results", [])][:30]}

def target_health(a, u):
    elb = g._session().client("elbv2"); out = []
    for tg in elb.describe_target_groups()["TargetGroups"]:
        for t in elb.describe_target_health(TargetGroupArn=tg["TargetGroupArn"])["TargetHealthDescriptions"]:
            out.append({"target_group": tg["TargetGroupName"], "target": t["Target"]["Id"],
                        "state": t["TargetHealth"]["State"], "reason": t["TargetHealth"].get("Reason", "")})
    return {"status": "ok", "targets": out, "unhealthy": [o for o in out if o["state"] != "healthy"]}

def security_group_review(a, u):
    """Flag risky open rules on the instance's security groups. Read-only; fixing needs a CHG."""
    iid = _resolve(a); ec2 = g._session().client("ec2")
    inst = ec2.describe_instances(InstanceIds=[iid])["Reservations"][0]["Instances"][0]
    sgs = [s["GroupId"] for s in inst["SecurityGroups"]]; findings = []
    for sg in ec2.describe_security_groups(GroupIds=sgs)["SecurityGroups"]:
        for p in sg["IpPermissions"]:
            for r in p.get("IpRanges", []):
                if r["CidrIp"] == "0.0.0.0/0" and p.get("FromPort") not in (80, 443):
                    findings.append(f"{sg['GroupId']}: {p.get('IpProtocol')} {p.get('FromPort')}-{p.get('ToPort')} open to the world")
    return {"status": "ok", "security_groups": sgs, "findings": findings or ["No world-open rules except 80/443"]}

def unused_resources(a, u):
    """Cost hygiene: unattached EBS volumes, unassociated Elastic IPs, old snapshots."""
    ec2 = g._session().client("ec2")
    vols = [{"id": v["VolumeId"], "gb": v["Size"]} for v in ec2.describe_volumes(
        Filters=[{"Name": "status", "Values": ["available"]}])["Volumes"]]
    eips = [e["PublicIp"] for e in ec2.describe_addresses()["Addresses"] if "AssociationId" not in e]
    return {"status": "ok", "unattached_volumes": vols, "unassociated_eips": eips,
            "note": "Deleting is blocked for the agent; raise a CHG to clean these up."}

def snapshot_create(a, u):
    """Snapshot all volumes of an instance. Mutating, needs approval."""
    iid = _resolve(a)
    ok, why, rec = g.validate_ticket(a.get("ticket"))
    if not ok: return {"status": "refused", "message": f"I can't proceed: {why}."}
    if not a.get("approved"):
        g.worknote(rec, f"Approval needed for snapshot of {iid}")
        return {"status": "needs_approval", "message": f"Creating snapshots of {iid} needs approval."}
    s = g._session(); ec2 = s.client("ec2")
    vols = [b["Ebs"]["VolumeId"] for b in ec2.describe_instances(InstanceIds=[iid])["Reservations"][0]["Instances"][0]["BlockDeviceMappings"]]
    ids = [ec2.create_snapshot(VolumeId=v, Description=f"{a['ticket']} pre-change snapshot")["SnapshotId"] for v in vols]
    g.worknote(rec, f"Snapshots created for {iid}: {', '.join(ids)}")
    return {"status": "created", "snapshots": ids}

# ---------------------------------------------------------------- tools: ServiceNow
def kb_search_v2(a, u):
    """Fixes the 'authentication required' error: queries published KB articles through the Table API."""
    t = a["query"].replace("^", " ")[:80]
    q = f"workflow_state=published^short_descriptionLIKE{t}^ORtextLIKE{t}"
    rows = g._snow("GET", f"/api/now/table/kb_knowledge?sysparm_query={urllib_quote(q)}&sysparm_limit=5"
                          "&sysparm_fields=number,short_description,sys_id,kb_knowledge_base")
    return {"status": "ok", "articles": [{"number": r["number"], "title": r["short_description"]} for r in rows]}

def kb_read_v2(a, u):
    rows = g._snow("GET", f"/api/now/table/kb_knowledge?sysparm_query=number={a['number']}&sysparm_limit=1&sysparm_fields=number,short_description,text")
    import re
    return {"status": "ok", "number": a["number"], "text": re.sub(r"<[^>]+>", " ", rows[0]["text"])[:6000]} if rows else {"status": "not_found"}

def urllib_quote(s):
    import urllib.parse; return urllib.parse.quote(s, safe="=^")

def create_incident(a, u):
    """Incident created by the chat is assigned to the AI agent user first."""
    r = g.create_ticket_as_agent("incident", a["short_description"], a.get("description", ""))
    return {"status": "created", "number": r["number"]}

def ticket_timeline(a, u):
    ok, why, rec = g.validate_ticket(a["ticket"])
    if not ok: return {"status": "refused", "message": why}
    notes = g._snow("GET", f"/api/now/table/sys_journal_field?sysparm_query=element_id={rec['sys_id']}^element=work_notes^ORDERBYsys_created_on&sysparm_fields=sys_created_on,value")
    return {"status": "ok", "ticket": a["ticket"], "short_description": rec.get("short_description"),
            "timeline": [{"at": n["sys_created_on"], "note": n["value"][:500]} for n in notes][-30:]}

def resolve_incident(a, u):
    """Close the loop: add resolution notes and move the incident to Resolved (state 6). Needs a valid incident."""
    ok, why, rec = g.validate_ticket(a["ticket"])
    if not ok or rec["_table"] != "incident": return {"status": "refused", "message": why if not ok else "Not an incident"}
    g._snow("PATCH", f"/api/now/table/incident/{rec['sys_id']}", {
        "state": "6", "close_code": "Solved (Permanently)", "close_notes": a["resolution_notes"][:3000],
        "work_notes": "[MATRIX AI] Resolved by agent. " + a["resolution_notes"][:1000]})
    return {"status": "resolved"}

def cost_report(a, u):
    return {"status": "ok", **cost_page_data(a.get("project_id", "default"), int(a.get("days", 30)))}

# ---------------------------------------------------------------- registry
def _t(name, desc, props, required):
    return {"name": name, "description": desc,
            "parameters": {"type": "object", "required": required, "properties": props}}
_S = {"type": "string"}; _I = {"type": "integer"}
_TARGET = {"ticket": _S, "instance_id": _S}

TOOLS = [
    _t("system_overview", "One-shot health snapshot of a host: load, memory, disk, inodes, failed services, recent errors.", _TARGET, ["instance_id"]),
    _t("memory_diagnostics", "Memory/swap usage, top memory processes, OOM kills on a host.", _TARGET, ["instance_id"]),
    _t("port_check", "Listening ports and connection counts on a host.", _TARGET, ["instance_id"]),
    _t("cert_check", "Days left on a TLS certificate seen from the host.", {**_TARGET, "host": _S, "port": _I}, ["instance_id"]),
    _t("network_check", "DNS and TCP connectivity test from a host to host:port.", {**_TARGET, "host": _S, "port": _I}, ["instance_id", "host"]),
    _t("large_files", "Largest files under a path on a host.", {**_TARGET, "path": _S}, ["instance_id"]),
    _t("log_tail", "Last N lines of an allowlisted log file (/var/log/messages, nginx, httpd, ssm, cloudwatch agent).", {**_TARGET, "log_file": _S, "lines": _I}, ["instance_id", "log_file"]),
    _t("backup_status", "Backup/cron job status on a host.", _TARGET, ["instance_id"]),
    _t("log_cleanup", "Delete old rotated logs and vacuum the journal. Needs approval.", {**_TARGET, "days": _I}, ["ticket", "instance_id"]),
    _t("service_action", "start/stop/restart/status of an allowlisted service. Changes need approval.", {**_TARGET, "service": _S, "action": {"type": "string", "enum": ["start", "stop", "restart", "status"]}}, ["ticket", "instance_id", "service", "action"]),
    _t("run_command", "Run a shell command through SSM (no SSH). Read-only runs automatically; changes need approval; dangerous ones are blocked.", {**_TARGET, "command": _S}, ["ticket", "instance_id", "command"]),
    _t("metric_trend", "CloudWatch trend for cpu, mem, disk, network_in, network_out, status_failed over N hours.", {"instance_id": _S, "name": _S, "metric": _S, "hours": _I}, []),
    _t("alarm_history", "Recent alarm state changes for an instance.", {"instance_id": _S, "name": _S}, []),
    _t("recent_changes", "CloudTrail: who changed this instance recently. First thing to check for 'it broke after...'.", {"instance_id": _S, "name": _S, "hours": _I}, []),
    _t("logs_insights", "Run a CloudWatch Logs Insights query on a log group.", {"log_group": _S, "query": _S, "hours": _I}, ["log_group", "query"]),
    _t("target_health", "Health of all load balancer targets; lists unhealthy ones.", {}, []),
    _t("security_group_review", "Find risky world-open rules on an instance's security groups.", {"instance_id": _S, "name": _S}, []),
    _t("unused_resources", "Find unattached volumes and idle Elastic IPs (cost savings).", {}, []),
    _t("snapshot_create", "Snapshot an instance's volumes before a change. Needs approval.", {"ticket": _S, "instance_id": _S, "name": _S}, ["ticket"]),
    _t("kb_search", "Search published ServiceNow KB articles.", {"query": _S}, ["query"]),
    _t("kb_read", "Read a KB article by number (KB0010001).", {"number": _S}, ["number"]),
    _t("create_incident", "Create an incident from chat. It is assigned to the AI agent user.", {"short_description": _S, "description": _S}, ["short_description"]),
    _t("ticket_timeline", "Show a CHG/INC's work-note timeline. Use to draft an RCA or hand over to a human.", {"ticket": _S}, ["ticket"]),
    _t("resolve_incident", "Resolve an incident with resolution notes.", {"ticket": _S, "resolution_notes": _S}, ["ticket", "resolution_notes"]),
    _t("cost_report", "AWS + LLM cost summary for the project.", {"project_id": _S, "days": _I}, []),
]

HANDLERS = {f.__name__: f for f in [
    system_overview, memory_diagnostics, port_check, cert_check, network_check, large_files, log_tail, backup_status,
    log_cleanup, service_action, run_command, metric_trend, alarm_history, recent_changes, logs_insights,
    target_health, security_group_review, unused_resources, snapshot_create, create_incident,
    ticket_timeline, resolve_incident, cost_report]}
HANDLERS["kb_search"] = kb_search_v2
HANDLERS["kb_read"] = kb_read_v2

def call_tool(name, args, user):
    """user = {'name':..., 'role':'L2'|'L3'} taken from the login token, never from the LLM."""
    if name not in HANDLERS: return {"status": "error", "message": f"unknown tool {name}"}
    try:
        return HANDLERS[name](dict(args), user)
    except Exception as e:
        return {"status": "error", "message": f"{type(e).__name__}: {str(e)[:300]}"}
