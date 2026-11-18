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
import matrix_mode as mode


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
    """Create a change request. Normal/emergency changes need plans and a window.
    With CHANGE_MODE=incident (no Change module) the planned work is tracked on an incident instead."""
    if mode.incident_mode():
        miss = [n for n, v in (("ci", ci), ("short_description", short_description), ("description", description)) if not v]
        if miss:
            return {"ok": False, "needs_info": miss, "ask": "Planned work needs: " + ", ".join(miss) + "."}
        plan = "\n".join(x for x in (
            "Implementation plan:\n" + _clean(implementation_plan) if implementation_plan else "",
            "Back-out plan:\n" + _clean(backout_plan) if backout_plan else "",
            "Test plan:\n" + _clean(test_plan) if test_plan else "",
            "Window: %s to %s" % (start_date, end_date) if start_date or end_date else "") if x)
        r = create_incident(ci=ci, short_description="[PLANNED] " + short_description, description=_clean(description) + ("\n\n" + plan if plan else ""),
                            urgency=3, impact=3, category="inquiry")
        if r.get("ok"):
            r["note"] = "Tracked on an incident because there is no Change module. The engineer's Confirm in the console is the approval."
        return r
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


# ------------------------------------------------- extra tools: search, checks, updates, problems, CMDB
def _q(text):
    """Make a user string safe inside an encoded query: no ^ (query separator) and no operators."""
    return re.sub(r"[\^=<>]", " ", str(text or "")).strip()[:120]


@_safe
def search_tickets(text=None, ci=None, table="incident", only_open=True, limit=10):
    """Find tickets by words in the summary and/or the CI name (both must match when both are given)."""
    if table not in ("incident", "change_request", "problem", "sc_task"):
        return {"ok": False, "error": "table must be incident, change_request, problem or sc_task"}
    t, c = _q(text), _q(ci)
    if not (t or c):
        return {"ok": False, "needs_info": ["text or ci"], "ask": "What should I search for, or which CI?"}
    parts = (["active=true"] if only_open else []) + (["short_descriptionLIKE" + t] if t else []) + (["cmdb_ci.name=" + c] if c else [])
    query = "^".join(parts)
    rows = _query(table, query + "^ORDERBYDESCsys_created_on", "number,short_description,state,priority,assignment_group,opened_at", min(int(limit), 25))
    return {"ok": True, "count": len([r for r in rows if r]), "tickets": [r for r in rows if r]}


@_safe
def check_change_approval(number):
    """Is this change approved, in the right state and inside its window? Never guesses: reads ServiceNow."""
    if mode.incident_mode() and str(number).startswith("INC"):
        _, r = _by_number(number)
        active = r.get("state") in ("1", "2", "3")
        return {"ok": True, "change": {"number": number, "state": r.get("state"), "approved": active, "state_ok": active, "ready_to_execute": active,
                                       "note": "Tracked on an incident (no Change module). The engineer's Confirm is the approval.",
                                       **({} if active else {"why_not": "the incident is resolved or closed"})}}
    if not str(number).startswith("CHG"):
        return {"ok": False, "error": "check_change_approval only works on CHG numbers" + (" (or INC numbers when CHANGE_MODE=incident)" if mode.incident_mode() else "")}
    _, r = _by_number(number)
    approved = r.get("approval") == "approved"
    in_state = r.get("state") in ("-1", "-2")
    res = {"number": number, "approval": r.get("approval"), "state": r.get("state"), "window_start": r.get("start_date"),
           "window_end": r.get("end_date"), "approved": approved, "state_ok": in_state, "ready_to_execute": approved and in_state}
    if not res["ready_to_execute"]:
        res["why_not"] = ("not approved yet (approval=%s)" % r.get("approval")) if not approved else "state is %s, needs Scheduled or Implement" % r.get("state")
    return {"ok": True, "change": res}


@_safe
def get_cmdb_ci(name):
    rows = _query("cmdb_ci", "name=%s" % _q(name), "name,sys_class_name,ip_address,os,operational_status,install_status,support_group,owned_by,environment,u_matrix_instance", 1)
    if not rows or not rows[0]:
        return {"ok": False, "error": "CI '%s' not found in the CMDB" % name}
    return {"ok": True, "ci": rows[0]}


