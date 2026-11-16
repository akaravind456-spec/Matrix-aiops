"""MATRIX ServiceNow tools: incident, change, SR task, work notes, resolve, reassign.

Env vars (same ones the Lambda already uses):
  SN_BASE  https://devXXXXXX.service-now.com   (no trailing slash)
  SN_USER  SN_PASS
Optional:
  SN_AI_USER   default "matrix.ai"       (assignee for AI-owned tickets)
  SN_AI_GROUP  default "MATRIX-AI-L1"    (L1 AI queue)
  SN_L2_GROUP  default "MATRIX-L2"       (human escalation queue)

Every function returns a plain dict: {"ok": True, ...} or {"ok": False, "error": "..."}.
No function raises, so the agent loop never crashes on a ServiceNow problem.
"""
import os, re, json, base64, urllib.request, urllib.error, urllib.parse


class SNError(Exception):
    pass


# ----------------------------------------------------------------- low level
def _sn(method, path, body=None, params=None):
    base = os.environ.get("SN_BASE", "").strip().rstrip("/")
    user = os.environ.get("SN_USER", "")
    pw = os.environ.get("SN_PASS", "")
    if not (base and user and pw):
        raise SNError("ServiceNow is not configured (SN_BASE / SN_USER / SN_PASS missing)")
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode())
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise SNError("ServiceNow login failed (401). Check SN_USER / SN_PASS.")
        if e.code == 403:
            raise SNError("ServiceNow refused (403). The integration user lacks a role or ACL for this table.")
        raise SNError(f"ServiceNow error {e.code}: {e.read()[:200].decode('utf-8', 'ignore')}")
    except urllib.error.URLError as e:
        raise SNError(f"Cannot reach ServiceNow: {e.reason}")
    return (json.loads(raw).get("result") if raw else {}) or {}


def _query(table, query, fields="", limit=1):
    p = {"sysparm_query": query, "sysparm_limit": limit}
    if fields:
        p["sysparm_fields"] = fields
    r = _sn("GET", f"/api/now/table/{table}", params=p)
    return r if isinstance(r, list) else [r]


def _sys_id(table, query):
    rows = _query(table, query, "sys_id")
    return rows[0]["sys_id"] if rows and rows[0] else None


def _ci_id(name):
    return _sys_id("cmdb_ci", f"name={name}")


def _group_id(name):
    return _sys_id("sys_user_group", f"name={name}")


def _user_id(user_name):
    return _sys_id("sys_user", f"user_name={user_name}")


_SECRET = re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key|authorization)\s*[=:]\s*\S+")


def _clean(text, limit=3800):
    return _SECRET.sub(lambda m: m.group(1) + "=****", str(text or ""))[:limit]


_TABLE_BY_PREFIX = {"INC": "incident", "CHG": "change_request", "SCTASK": "sc_task",
                    "RITM": "sc_req_item", "REQ": "sc_request", "TASK": "task"}


def _table_for(number):
    m = re.match(r"([A-Z]+)\d+", number or "")
    if not m or m.group(1) not in _TABLE_BY_PREFIX:
        raise SNError(f"Unknown ticket number format: {number!r}")
    return _TABLE_BY_PREFIX[m.group(1)]


def _by_number(number):
    table = _table_for(number)
    rows = _query(table, f"number={number}", limit=1)
    if not rows or not rows[0]:
        raise SNError(f"{number} not found")
    return table, rows[0]


def _safe(fn):
    def wrap(**kw):
        try:
            return fn(**kw)
        except SNError as e:
            return {"ok": False, "error": str(e)}
        except TypeError as e:
            return {"ok": False, "error": f"bad arguments: {e}"}
        except Exception as e:  # never crash the agent loop
            return {"ok": False, "error": f"unexpected error: {e}"}
    wrap.__name__ = fn.__name__
    wrap.__doc__ = fn.__doc__
    return wrap


# ------------------------------------------------------------------- tools
@_safe
def get_ticket(number):
    table, r = _by_number(number)
    keep = ("number", "short_description", "state", "priority", "approval", "assignment_group",
            "assigned_to", "cmdb_ci", "opened_at", "type", "risk", "start_date", "end_date")
    return {"ok": True, "table": table, "ticket": {k: r.get(k) for k in keep if k in r}}


@_safe
def add_work_note(number, note):
    """Append a work note (internal) to any ticket. Secrets are masked."""
    table, r = _by_number(number)
    _sn("PATCH", f"/api/now/table/{table}/{r['sys_id']}", {"work_notes": _clean(note)})
    return {"ok": True, "number": number}


