"""
matrix_projects_cost.py - multi-project registry, chat history, and cost tracking.

DynamoDB tables (create all three, on-demand billing):
  matrix-projects   PK: project_id
  matrix-sessions   PK: user_id,  SK: session_id        (chat history)
  matrix-usage      PK: project_id, SK: ts_id           (LLM token usage)

Example item in matrix-projects:
{
  "project_id": "payments",
  "name": "Payments Platform",
  "environment": "dev",
  "executor_role_arn": "arn:aws:iam::111111111111:role/matrix-executor-dev",   # can be another account
  "snow_assignment_group": "Payments-L2",
  "allowed_instance_types": ["t3.micro", "t3.small", "t3.medium"],
  "subnet_id": "subnet-...", "security_group_id": "sg-...", "instance_profile": "matrix-instance-profile-dev",
  "members": {"alice": "L3", "bob": "L2"}
}
"""
import os, time, uuid, datetime
from decimal import Decimal
import boto3

REGION = os.environ.get("AWS_REGION", "ap-southeast-2")
ddb = boto3.resource("dynamodb", region_name=REGION)

# ---------- projects ----------
def get_project(project_id, user):
    item = ddb.Table("matrix-projects").get_item(Key={"project_id": project_id}).get("Item")
    if not item:
        raise PermissionError("unknown project")
    role = item.get("members", {}).get(user)
    if not role:
        raise PermissionError(f"{user} is not a member of {project_id}")
    item["user_role"] = role
    return item

def list_projects(user):
    items = ddb.Table("matrix-projects").scan()["Items"]
    return [{"project_id": i["project_id"], "name": i["name"], "environment": i["environment"]}
            for i in items if user in i.get("members", {})]

# In matrix_guardrails.py: replace the module-level ENV / EXECUTOR_ROLE_ARN / CATALOG / SUBNET_ID etc.
# with values from get_project(...) passed into execute() and deploy_ec2(), and add a
# {"Key": "project", "Value": project_id} tag to every launched resource.

# ---------- chat history (sidebar + New chat) ----------
def new_session(user, project_id, title="New chat"):
    sid = uuid.uuid4().hex[:12]
    ddb.Table("matrix-sessions").put_item(Item={
        "user_id": user, "session_id": sid, "project_id": project_id, "title": title,
        "created": int(time.time()), "messages": []})
    return sid

def list_sessions(user, project_id=None):
    rows = ddb.Table("matrix-sessions").query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key("user_id").eq(user))["Items"]
    rows = [r for r in rows if not project_id or r["project_id"] == project_id]
    return sorted([{"session_id": r["session_id"], "title": r["title"], "created": int(r["created"])} for r in rows],
                  key=lambda r: r["created"], reverse=True)

def get_session(user, session_id):
    return ddb.Table("matrix-sessions").get_item(Key={"user_id": user, "session_id": session_id}).get("Item")

def append_message(user, session_id, role, text, image_s3_key=None):
    msg = {"role": role, "text": text[:8000], "ts": int(time.time())}
    if image_s3_key: msg["image"] = image_s3_key
    ddb.Table("matrix-sessions").update_item(
        Key={"user_id": user, "session_id": session_id},
        UpdateExpression="SET messages = list_append(if_not_exists(messages, :e), :m)",
        ExpressionAttributeValues={":e": [], ":m": [msg]})

# ---------- LLM usage cost ----------
# Set your model's real prices (USD per 1M tokens). Groq free tier = 0.
PRICE_IN = Decimal(os.environ.get("LLM_PRICE_IN_PER_M", "0"))
PRICE_OUT = Decimal(os.environ.get("LLM_PRICE_OUT_PER_M", "0"))

def log_llm_usage(project_id, ticket, tokens_in, tokens_out, model):
    cost = (Decimal(tokens_in) * PRICE_IN + Decimal(tokens_out) * PRICE_OUT) / Decimal(1_000_000)
    ddb.Table("matrix-usage").put_item(Item={
        "project_id": project_id, "ts_id": f"{int(time.time()*1000)}-{uuid.uuid4().hex[:6]}",
        "day": datetime.date.today().isoformat(), "ticket": ticket or "-", "model": model,
        "tokens_in": tokens_in, "tokens_out": tokens_out, "cost_usd": cost})
# Call log_llm_usage() after every LLM response using the usage numbers the API returns.

def llm_cost_summary(project_id, days=30):
    rows = ddb.Table("matrix-usage").query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key("project_id").eq(project_id))["Items"]
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    rows = [r for r in rows if r["day"] >= cutoff]
    by_day, by_ticket = {}, {}
    for r in rows:
        by_day[r["day"]] = by_day.get(r["day"], 0) + float(r["cost_usd"])
        by_ticket[r["ticket"]] = by_ticket.get(r["ticket"], 0) + float(r["cost_usd"])
    return {"total_usd": round(sum(by_day.values()), 4),
            "tokens": sum(int(r["tokens_in"]) + int(r["tokens_out"]) for r in rows),
            "by_day": dict(sorted(by_day.items())),
            "top_tickets": sorted(by_ticket.items(), key=lambda x: -x[1])[:5]}

# ---------- AWS resource cost ----------
# Needs: Lambda role gets ce:GetCostAndUsage; in Billing > Cost allocation tags, ACTIVATE the tags
# "project" and "environment" (data appears about 24h after activation). Cost Explorer calls cost $0.01 each,
# so cache the result (e.g. 6 hours) in DynamoDB or memory.
_cache = {}
def aws_cost_summary(project_id, days=30):
    key = (project_id, days)
    if key in _cache and time.time() - _cache[key][0] < 6 * 3600:
        return _cache[key][1]
    ce = boto3.client("ce", region_name="us-east-1")
    end = datetime.date.today(); start = end - datetime.timedelta(days=days)
    flt = {"Tags": {"Key": "project", "Values": [project_id]}}
    daily = ce.get_cost_and_usage(TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
                                  Granularity="DAILY", Metrics=["UnblendedCost"], Filter=flt)
    by_svc = ce.get_cost_and_usage(TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
                                   Granularity="MONTHLY", Metrics=["UnblendedCost"], Filter=flt,
                                   GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}])
    by_day = {d["TimePeriod"]["Start"]: round(float(d["Total"]["UnblendedCost"]["Amount"]), 2)
              for d in daily["ResultsByTime"]}
    svc = {}
    for m in by_svc["ResultsByTime"]:
        for g in m["Groups"]:
            svc[g["Keys"][0]] = svc.get(g["Keys"][0], 0) + float(g["Metrics"]["UnblendedCost"]["Amount"])
    out = {"total_usd": round(sum(by_day.values()), 2), "by_day": by_day,
           "top_services": sorted(((k, round(v, 2)) for k, v in svc.items() if v >= 0.01), key=lambda x: -x[1])[:6]}
    _cache[key] = (time.time(), out)
    return out

def cost_page_data(project_id, days=30):
    """One call for the traceability page: two cards + 'cost per resolved ticket'."""
    a, l = aws_cost_summary(project_id, days), llm_cost_summary(project_id, days)
    return {"aws": a, "llm": l, "combined_usd": round(a["total_usd"] + l["total_usd"], 2)}