@_safe
def search_kb(query=None, limit=5):
    t = _q(query)
    if not t:
        return {"ok": False, "needs_info": ["query"], "ask": "What should I look up in the knowledge base?"}
    rows = _query("kb_knowledge", "workflow_state=published^short_descriptionLIKE%s^ORtextLIKE%s" % (t, t),
                  "number,short_description,kb_knowledge_base,sys_updated_on", min(int(limit), 10))
    return {"ok": True, "articles": [r for r in rows if r]}


@_safe
def get_sla(number):
    _, r = _by_number(number)
    rows = _query("task_sla", "task=%s" % r["sys_id"], "sla,stage,has_breached,business_time_left,percentage", 10)
    return {"ok": True, "number": number, "slas": [x for x in rows if x]}


_UPDATABLE = {"priority", "urgency", "impact", "short_description", "category", "risk"}


@_safe
def update_ticket(number, fields=None, assignment_group=None, assigned_to=None, note=None):
    """Change a limited set of fields. State changes go through the dedicated resolve/close tools."""
    table, r = _by_number(number)
    fields = fields or {}
    bad = sorted(set(fields) - _UPDATABLE)
    if bad:
        return {"ok": False, "error": "these fields cannot be changed here: %s. Allowed: %s" % (", ".join(bad), ", ".join(sorted(_UPDATABLE)))}
    body = {k: (_clean(v, 160) if k == "short_description" else str(v)) for k, v in fields.items()}
    if assignment_group:
        gid = _group_id(assignment_group)
        if not gid:
            return {"ok": False, "error": "group %s not found" % assignment_group}
        body["assignment_group"] = gid
    if assigned_to:
        uid = _user_id(assigned_to)
        if not uid:
            return {"ok": False, "error": "user %s not found" % assigned_to}
        body["assigned_to"] = uid
    if not body:
        return {"ok": False, "error": "nothing to change"}
    if note:
        body["work_notes"] = _clean(note)
    _sn("PATCH", "/api/now/table/%s/%s" % (table, r["sys_id"]), body)
    return {"ok": True, "number": number, "updated": sorted(k for k in body if k != "work_notes")}


@_safe
def close_change(number, close_code, close_notes):
    """Close a change after implementation. close_code: successful, successful_with_issues or unsuccessful."""
    if close_code not in ("successful", "successful_with_issues", "unsuccessful"):
        return {"ok": False, "error": "close_code must be successful, successful_with_issues or unsuccessful"}
    if mode.incident_mode() and str(number).startswith("INC"):
        _, r = _by_number(number)
        note = "Planned work closed as %s. %s" % (close_code, _clean(close_notes))
        _sn("PATCH", "/api/now/table/incident/" + r["sys_id"], {"state": "6", "close_code": os.environ.get("CLOSE_CODE", "Solved (Permanently)"), "close_notes": note})
        return {"ok": True, "number": number, "state": "Resolved", "close_code": close_code}
    if not str(number).startswith("CHG"):
        return {"ok": False, "error": "close_change only works on CHG numbers"}
    _, r = _by_number(number)
    code = {"successful": "successful", "successful_with_issues": "successful_issues", "unsuccessful": "unsuccessful"}[close_code]
    _sn("PATCH", "/api/now/table/change_request/" + r["sys_id"], {"state": "3", "close_code": code, "close_notes": _clean(close_notes)})
    return {"ok": True, "number": number, "state": "Closed", "close_code": close_code}


@_safe
def create_problem(short_description=None, description=None, ci=None, related_incident=None, number=None):
    """Open a problem record for a repeat or root-cause investigation, and link the incident to it.
    `number` is the authorising ticket the engineer gave; an INC number is used as the incident to link."""
    if not related_incident and str(number or "").startswith("INC"):
        related_incident = number
    need = [n for n, v in (("short_description", short_description), ("description", description)) if not v]
    if need:
        return {"ok": False, "needs_info": need, "ask": "A problem needs a one-line summary and a description of the pattern."}
    body = {"short_description": short_description[:160], "description": _clean(description)}
    if ci:
        cid = _ci_id(ci)
        if not cid:
            return {"ok": False, "error": "CI '%s' not found in the CMDB" % ci}
        body["cmdb_ci"] = cid
    g = _group_id(os.environ.get("SN_AI_GROUP", "MATRIX-AI-L1"))
    if g:
        body["assignment_group"] = g
    p = _sn("POST", "/api/now/table/problem", body)
    if related_incident:
        _, inc = _by_number(related_incident)
        _sn("PATCH", "/api/now/table/incident/" + inc["sys_id"], {"problem_id": p["sys_id"]})
    return {"ok": True, "number": p["number"], "sys_id": p["sys_id"], "linked_incident": related_incident}


