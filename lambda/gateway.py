"""MATRIX model gateway. Install it FIRST in lambda_function.py (before aiops) so tracing sees the model that really answered.

What it does for every LLM call (chat and autonomous agent):
  1. Sends only the tools that fit the request (about 10 to 15 instead of 35), which cuts tokens per call by more than half.
  2. On a rate limit (429) it waits if the wait is short, otherwise it cools that slot for a while and moves to the next one.
  3. On server errors or timeouts it does the same. All slots in the chain are tried before giving up.
  4. Small talk goes to LLM_SMALL_MODEL first (if set), so cheap questions use the cheap model.
Chain (in order): the primary (OPENAI_*), then LLM_EXTRA_MODELS (comma list, same provider and key),
then up to three standby slots. Slot 1 uses LLM_FALLBACK_URL / _KEY / _MODEL, slot 2 uses LLM_FALLBACK_URL_2 / _KEY_2 / _MODEL_2, slot 3 uses ..._3.
A standby slot needs a key and a model. If its URL is empty it uses the primary's URL (for example three API keys on the same provider).
Every slot is tracked separately, so a rate limit on one key does not stop the others, even when they use the same model name.
"""
import json, os, re, time, urllib.error, urllib.request
from urllib.parse import urlparse

CHAIN, SMALL, COOL = [], None, {}
HDR = {'Content-Type': 'application/json', 'User-Agent': 'matrix-console/1.0', 'Accept': 'application/json'}

GROUPS = {
    'core': ['kb_search', 'job_status', 'server_info', 'list_servers', 'aws_read'],
    'diag': ['health_check', 'top_cpu_processes', 'disk_usage', 'service_status', 'check_alarms'],
    'svc': ['restart_service', 'start_service', 'stop_service', 'kill_process', 'clear_old_logs'],
    'power': ['ec2_power'],
    'inc': ['list_incidents', 'incident_timeline', 'search_incidents', 'create_incident_ticket', 'assign_to_me', 'approve_remediation', 'reject_remediation', 'resolve_incident', 'raise_incident'],
    'aws': ['aws_read', 'aws_write'],
    'ops': ['patch_scan', 'patch_install', 'playbook_check', 'run_playbook', 'terraform_plan', 'terraform_apply', 'deploy_server', 'migrate_create_image', 'migrate_launch', 'data_sync', 'cmdb_lookup', 'ops_catalog', 'kb_read'],
    # tools from matrix_ops_install.py (matrix_ops_skills.py and the extra ServiceNow tools)
    'patch': ['patch_scan', 'patch_status', 'patch_install', 'snow_check_change_approval', 'snow_create_change', 'snow_add_work_note', 'snow_get_cmdb_ci'],
    'migrate': ['migration_assess', 'migration_replicate', 'migration_image_status', 'migration_copy_image', 'migration_launch', 'migration_validate',
                'migration_cutover', 'migration_rollback', 'snow_check_change_approval', 'snow_create_change', 'snow_add_work_note', 'snow_get_cmdb_ci'],
    'deploy': ['deployment_plan', 'deployment_apply', 'migration_validate', 'snow_check_change_approval', 'snow_create_change', 'snow_add_work_note', 'snow_get_cmdb_ci'],
    'decom': ['decommission_assess', 'decommission_snapshot', 'decommission_stop', 'decommission_terminate', 'migration_image_status', 'snow_check_change_approval',
              'snow_create_change', 'snow_add_work_note', 'snow_update_cmdb_ci', 'snow_close_change', 'snow_get_cmdb_ci'],
    'snow': ['snow_create_incident', 'snow_create_change', 'snow_create_sr_task', 'snow_add_work_note', 'snow_get_ticket', 'snow_escalate', 'snow_search_tickets',
             'snow_check_change_approval', 'snow_get_cmdb_ci', 'snow_search_kb', 'snow_get_sla', 'snow_update_ticket', 'snow_close_change', 'snow_create_problem',
             'snow_link_ticket', 'snow_attach_evidence', 'snow_update_cmdb_ci'],
}
KEYS = [
    ('power', r'\b(start|stop|reboot|restart server|shut ?down|power|boot)\b'),
    ('diag', r'(health|cpu|disk|memory|ram|alarm|process|status|check|slow|load)'),
    ('svc', r'(service|nginx|httpd|crond|restart|kill|logs?\b)'),
    ('inc', r'(incident|ticket|inc\d|approve|reject|resolve|assign|escalat|raise)'),
    ('aws', r'(s3|bucket|volume|snapshot|cost|cloudtrail|activity|report|rds|lambda|vpc|aws|size|decommission|restore|delete|create|tag)'),
    ('ops', r'(patch|deploy|migrat|terraform|playbook|ansible|sync|vcpu|provision|cmdb|runbook|sop|\bami\b|image|availability zone|ap-southeast|job)'),
    ('patch', r'(patch|security update|os update)'),
    ('migrate', r'(migrat|cutover|cut over|rollback|replicat|another (az|region)|move (the )?(server|instance))'),
    ('deploy', r'(deploy|provision|new (server|instance)|spin up|launch)'),
    ('decom', r'(decommission|retire|terminate|remove (the )?(server|instance)|shut ?down permanently)'),
    ('snow', r'(servicenow|snow|ticket|inc\d|chg\d|change request|problem|\bkb\b|knowledge|sla|\bci\b|cmdb|attach|link)'),
]


