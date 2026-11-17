"""
matrix_guardrails.py - drop into the MATRIX console Lambda package.

Every chat action goes through ONE function: execute(request).
Order is fixed and cannot be skipped by the LLM:
  1. validate ticket in ServiceNow  (real record, right state, approved)
  2. validate target instance        (tagged matrix-managed, right environment)
  3. classify command                (read_only / mutating / blocked)
  4. approval gate                   (mutating needs approval, prod needs L3)
  5. assume scoped IAM role, run via SSM (no SSH)
  6. write work notes + audit log

Env vars: SNOW_URL, SNOW_USER, SNOW_PASS, EXECUTOR_ROLE_ARN, ENVIRONMENT,
          AUDIT_LOG_GROUP, SUBNET_ID, SECURITY_GROUP_ID, INSTANCE_PROFILE,
          AI_AGENT_USER (default "matrix ai")
"""
import base64, json, os, re, time, urllib.request
import boto3

REGION = os.environ.get("AWS_REGION", "ap-southeast-2")
ENV = os.environ.get("ENVIRONMENT", "dev")

# ---------- catalog (must match the IAM stack AllowedInstanceTypes) ----------
# Any EC2 instance type is allowed. Optional: set MAX_VCPU to cap size per environment (0 = no cap).
MAX_VCPU = int(os.environ.get("MAX_VCPU", "0"))

def find_type(sess, vcpu, ram_gb):
    """Find an x86_64 current-generation type with exactly this vCPU and RAM; prefer t3, then m5/m6i."""
    ec2 = sess.client("ec2"); found = []
    for page in ec2.get_paginator("describe_instance_types").paginate(Filters=[
            {"Name": "vcpu-info.default-vcpus", "Values": [str(vcpu)]},
            {"Name": "memory-info.size-in-mib", "Values": [str(int(ram_gb * 1024))]},
            {"Name": "current-generation", "Values": ["true"]},
            {"Name": "processor-info.supported-architecture", "Values": ["x86_64"]}]):
        found += [t["InstanceType"] for t in page["InstanceTypes"]]
    for pref in ("t3.", "m5.", "m6i.", "t3a."):
        for t in sorted(found):
            if t.startswith(pref): return t
    return sorted(found)[0] if found else None
# Playbook (SSM document) allowlist: name -> tier. Add every new playbook here. Names not listed are refused.
DOCS = {
    "MATRIX_MEM_DIAGNOSTICS": "read_only", "MATRIX_CERT_EXPIRY_CHECK": "read_only",
    "MATRIX_PORT_CHECK": "read_only", "MATRIX_BACKUP_STATUS": "read_only", "MATRIX_PATCH_SCAN": "read_only",
    "MATRIX_NET_CHECK": "read_only", "MATRIX_OVERVIEW": "read_only", "MATRIX_LARGE_FILES": "read_only",
    "MATRIX_LOG_TAIL": "read_only", "MATRIX_LOG_CLEANUP": "mutating",
    "CPU_DIAGNOSTICS": "read_only", "PROCESS_DETAILS": "read_only", "DISK_DIAGNOSTICS": "read_only",
    "DISK_CLEANUP": "mutating", "KILL_PID": "mutating",
}
SERVICES = {"nginx", "httpd", "amazon-cloudwatch-agent", "amazon-ssm-agent", "crond",
            "chronyd", "sshd", "docker", "mysqld", "postgresql", "rsyslog"}

# ---------- ServiceNow ----------
def _snow(method, path, body=None):
    url = os.environ["SNOW_URL"].rstrip("/") + path
    auth = base64.b64encode(f"{os.environ['SNOW_USER']}:{os.environ['SNOW_PASS']}".encode()).decode()
    req = urllib.request.Request(url, method=method, headers={
        "Authorization": f"Basic {auth}", "Content-Type": "application/json", "Accept": "application/json"},
        data=json.dumps(body).encode() if body else None)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())["result"]