@_safe
def link_ticket(number, to_number):
    """Link an incident to a change (rfc field) or to a problem (problem_id field)."""
    if not str(number).startswith("INC"):
        return {"ok": False, "error": "number must be an INC (incidents are the only tickets that can be linked here)"}
    if str(to_number).startswith("CHG"):
        field = "rfc"
    elif str(to_number).startswith("PRB"):
        field = "problem_id"
    else:
        return {"ok": False, "error": "to_number must be a CHG or PRB number"}
    _, inc = _by_number(number)
    if field == "rfc":
        _, target = _by_number(to_number)
    else:
        rows = _query("problem", "number=%s" % _q(to_number), "sys_id", 1)
        if not rows or not rows[0]:
            return {"ok": False, "error": "%s not found" % to_number}
        target = rows[0]
    _sn("PATCH", "/api/now/table/incident/" + inc["sys_id"], {field: target["sys_id"]})
    return {"ok": True, "number": number, "linked_to": to_number}


@_safe
def attach_evidence(number, file_name, text):
    """Attach command output or logs as a text file. Secrets are masked first."""
    table, r = _by_number(number)
    base = os.environ.get("SN_BASE", "").strip().rstrip("/")
    user, pw = os.environ.get("SN_USER", ""), os.environ.get("SN_PASS", "")
    if not (base and user and pw):
        raise SNError("ServiceNow is not configured (SN_BASE / SN_USER / SN_PASS missing)")
    name = re.sub(r"[^A-Za-z0-9._-]", "_", file_name or "evidence.txt")[:80]
    url = base + "/api/now/attachment/file?" + urllib.parse.urlencode({"table_name": table, "table_sys_id": r["sys_id"], "file_name": name})
    req = urllib.request.Request(url, data=_clean(text, 200000).encode(), method="POST")
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode())
    req.add_header("Content-Type", "text/plain")
    req.add_header("Accept", "application/json")
    try:
        urllib.request.urlopen(req, timeout=30).read()
    except urllib.error.HTTPError as e:
        raise SNError("attachment failed (%s): %s" % (e.code, e.read()[:150].decode("utf-8", "ignore")))
    return {"ok": True, "number": number, "file": name}


@_safe
def update_cmdb_ci(name, install_status=None, operational_status=None, comments=None, number=None):
    """Update lifecycle fields of a CI, for example retire it after decommission. `number` is the authorising change."""
    inst = {"installed": "1", "in_maintenance": "3", "retired": "7"}
    oper = {"operational": "1", "non_operational": "2", "retired": "6"}
    body = {}
    if install_status:
        if install_status not in inst:
            return {"ok": False, "error": "install_status must be one of " + ", ".join(inst)}
        body["install_status"] = inst[install_status]
    if operational_status:
        if operational_status not in oper:
            return {"ok": False, "error": "operational_status must be one of " + ", ".join(oper)}
        body["operational_status"] = oper[operational_status]
    if comments:
        body["comments"] = _clean(comments)
    if not body:
        return {"ok": False, "error": "nothing to change"}
    cid = _ci_id(name)
    if not cid:
        return {"ok": False, "error": "CI '%s' not found in the CMDB" % name}
    _sn("PATCH", "/api/now/table/cmdb_ci/" + cid, body)
    return {"ok": True, "ci": name, "updated": sorted(body)}


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