@_safe
def create_incident(ci=None, short_description=None, description=None, error_log=None,
                    urgency=3, impact=3, category="software", assign_to_ai=True):
    """Create an incident. Refuses vague requests: CI, summary and evidence are required."""
    evidence = (description or "") + (error_log or "")
    missing = [n for n, v in (("ci", ci), ("short_description", short_description),
                              ("description_or_error_log", evidence.strip())) if not v]
    if missing:
        return {"ok": False, "needs_info": missing,
                "ask": "Please give the CI (server name), a one-line summary, and the error log or what you see."}
    ci_id = _ci_id(ci)
    if not ci_id:
        return {"ok": False, "error": f"CI '{ci}' not found in the CMDB. Check the name or add it to the CMDB."}
    dup = _query("incident", f"active=true^cmdb_ci={ci_id}^short_description={short_description}",
                 "number,state", 1)
    if dup and dup[0]:
        return {"ok": True, "duplicate": True, "number": dup[0]["number"],
                "message": "An open incident for this CI and summary already exists; reusing it."}
    body = {"short_description": short_description[:160],
            "description": _clean(description or error_log),
            "cmdb_ci": ci_id, "urgency": str(urgency), "impact": str(impact), "category": category}
    if assign_to_ai:
        g = _group_id(os.environ.get("SN_AI_GROUP", "MATRIX-AI-L1"))
        u = _user_id(os.environ.get("SN_AI_USER", "matrix.ai"))
        if g:
            body["assignment_group"] = g
        if u:
            body["assigned_to"] = u
    r = _sn("POST", "/api/now/table/incident", body)
    if error_log and description:
        _sn("PATCH", f"/api/now/table/incident/{r['sys_id']}", {"work_notes": "Error log:\n" + _clean(error_log)})
    return {"ok": True, "number": r["number"], "sys_id": r["sys_id"]}


@_safe
def create_change(ci=None, short_description=None, description=None, change_type="normal",
                  implementation_plan=None, backout_plan=None, test_plan=None,
                  start_date=None, end_date=None, risk="3", justification=None):
    """Create a change request. Normal/emergency changes need plans and a window."""
    need = [("ci", ci), ("short_description", short_description), ("description", description)]
    if change_type in ("normal", "emergency"):
        need += [("implementation_plan", implementation_plan), ("backout_plan", backout_plan),
                 ("test_plan", test_plan), ("start_date", start_date), ("end_date", end_date)]
    missing = [n for n, v in need if not v]
    if missing:
        return {"ok": False, "needs_info": missing,
                "ask": "A change needs: " + ", ".join(missing) + ". Dates as 'YYYY-MM-DD HH:MM:SS' (UTC)."}
    ci_id = _ci_id(ci)
    if not ci_id:
        return {"ok": False, "error": f"CI '{ci}' not found in the CMDB."}
    body = {"type": change_type, "short_description": short_description[:160], "description": _clean(description),
            "cmdb_ci": ci_id, "risk": str(risk), "justification": _clean(justification or description),
            "implementation_plan": _clean(implementation_plan), "backout_plan": _clean(backout_plan),
            "test_plan": _clean(test_plan)}
    if start_date:
        body["start_date"] = start_date
    if end_date:
        body["end_date"] = end_date
    g = _group_id(os.environ.get("SN_AI_GROUP", "MATRIX-AI-L1"))
    if g:
        body["assignment_group"] = g
    r = _sn("POST", "/api/now/table/change_request", body)
    return {"ok": True, "number": r["number"], "sys_id": r["sys_id"],
            "note": "Change still needs approval in ServiceNow before the agent can execute it."}


@_safe
def create_sr_task(short_description=None, description=None, ci=None, requested_for=None, assign_to_ai=True):
    """Create a Service Request with a catalog task: REQ -> RITM -> SCTASK."""
    if not short_description or not description:
        return {"ok": False, "needs_info": [n for n, v in (("short_description", short_description),
                                                           ("description", description)) if not v],
                "ask": "Please give a one-line summary and what exactly is needed."}
    who = _user_id(requested_for) if requested_for else _user_id(os.environ.get("SN_AI_USER", "matrix.ai"))
    req = _sn("POST", "/api/now/table/sc_request",
              {"short_description": short_description[:160], "description": _clean(description),
               **({"requested_for": who} if who else {})})
    ritm_body = {"request": req["sys_id"], "short_description": short_description[:160]}
    if ci and _ci_id(ci):
        ritm_body["cmdb_ci"] = _ci_id(ci)
    ritm = _sn("POST", "/api/now/table/sc_req_item", ritm_body)
    task_body = {"request": req["sys_id"], "request_item": ritm["sys_id"],
                 "short_description": short_description[:160], "description": _clean(description)}
    if assign_to_ai:
        g = _group_id(os.environ.get("SN_AI_GROUP", "MATRIX-AI-L1"))
        u = _user_id(os.environ.get("SN_AI_USER", "matrix.ai"))
        if g:
            task_body["assignment_group"] = g
        if u:
            task_body["assigned_to"] = u
    t = _sn("POST", "/api/now/table/sc_task", task_body)
    return {"ok": True, "request": req["number"], "item": ritm["number"], "task": t["number"]}