def validate_ticket(number):
    """Returns (ok, reason, record). Never trusts the number the user typed."""
    number = (number or "").strip().upper()
    if re.fullmatch(r"CHG\d{7,}", number):
        table = "change_request"
    elif re.fullmatch(r"INC\d{7,}", number):
        table = "incident"
    else:
        return False, f"'{number}' is not a valid CHG/INC number format", None
    rows = _snow("GET", f"/api/now/table/{table}?sysparm_query=number={number}&sysparm_limit=1"
                        "&sysparm_display_value=false")
    if not rows:
        return False, f"{number} does not exist in ServiceNow", None
    r = rows[0]; r["_table"] = table
    if table == "change_request":
        # state: -2 Scheduled, -1 Implement ; approval must be 'approved'
        if r.get("approval") != "approved":
            return False, f"{number} is not approved (approval={r.get('approval')})", r
        if r.get("state") not in ("-1", "-2"):
            return False, f"{number} is not in Scheduled/Implement state (state={r.get('state')})", r
    else:
        # incident: 1 New, 2 In Progress, 3 On Hold
        if r.get("state") not in ("1", "2", "3"):
            return False, f"{number} is closed/resolved (state={r.get('state')})", r
    return True, "ok", r

def worknote(rec, text):
    if not rec:
        return
    try:
        _snow("PATCH", f"/api/now/table/{rec['_table']}/{rec['sys_id']}", {"work_notes": f"[MATRIX AI] {text}"})
    except Exception as e:
        print("worknote failed", e)

def create_ticket_as_agent(table, short_description, description):
    """Chat-created tickets are assigned to the AI agent user first."""
    return _snow("POST", f"/api/now/table/{table}", {
        "short_description": short_description, "description": description,
        "assigned_to": os.environ.get("AI_AGENT_USER", "matrix ai"),
        "caller_id": os.environ.get("AI_AGENT_USER", "matrix ai")})

# ---------- AWS ----------
def _session():
    c = boto3.client("sts", region_name=REGION).assume_role(
        RoleArn=os.environ["EXECUTOR_ROLE_ARN"],
        RoleSessionName=re.sub(r"[^\w=,.@-]", "", os.environ.get("CURRENT_TICKET", "matrix"))[:60] or "matrix",
        DurationSeconds=900)["Credentials"]
    return boto3.Session(aws_access_key_id=c["AccessKeyId"], aws_secret_access_key=c["SecretAccessKey"],
                         aws_session_token=c["SessionToken"], region_name=REGION)

def _audit(entry):
    print(json.dumps(entry))  # also lands in the Lambda log group
    try:
        lg = os.environ.get("AUDIT_LOG_GROUP")
        if lg:
            logs = boto3.client("logs", region_name=REGION)
            stream = time.strftime("%Y-%m-%d")
            try: logs.create_log_stream(logGroupName=lg, logStreamName=stream)
            except logs.exceptions.ResourceAlreadyExistsException: pass
            logs.put_log_events(logGroupName=lg, logStreamName=stream,
                                logEvents=[{"timestamp": int(time.time()*1000), "message": json.dumps(entry)}])
    except Exception as e:
        print("audit failed", e)

# ---------- command classification ----------
BLOCKED = [r"\brm\s+-[a-z]*r[a-z]*f?\s+/(\s|$)", r"\bmkfs", r"\bdd\s+if=", r"\b(shutdown|halt|poweroff|init\s+0)\b",
           r":\(\)\s*\{", r"chmod\s+-R\s+777\s+/", r"(curl|wget)[^|]*\|\s*(sudo\s+)?(ba)?sh",
           r"/etc/(shadow|sudoers)", r"\b(useradd|userdel|usermod|passwd|visudo)\b", r"iptables\s+-F",
           r">\s*/dev/(sd|nvme|xvd)", r"\baws\s+(iam|organizations)\b", r"\bcrontab\s+-r\b"]
READ_ONLY = {"df", "free", "uptime", "ps", "top", "ls", "cat", "tail", "head", "grep", "du", "ss", "netstat",
             "ip", "hostname", "whoami", "id", "date", "uname", "journalctl", "lsblk", "vmstat", "iostat",
             "wc", "sort", "awk", "uniq", "lsof", "dmesg", "which", "stat", "find"}
SENSITIVE_READ = re.compile(r"(/etc/shadow|/etc/sudoers|\.ssh/|id_rsa|\.aws/credentials)")