_NUM = {"type": "string", "description": "Ticket number, e.g. INC0010001 or CHG0030012"}
TOOL_SPECS += [
    {"name": "snow_search_tickets",
     "description": "Search tickets by words in the summary and/or a CI name. Use it to find duplicates or related incidents and changes.",
     "input_schema": {"type": "object", "properties": {"text": _STR, "ci": _STR,
                      "table": {"type": "string", "enum": ["incident", "change_request", "problem", "sc_task"]},
                      "only_open": {"type": "boolean"}, "limit": {"type": "integer"}}, "required": []}},
    {"name": "snow_check_change_approval",
     "description": "Check whether a change (CHG) is approved, in Scheduled/Implement state and inside its window. Use before any planned work.",
     "input_schema": {"type": "object", "properties": {"number": _NUM}, "required": ["number"]}},
    {"name": "snow_get_cmdb_ci",
     "description": "Read a CI from the CMDB: class, IP, OS, status, owner and support group.",
     "input_schema": {"type": "object", "properties": {"name": _STR}, "required": ["name"]}},
    {"name": "snow_search_kb",
     "description": "Search published ServiceNow knowledge articles.",
     "input_schema": {"type": "object", "properties": {"query": _STR, "limit": {"type": "integer"}}, "required": ["query"]}},
    {"name": "snow_get_sla",
     "description": "Read SLA stage, time left and breach flag for a ticket.",
     "input_schema": {"type": "object", "properties": {"number": _NUM}, "required": ["number"]}},
    {"name": "snow_update_ticket",
     "description": "Change priority, urgency, impact, category, risk, summary, assignment group or assignee on a ticket. Needs engineer confirmation.",
     "input_schema": {"type": "object", "properties": {"number": _NUM, "fields": {"type": "object"}, "assignment_group": _STR,
                      "assigned_to": _STR, "note": _STR}, "required": ["number"]}},
    {"name": "snow_close_change",
     "description": "Close a change after implementation with a close code (successful, successful_with_issues, unsuccessful) and notes. Needs engineer confirmation.",
     "input_schema": {"type": "object", "properties": {"number": _NUM,
                      "close_code": {"type": "string", "enum": ["successful", "successful_with_issues", "unsuccessful"]},
                      "close_notes": _STR}, "required": ["number", "close_code", "close_notes"]}},
    {"name": "snow_create_problem",
     "description": "Open a problem record for a repeat or root-cause investigation and optionally link an incident. Needs engineer confirmation.",
     "input_schema": {"type": "object", "properties": {"short_description": _STR, "description": _STR, "ci": _STR,
                      "related_incident": _STR, "number": _NUM}, "required": ["short_description", "description", "number"]}},
    {"name": "snow_link_ticket",
     "description": "Link an incident to a change (CHG) or a problem (PRB). Needs engineer confirmation.",
     "input_schema": {"type": "object", "properties": {"number": _NUM, "to_number": _NUM}, "required": ["number", "to_number"]}},
    {"name": "snow_attach_evidence",
     "description": "Attach command output or logs to a ticket as a text file. Secrets are masked. Needs engineer confirmation.",
     "input_schema": {"type": "object", "properties": {"number": _NUM, "file_name": _STR, "text": _STR}, "required": ["number", "text"]}},
    {"name": "snow_update_cmdb_ci",
     "description": "Update a CI's install_status (installed, in_maintenance, retired) or operational_status (operational, non_operational, retired), for example after decommission. Needs engineer confirmation.",
     "input_schema": {"type": "object", "properties": {"name": _STR, "install_status": _STR, "operational_status": _STR,
                      "comments": _STR, "number": _NUM}, "required": ["name", "number"]}},
]

HANDLERS = {"snow_create_incident": create_incident, "snow_create_change": create_change,
            "snow_create_sr_task": create_sr_task, "snow_add_work_note": add_work_note,
            "snow_get_ticket": get_ticket, "snow_resolve_incident": resolve_incident,
            "snow_escalate": escalate_ticket,
            "snow_search_tickets": search_tickets, "snow_check_change_approval": check_change_approval,
            "snow_get_cmdb_ci": get_cmdb_ci, "snow_search_kb": search_kb, "snow_get_sla": get_sla,
            "snow_update_ticket": update_ticket, "snow_close_change": close_change,
            "snow_create_problem": create_problem, "snow_link_ticket": link_ticket,
            "snow_attach_evidence": attach_evidence, "snow_update_cmdb_ci": update_cmdb_ci}


def register(add_tool):
    """add_tool(name, description, input_schema, handler) is whatever your Lambda uses to register a tool."""
    for spec in TOOL_SPECS:
        add_tool(spec["name"], spec["description"], spec["input_schema"], HANDLERS[spec["name"]])