@_safe
def resolve_incident(number, close_notes, close_code="Solved (Permanently)"):
    if not number.startswith("INC"):
        return {"ok": False, "error": "resolve_incident only works on INC numbers"}
    _, r = _by_number(number)
    _sn("PATCH", f"/api/now/table/incident/{r['sys_id']}",
        {"state": "6", "close_code": close_code, "close_notes": _clean(close_notes)})
    return {"ok": True, "number": number, "state": "Resolved"}


@_safe
def escalate_ticket(number, reason, level="L2"):
    """Reassign to the human queue and leave a work note explaining why."""
    table, r = _by_number(number)
    gname = os.environ.get("SN_L2_GROUP", "MATRIX-L2") if level == "L2" else os.environ.get("SN_L3_GROUP", "MATRIX-L3")
    gid = _group_id(gname)
    if not gid:
        return {"ok": False, "error": f"group {gname} not found in ServiceNow"}
    _sn("PATCH", f"/api/now/table/{table}/{r['sys_id']}",
        {"assignment_group": gid, "assigned_to": "", "work_notes": f"Escalated to {level} by MATRIX AI: {_clean(reason)}"})
    return {"ok": True, "number": number, "assigned_group": gname}


# ---------------------------------------------------------- registration
_STR = {"type": "string"}
TOOL_SPECS = [
    {"name": "snow_create_incident",
     "description": "Create a ServiceNow incident assigned to the AI queue. If CI, summary or error evidence is missing, "
                    "it returns needs_info; ask the user for those first, never guess them.",
     "input_schema": {"type": "object", "properties": {"ci": _STR, "short_description": _STR, "description": _STR,
                      "error_log": _STR, "urgency": {"type": "integer", "enum": [1, 2, 3]},
                      "impact": {"type": "integer", "enum": [1, 2, 3]}}, "required": []}},
    {"name": "snow_create_change",
     "description": "Create a change request (normal, standard or emergency). Needs implementation, backout and test plans "
                    "and a window for normal/emergency. It still needs approval before execution.",
     "input_schema": {"type": "object", "properties": {"ci": _STR, "short_description": _STR, "description": _STR,
                      "change_type": {"type": "string", "enum": ["normal", "standard", "emergency"]},
                      "implementation_plan": _STR, "backout_plan": _STR, "test_plan": _STR,
                      "start_date": _STR, "end_date": _STR, "risk": _STR, "justification": _STR}, "required": []}},
    {"name": "snow_create_sr_task",
     "description": "Create a service request (REQ, RITM and SCTASK) for a routine ask.",
     "input_schema": {"type": "object", "properties": {"short_description": _STR, "description": _STR,
                      "ci": _STR, "requested_for": _STR}, "required": []}},
    {"name": "snow_add_work_note",
     "description": "Add an internal work note to INC, CHG, REQ, RITM or SCTASK. Use after every investigation step and action.",
     "input_schema": {"type": "object", "properties": {"number": _STR, "note": _STR}, "required": ["number", "note"]}},
    {"name": "snow_get_ticket",
     "description": "Read state, priority, approval and assignment of a ticket.",
     "input_schema": {"type": "object", "properties": {"number": _STR}, "required": ["number"]}},
    {"name": "snow_resolve_incident",
     "description": "Resolve an incident after the fix is validated against CloudWatch or a health check.",
     "input_schema": {"type": "object", "properties": {"number": _STR, "close_notes": _STR}, "required": ["number", "close_notes"]}},
    {"name": "snow_escalate",
     "description": "Reassign a ticket to the L2 or L3 human queue with the reason.",
     "input_schema": {"type": "object", "properties": {"number": _STR, "reason": _STR,
                      "level": {"type": "string", "enum": ["L2", "L3"]}}, "required": ["number", "reason"]}},
]

HANDLERS = {"snow_create_incident": create_incident, "snow_create_change": create_change,
            "snow_create_sr_task": create_sr_task, "snow_add_work_note": add_work_note,
            "snow_get_ticket": get_ticket, "snow_resolve_incident": resolve_incident,
            "snow_escalate": escalate_ticket}


def register(add_tool):
    """add_tool(name, description, input_schema, handler) is whatever your Lambda uses to register a tool."""
    for spec in TOOL_SPECS:
        add_tool(spec["name"], spec["description"], spec["input_schema"], HANDLERS[spec["name"]])