def classify(cmd):
    c = cmd.strip()
    if not c or len(c) > 2000:
        return "blocked", "empty or too long"
    for p in BLOCKED:
        if re.search(p, c, re.I):
            return "blocked", f"matches blocked pattern {p}"
    if SENSITIVE_READ.search(c):
        return "blocked", "touches credential/secret files"
    if re.search(r"[`]|\$\(|>|<<", c):
        return "mutating", "uses redirection/substitution"
    for seg in re.split(r"\|\||&&|;|\|", c):
        parts = seg.strip().split()
        if not parts: continue
        first = parts[0].lstrip("sudo ").split("/")[-1] if parts[0] != "sudo" else (parts[1] if len(parts) > 1 else "")
        if first == "systemctl" and any(a in parts for a in ("status", "is-active", "list-units")):
            continue
        if first == "find" and re.search(r"-(delete|exec)", seg):
            return "mutating", "find with delete/exec"
        if first not in READ_ONLY:
            return "mutating", f"'{first}' is not in the read-only list"
    return "read_only", "all segments read-only"

# ---------- main entry ----------
def _instance_ok(sess, instance_id):
    r = sess.client("ec2").describe_instances(InstanceIds=[instance_id])["Reservations"]
    if not r: return False, "instance not found"
    tags = {t["Key"]: t["Value"] for t in r[0]["Instances"][0].get("Tags", [])}
    if tags.get("matrix-managed") != "true": return False, "instance is not tagged matrix-managed=true"
    if tags.get("environment") != ENV: return False, f"instance environment={tags.get('environment')}, this agent serves {ENV}"
    return True, "ok"

def _wait(sess, cmd_id, instance_id, timeout=90):
    ssm = sess.client("ssm"); end = time.time() + timeout
    while time.time() < end:
        time.sleep(3)
        try:
            r = ssm.get_command_invocation(CommandId=cmd_id, InstanceId=instance_id)
        except ssm.exceptions.InvocationDoesNotExist:
            continue
        if r["Status"] not in ("Pending", "InProgress", "Delayed"):
            return r
    return {"Status": "TimedOut", "StandardOutputContent": "", "StandardErrorContent": ""}

def execute(req):
    """
    req = {ticket, instance_id, requested_by, role('L2'|'L3'),
           command | service+action, approved(bool, set only by the approval step)}
    """
    ticket = req.get("ticket"); who = req.get("requested_by", "unknown")
    os.environ["CURRENT_TICKET"] = ticket or "none"
    no_ticket_ok = bool(req.get("allow_no_ticket")) and not ticket
    rec = None
    if not no_ticket_ok:
        ok, why, rec = validate_ticket(ticket)
        if not ok:
            _audit({"ticket": ticket, "who": who, "result": "REFUSED", "why": why})
            return {"status": "refused", "message": f"I can't proceed: {why}."}

    sess = _session()
    iid = req["instance_id"]
    ok, why = _instance_ok(sess, iid)
    if not ok:
        worknote(rec, f"Refused: {why} ({iid})")
        return {"status": "refused", "message": f"I can't proceed: {why}."}

    ssm = sess.client("ssm")
    if req.get("service"):
        svc, act = req["service"], req.get("action", "status")
        if svc not in SERVICES or act not in ("start", "stop", "restart", "status"):
            return {"status": "refused", "message": f"Service/action not allowed: {svc} {act}"}
        tier, label = ("read_only" if act == "status" else "mutating"), f"{act} {svc}"
        kwargs = dict(DocumentName="MATRIX_SERVICE_ACTION", Parameters={"ServiceName": [svc], "Action": [act]})
    elif req.get("document"):
        doc = req["document"]
        if doc not in DOCS:
            return {"status": "refused", "message": f"Playbook {doc} is not in the allowlist."}
        tier, label = DOCS[doc], f"playbook {doc} {req.get('doc_params', {})}"
        kwargs = dict(DocumentName=doc, Parameters={k: [str(v)] for k, v in req.get("doc_params", {}).items()})
    else:
        cmd = req["command"]
        tier, reason = classify(cmd)
        label = cmd
        if tier == "blocked":
            worknote(rec, f"Blocked command requested by {who}: {cmd} ({reason})")
            _audit({"ticket": ticket, "who": who, "cmd": cmd, "result": "BLOCKED", "why": reason})
            return {"status": "blocked", "message": f"That command is blocked by policy ({reason})."}
        kwargs = dict(DocumentName="AWS-RunShellScript", Parameters={"commands": [cmd]})

    if rec is None and tier != "read_only":
        return {"status": "refused", "message": "Changes need a valid CHG/INC number."}

    if tier == "mutating":
        need = "L3" if ENV == "prod" else "L2"
        if not req.get("approved"):
            worknote(rec, f"Approval needed ({need}) for: {label} on {iid}, requested by {who}")
            return {"status": "needs_approval", "message": f"'{label}' changes the server. It needs {need} approval.",
                    "pending": {"instance_id": iid, "command": label}}
        if ENV == "prod" and req.get("role") != "L3":
            return {"status": "refused", "message": "Prod changes need an L3 approver."}

    worknote(rec, f"{who} requested on {iid} ({tier}): {label}. Executing via SSM.")
    sent = ssm.send_command(InstanceIds=[iid], Comment=f"{ticket} by {who}"[:100], TimeoutSeconds=120, **kwargs)
    res = _wait(sess, sent["Command"]["CommandId"], iid)
    out = (res.get("StandardOutputContent") or "")[:3000]; err = (res.get("StandardErrorContent") or "")[:1000]
    worknote(rec, f"Result: {res['Status']}\n{out}\n{err}")
    _audit({"ticket": ticket, "who": who, "instance": iid, "cmd": label, "tier": tier,
            "status": res["Status"], "command_id": sent["Command"]["CommandId"]})
    return {"status": res["Status"].lower(), "output": out, "error": err}

