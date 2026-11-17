"""MATRIX metrics for the Dashboard and Observability pages. Install last in lambda_function.py.

Actions added: dash (agent outcomes and human intervention), obs (latency, tokens, tools, models, trace list), gateway (model chain status).
Everything comes from data the platform already stores (DynamoDB traces + inbox events, ServiceNow incidents). Nothing is invented:
if a source is not connected the response says so.
"""
import json, re, time
from collections import Counter, defaultdict
from datetime import datetime
from urllib.parse import urlparse
from boto3.dynamodb.conditions import Key
import aiops as AI
import gateway as GW

G = {}


def _q(pk, limit):
    out, last = [], None
    while len(out) < limit:
        kw = {'KeyConditionExpression': Key('pk').eq(pk), 'ScanIndexForward': False, 'Limit': min(200, limit - len(out))}
        if last:
            kw['ExclusiveStartKey'] = last
        r = AI.ddb.query(**kw)
        out += r['Items']
        last = r.get('LastEvaluatedKey')
        if not last:
            break
    return AI._plain(out)


def _pct(vals, p):
    if not vals:
        return 0
    v = sorted(vals)
    return v[min(len(v) - 1, int(round(p / 100 * (len(v) - 1))))]


def _days(q):
    try:
        return max(1, min(30, int(q.get('days') or 7)))
    except ValueError:
        return 7


def _ts(item):
    return int(str(item['sk']).split('#')[0])


def _day(ms):
    return datetime.utcfromtimestamp(ms / 1000).strftime('%m-%d')


def a_obs(q, u):
    if not AI.ddb:
        return {'ok': False, 'error': 'TRACE_TABLE is not configured'}
    since = (time.time() - _days(q) * 86400) * 1000
    tr = [t for t in _q('TRACES', 400) if _ts(t) >= since]
    ms = [t.get('ms', 0) for t in tr if t.get('ms')]
    per_day = defaultdict(lambda: {'n': 0, 'err': 0, 'tok': 0})
    for t in tr:
        d = per_day[_day(_ts(t))]
        d['n'] += 1; d['err'] += t.get('status') == 'error'; d['tok'] += t.get('prompt_tokens', 0) + t.get('completion_tokens', 0)
    models, tools, llm_ms = defaultdict(lambda: {'calls': 0, 'in': 0, 'out': 0}), defaultdict(lambda: {'calls': 0, 'errors': 0, 'ms': 0}), []
    for t in tr:
        try:
            for name, v in json.loads(t.get('models') or '{}').items():
                m = models[name]; m['calls'] += v.get('calls', 0); m['in'] += v.get('in', 0); m['out'] += v.get('out', 0)
        except Exception:
            pass
    for t in tr[:25]:
        for e in _q(t['trace_id'], 100):
            try:
                d = json.loads(e.get('data', '{}'))
            except Exception:
                d = {}
            if e['kind'] == 'llm':
                llm_ms.append(e['ms'])
            elif e['kind'] == 'tool':
                s = tools[e['name']]; s['calls'] += 1; s['ms'] += e['ms']; s['errors'] += str(d.get('result', '')).startswith('Error')
    return {'ok': True, 'days': _days(q), 'summary': {
        'requests': len(tr), 'errors': sum(t.get('status') == 'error' for t in tr), 'p50': _pct(ms, 50), 'p95': _pct(ms, 95), 'p99': _pct(ms, 99),
        'prompt_tokens': sum(t.get('prompt_tokens', 0) for t in tr), 'completion_tokens': sum(t.get('completion_tokens', 0) for t in tr),
        'tool_calls': sum(t.get('tools', 0) for t in tr), 'llm_p95': _pct(llm_ms, 95)},
        'per_day': [dict(day=k, **v) for k, v in sorted(per_day.items())],
        'latency': [t.get('ms', 0) for t in reversed(tr[:60])],
        'models': [dict(model=k, **v) for k, v in models.items()],
        'tools': sorted([dict(tool=k, avg_ms=int(v['ms'] / max(v['calls'], 1)), **{x: v[x] for x in ('calls', 'errors')}) for k, v in tools.items()], key=lambda x: -x['calls']),
        'traces': [{k: t.get(k) for k in ('trace_id', 'sk', 'kind', 'user', 'prompt', 'status', 'ms', 'prompt_tokens', 'completion_tokens', 'tools')} for t in tr[:40]],
        'sampled_traces_for_detail': min(len(tr), 25)}


def a_dash(q, u):
    if not AI.ddb:
        return {'ok': False, 'error': 'TRACE_TABLE is not configured'}
    since = (time.time() - _days(q) * 86400) * 1000
    inbox = [i for i in _q('INBOX', 500) if _ts(i) >= since]
    traces = [t for t in _q('TRACES', 400) if _ts(t) >= since]
    kinds = Counter(i['kind'] for i in inbox)
    resolved, escalated, approvals = kinds['resolved'], kinds['escalation'], kinds['approval']
    handled = resolved + escalated
    per_day = defaultdict(lambda: {'resolved': 0, 'escalated': 0, 'approvals': 0})
    for i in inbox:
        k = {'resolved': 'resolved', 'escalation': 'escalated', 'approval': 'approvals'}.get(i['kind'])
        if k:
            per_day[_day(_ts(i))][k] += 1
    res = {'ok': True, 'days': _days(q), 'agent_runs': sum(t.get('kind') == 'agent' for t in traces), 'resolved': resolved, 'escalated': escalated, 'approvals': approvals,
           'auto_rate': round(resolved / handled * 100) if handled else None, 'human_rate': round(escalated / handled * 100) if handled else None,
           'per_day': [dict(day=k, **v) for k, v in sorted(per_day.items())],
           'recent': [{k: i.get(k) for k in ('kind', 'number', 'text', 'sk')} for i in inbox[:12]],
           'definitions': {'auto_rate': 'resolved by the agent and verified, divided by (resolved + escalated)', 'human_rate': 'escalated to a human, divided by (resolved + escalated)',
                           'approvals': 'times the agent asked a human to approve a fix (counted separately)'}}
    try:
        inc = G['a_list']({}, u)['incidents']
        res['incident_status'] = dict(Counter(i['status'] for i in inc))
        mins = []
        for i in inc:
            if i['status'] == 'resolved' and i.get('resolved_raw') and i.get('created_raw'):
                try:
                    f = '%Y-%m-%d %H:%M:%S'
                    mins.append((datetime.strptime(i['resolved_raw'], f) - datetime.strptime(i['created_raw'], f)).total_seconds() / 60)
                except ValueError:
                    pass
        res['mttr_min'] = round(sum(mins) / len(mins), 1) if mins else None
    except Exception as e:
        res['incident_error'] = 'ServiceNow not connected: ' + str(e)[:120]
    return res


def a_gateway(q, u):
    now = time.time(); first = GW.CHAIN[0]['url'] if GW.CHAIN else ''
    rows = [{'model': c['model'], 'provider': urlparse(c['url']).netloc, 'role': 'primary' if i == 0 else ('standby' if c['url'] != first else 'extra'),
             'cooling_s': max(0, int(GW.COOL.get(c['model'], 0) - now))} for i, c in enumerate(GW.CHAIN)]
    return {'ok': True, 'chain': rows, 'small_model': GW.SMALL['model'] if GW.SMALL else None, 'standby_configured': any(r['role'] == 'standby' for r in rows)}


def install(g):
    G.update(g)
    g['ACTIONS'].update({'obs': a_obs, 'dash': a_dash, 'gateway': a_gateway})