def select_tools(text, all_tools):
    names, matched = set(GROUPS['core']), []
    for grp, rx in KEYS:
        if re.search(rx, text):
            matched.append(grp); names.update(GROUPS[grp])
            if grp == 'power':
                names.update(GROUPS['diag'])
    if not matched:
        names.update(GROUPS['diag'] + GROUPS['inc'][:3])
    return [t for t in all_tools if t['function']['name'] in names], matched


def _wait(e, txt):
    h = e.headers.get('retry-after') if getattr(e, 'headers', None) else None
    if h:
        try:
            return float(h)
        except ValueError:
            pass
    m = re.search(r'try again in (?:(\d+)m)?\s*([\d.]+)(ms|s)', txt)
    if m:
        s = float(m.group(2)) / (1000 if m.group(3) == 'ms' else 1) + (60 * int(m.group(1)) if m.group(1) else 0)
        return s
    return 10.0


def post(cands, body, timeout=60):
    now = time.time()
    live = [c for c in cands if COOL.get(c['id'], 0) <= now] or sorted(cands, key=lambda c: COOL.get(c['id'], 0))[:1]
    errs, auth_failed = [], False
    for c in live:
        for attempt in (0, 1):
            try:
                req = urllib.request.Request(c['url'], data=json.dumps(dict(body, model=c['model'])).encode(), method='POST',
                                             headers=dict(HDR, Authorization='Bearer ' + c['key']))
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    res = json.loads(r.read())
                res.setdefault('model', c['model'])
                return res
            except urllib.error.HTTPError as e:
                txt = e.read()[:300].decode('utf8', 'ignore')
                if e.code == 429:
                    w = _wait(e, txt)
                    if attempt == 0 and w <= 5:
                        time.sleep(w + 0.5); continue
                    COOL[c['id']] = time.time() + min(max(w, 5), 90); errs.append('%s rate limited' % c['label']); break
                if e.code >= 500 or (e.code == 400 and 'tool' in txt.lower()):
                    COOL[c['id']] = time.time() + 30; errs.append('%s error %s' % (c['label'], e.code)); break
                if e.code in (401, 403):
                    # a bad or expired key on ONE slot must not stop the others: park it for 10 minutes and say which slot it was
                    COOL[c['id']] = time.time() + 600; errs.append('%s rejected its API key (HTTP %s)' % (c['label'], e.code)); auth_failed = True; break
                raise RuntimeError('LLM %s: %s' % (e.code, txt))
            except Exception as e:
                COOL[c['id']] = time.time() + 20; errs.append('%s %s' % (c['label'], str(e)[:60])); break
    if auth_failed:
        raise RuntimeError('No model could answer (%s). Fix the key for the slot named above (Lambda environment variables).' % '; '.join(errs))
    raise RuntimeError('All models are busy or down (%s). Try again in a minute.' % '; '.join(errs))


def _slot(role, url, key, model):
    i = len(CHAIN)
    return {'id': 'slot%d' % i, 'role': role, 'url': url, 'key': key, 'model': model, 'label': '%s (%s #%d)' % (model, role, i)}


def a_gateway(q, u):
    """Replaces the metrics version so standby slots on the same provider still show as standby."""
    now = time.time()
    rows = [{'model': c['model'], 'provider': urlparse(c['url']).netloc, 'role': c['role'], 'cooling_s': max(0, int(COOL.get(c['id'], 0) - now))} for c in CHAIN]
    return {'ok': True, 'chain': rows, 'small_model': SMALL['model'] if SMALL else None, 'standby_configured': any(r['role'] == 'standby' for r in rows),
            'standby_count': sum(r['role'] == 'standby' for r in rows)}


def install(g):
    global SMALL
    url, key, model = g['OPENAI_URL'], g['OPENAI_KEY'], g['OPENAI_MODEL']
    CHAIN.clear(); COOL.clear()
    CHAIN.append(_slot('primary', url, key, model))
    for m in [x.strip() for x in os.environ.get('LLM_EXTRA_MODELS', '').split(',') if x.strip()]:
        CHAIN.append(_slot('extra', url, key, m))
    for sfx in ('', '_2', '_3'):
        fu, fk, fm = (os.environ.get('LLM_FALLBACK_%s%s' % (k, sfx), '').strip() for k in ('URL', 'KEY', 'MODEL'))
        if fk and fm:
            CHAIN.append(_slot('standby', fu or url, fk, fm))
    sm = os.environ.get('LLM_SMALL_MODEL', '').strip()
    SMALL = dict(_slot('small', url, key, sm), id='small') if sm else None

    def _openai(messages):
        users = [m.get('content') or '' for m in messages if m.get('role') == 'user']
        recent = [m.get('content') or '' for m in messages[-8:] if m.get('role') in ('user', 'assistant') and isinstance(m.get('content'), str)]
        text = ' '.join(recent).lower()[-1500:]
        tools, matched = select_tools(text, g['TOOLS'])
        simple = not matched and len(users[-1] if users else '') < 80
        cands = ([SMALL] if simple and SMALL else []) + CHAIN
        return post(cands, {'messages': messages, 'tools': tools})
    g['_openai'] = _openai