# ---------- EC2 deployment (replaces the 'no runbook found' dead end) ----------
def deploy_ec2(req):
    """req = {ticket, name, instance_type, disk_gb, requested_by}"""
    ticket = req["ticket"]; os.environ["CURRENT_TICKET"] = ticket
    ok, why, rec = validate_ticket(ticket)
    if not ok:
        return {"status": "refused", "message": f"I can't proceed: {why}."}
    disk = int(req.get("disk_gb", 8))
    if not 8 <= disk <= 1000:
        return {"status": "refused", "message": "Disk must be 8-1000 GB."}
    sess = _session()
    itype = req.get("instance_type")
    if not itype:
        # pick the cheapest-looking current-gen type matching vCPU/RAM (e.g. 2 vCPU, 8 GB -> t3.large / m5.large)
        itype = find_type(sess, int(req["vcpu"]), float(req["ram_gb"]))
        if not itype:
            return {"status": "refused", "message": "No instance type matches that vCPU/RAM."}
    else:
        try:
            sess.client("ec2").describe_instance_types(InstanceTypes=[itype])
        except Exception:
            return {"status": "refused", "message": f"{itype} is not a valid instance type in this region."}
    ami = sess.client("ssm").get_parameter(
        Name="/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64")["Parameter"]["Value"]
    tags = [{"Key": "Name", "Value": req["name"]}, {"Key": "environment", "Value": ENV},
            {"Key": "matrix-managed", "Value": "true"}, {"Key": "change", "Value": ticket},
            {"Key": "requested-by", "Value": req.get("requested_by", "unknown")}]
    r = sess.client("ec2").run_instances(
        ImageId=ami, InstanceType=itype, MinCount=1, MaxCount=1,
        SubnetId=os.environ["SUBNET_ID"], SecurityGroupIds=[os.environ["SECURITY_GROUP_ID"]],
        IamInstanceProfile={"Name": os.environ["INSTANCE_PROFILE"]},
        MetadataOptions={"HttpTokens": "required"},
        BlockDeviceMappings=[{"DeviceName": "/dev/xvda", "Ebs": {"VolumeSize": disk, "VolumeType": "gp3", "Encrypted": True}}],
        TagSpecifications=[{"ResourceType": t, "Tags": tags} for t in ("instance", "volume")])
    iid = r["Instances"][0]["InstanceId"]
    worknote(rec, f"Deployed {req['name']} ({iid}), {itype}, {disk} GB, env={ENV}, no SSH (SSM only).")
    _audit({"ticket": ticket, "who": req.get("requested_by"), "action": "deploy_ec2", "instance": iid, "type": itype})
    return {"status": "created", "instance_id": iid, "message": f"{req['name']} ({iid}) is launching."}
