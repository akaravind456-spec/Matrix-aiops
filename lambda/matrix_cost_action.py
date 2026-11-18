"""
matrix_cost_action.py - adds the 'cost' action that the console's Costs page calls.

Entry file (lambda_function.py), before learning.install(g):
    import matrix_cost_action
    matrix_cost_action.install(g)

Needs on the Lambda role: ce:GetCostAndUsage  (already in the matrix-tables-and-cost policy).
Cost Explorer must be enabled in the AWS account (Billing > Cost Explorer; first enable takes up to 24 hours).
Each Cost Explorer request costs about $0.01, so results are cached for an hour per period.
Optional env var COST_TAG_KEY (e.g. "project") + the request field 'project' limits cost to resources with that tag value.
"""
import datetime, os, time
import boto3

CACHE = {}
TTL = 3600


def install(g):
    ce = boto3.client("ce", region_name="us-east-1")

    def a_cost(q, u):
        try:
            days = min(max(int(q.get("days") or 7), 1), 90)
        except Exception:
            days = 7
        tag_key, tag_val = os.environ.get("COST_TAG_KEY", "").strip(), str(q.get("project", "")).strip()[:100]
        key = (days, tag_key, tag_val)
        hit = CACHE.get(key)
        if hit and time.time() - hit[0] < TTL:
            return hit[1]

        today = datetime.date.today()
        start, end = today - datetime.timedelta(days=days - 1), today + datetime.timedelta(days=1)  # End is exclusive
        # one query grouped by service AND charge type, so we can show the real usage cost (before credits and refunds)
        # and what is left to pay after them
        args = dict(TimePeriod={"Start": start.isoformat(), "End": end.isoformat()}, Granularity="DAILY",
                    Metrics=["UnblendedCost"], GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}, {"Type": "DIMENSION", "Key": "RECORD_TYPE"}])
        if tag_key and tag_val:
            args["Filter"] = {"Tags": {"Key": tag_key, "Values": [tag_val]}}
        daily, svc, token, net = {}, {}, None, 0.0
        try:
            while True:
                r = ce.get_cost_and_usage(**args, **({"NextPageToken": token} if token else {}))
                for day in r["ResultsByTime"]:
                    d = day["TimePeriod"]["Start"]
                    for grp in day["Groups"]:
                        v = float(grp["Metrics"]["UnblendedCost"]["Amount"])
                        net += v
                        if grp["Keys"][1] in ("Credit", "Refund"):
                            continue
                        daily[d] = daily.get(d, 0) + v
                        svc[grp["Keys"][0]] = svc.get(grp["Keys"][0], 0) + v
                token = r.get("NextPageToken")
                if not token:
                    break
        except Exception as e:
            msg = str(e)
            if "AccessDenied" in msg:
                msg = "The Lambda role needs ce:GetCostAndUsage."
            elif "not enabled" in msg.lower() or "DataUnavailable" in msg:
                msg = "Cost Explorer is not enabled for this account yet. Enable it in Billing, then try again in a day."
            return {"ok": False, "error": msg[:300]}

        # fill days with no cost so the chart has no gaps
        series = []
        d = start
        while d <= today:
            series.append({"d": d.isoformat(), "v": round(daily.get(d.isoformat(), 0), 4)})
            d += datetime.timedelta(days=1)
        top = sorted(((k, v) for k, v in svc.items() if abs(v) >= 0.0001), key=lambda x: -x[1])
        services = [{"name": k, "v": round(v, 4)} for k, v in top[:12]]
        rest = sum(v for _, v in top[12:])
        if abs(rest) >= 0.0001:
            services.append({"name": "Other services", "v": round(rest, 4)})
        gross = sum(daily.values())
        # total = usage cost before credits and refunds. net_total = what is left to pay after them.
        out = {"ok": True, "currency": "USD", "days": days, "total": round(gross, 4), "net_total": round(net, 4), "credits": round(net - gross, 4),
               "daily": series, "services": services, "service_count": len(svc)}
        CACHE[key] = (time.time(), out)
        return out

    g["ACTIONS"]["cost"] = a_cost
