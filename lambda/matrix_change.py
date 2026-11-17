"""MATRIX change-request layer. Add AFTER autonomy.install(g) in lambda_function.py:

    import matrix_change
    matrix_change.install(g)

What it does
  - Adds the tool create_change_request. Planned work (migration, new server deployment, decommission,
    patching, resize, other planned change) gets a ServiceNow CHANGE with implementation, backout and
    test plans written by the agent. The engineer is NOT asked for an error log or plans.
  - Adds a guard on create_incident_ticket: if the request is planned work, it is refused and the model is
    told to call create_change_request instead. Real faults (service down, errors, alarms) still go through
    the original incident flow in autonomy.py, which still asks for the error log.
  - Tells the chat model: for planned work create the change yourself and pass its CHG number as `number`;
    never ask the engineer for a change number, and never reuse a closed incident.

Extra environment variables (all optional)
  CHANGE_GROUP    assignment group for new changes (default: same as L1_GROUP, MATRIX-AI-L1)
  CHANGE_TYPE     normal | standard | emergency (default normal)
  CHANGE_HOURS    length of the default change window in hours (default 4)
"""
import datetime
import os
import re

import aiops as AI

G = {}
CHANGE_GROUP = os.environ.get('CHANGE_GROUP', os.environ.get('L1_GROUP', 'MATRIX-AI-L1'))
CHANGE_TYPE = os.environ.get('CHANGE_TYPE', 'normal')
CHANGE_HOURS = int(os.environ.get('CHANGE_HOURS', '4'))

# ---------------------------------------------------------------- classification
PLANNED = {
    'migration': r'\b(migrat\w*|relocat\w*|move (the )?(server|instance|vm)|another (az|availability zone)|different (az|availability zone)|az to az)\b',
    'deployment': r'\b(deploy\w*|provision\w*|new server|new instance|build (a |the )?server|spin up|launch (a |the )?(server|instance))\b',
    'decommission': r'\b(decommission\w*|retire (the )?(server|instance)|terminate (the )?(server|instance)|shut ?down permanently|remove (the )?server)\b',
    'patching': r'\b(patch\w*|os update|security update|upgrade (the )?(os|kernel|server))\b',
    'resize': r'\b(resize|change (the )?instance type|scale (up|down) (the )?(server|instance))\b',
}
FAULT = r'\b(fail\w*|error\w*|crash\w*|outage|is down|went down|not working|unresponsive|unreachable|exception|timed? ?out)\b'


def planned_kind(text):
    """Return migration/deployment/decommission/patching/resize, or '' when it looks like a fault or is unclear."""
    t = str(text or '').lower()
    if re.search(FAULT, t):
        return ''
    for kind, rx in PLANNED.items():
        if re.search(rx, t):
            return kind
    return ''


# ---------------------------------------------------------------- plan templates
def _plans(kind, host, details):
    d = (' Details: ' + details) if details else ''
    if kind == 'migration':
        return (
            '1. cmdb_lookup and health_check on %s. 2. Create an AMI of %s (migrate_create_image). 3. Wait until job_status shows the image available. '
            '4. Launch a clone in the target AZ in the same VPC (migrate_launch). 5. health_check on the new server and compare latency and service state. '
            '6. Engineer verifies; the original server is left running until verified.%s' % (host, host, d),
            'The original server is untouched. Terminate the clone and delete the AMI, then continue on the original in the current AZ.',
            'health_check on the new server is clean, services are active, network RTT and application response time are within threshold for the test period.')
    if kind == 'deployment':
        return (
            '1. ops_catalog to confirm the allowed module and instance type. 2. terraform_plan and review the result. 3. terraform_apply (deploy_server) after approval. '
            '4. health_check on the new server. 5. Add the server to the CMDB.%s' % d,
            'Run terraform destroy for the module (or terminate the new instance). No existing server is touched.',
            'New instance is running, status checks pass, SSM reachable, health_check clean, CMDB record present.')
    if kind == 'decommission':
        return (
            '1. cmdb_lookup for owner, environment and dependencies. 2. Create a backup AMI of %s (migrate_create_image). 3. Stop the instance (do not terminate). '
            '4. Keep it stopped for the retention period, then an L2 engineer terminates it and removes the CMDB record.%s' % (host, d),
            'Start the stopped instance, or launch a new one from the backup AMI.',
            'Backup AMI is available, no dependent service raised an alarm after the stop, owner confirmed.')
    if kind == 'patching':
        return (
            '1. patch_scan on %s and review the missing patches. 2. Create a backup AMI (migrate_create_image) for non-dev servers. 3. patch_install (reboot only if needed). '
            '4. job_status until complete. 5. health_check.%s' % (host, d),
            'Restore from the backup AMI, or uninstall the affected package through SSM.',
            'patch_scan shows no critical or important patches missing, health_check clean, services active after reboot.')
    if kind == 'resize':
        return (
            '1. health_check on %s. 2. Create a backup AMI. 3. Launch a clone with the new instance type from the allowed list (migrate_launch). 4. health_check on the clone.%s' % (host, d),
            'Terminate the clone and keep the original instance type.',
            'Clone is healthy on the new type and performance is within threshold.')
    return (
        'Executed by MATRIX AI using the approved tools, each step confirmed by an engineer.%s' % d,
        'Revert the change using the pre-change backup (AMI or configuration), then verify with health_check.',
        'Run health_check after the change and confirm services and alarms are normal.')


def _now():
    return datetime.datetime.utcnow().replace(microsecond=0)


def _fmt(dt):
    return dt.strftime('%Y-%m-%d %H:%M:%S')


# ---------------------------------------------------------------- tool
def create_change_request(a, u):
    ci = str(a.get('ci', '')).strip()
    short = str(a.get('short_description', '')).strip()
    kind = str(a.get('kind', '')).strip().lower()
    details = str(a.get('details', '')).strip()
    if kind not in list(PLANNED) + ['other']:
        kind = planned_kind(short + ' ' + details) or 'other'
    if not ci:
        return 'NOT CREATED. Ask the engineer only for the server (CI) name.'
    if len(short) < 5:
        short = '%s of %s' % (kind.capitalize(), ci)

    inst = G['need_instance']({'host': ci})
    host = inst['host']
    env = AI._env(inst['id'])
    risk = '2' if env in ('prod', 'production') else '3'

    cr = G['sn']('GET', 'cmdb_ci_server', {'sysparm_query': 'name=' + host, 'sysparm_limit': '1', 'sysparm_fields': 'sys_id'}) or []
    ci_id = G['raw'](cr[0]['sys_id']) if cr else ''

    # reuse an open change for the same server and kind instead of creating duplicates
    if ci_id:
        dup = G['sn']('GET', 'change_request', {'sysparm_query': 'active=true^cmdb_ci=%s^short_descriptionLIKE%s' % (ci_id, kind),
                                                'sysparm_limit': '1', 'sysparm_fields': 'number,sys_id'}) or []
        if dup:
            n = G['raw'](dup[0]['number'])
            return 'An open %s change already exists for %s: %s. Use %s as the number for the next steps.' % (kind, host, n, n)

    impl, backout, test = _plans(kind, host, details)
    start = str(a.get('start_date', '')).strip()
    end = str(a.get('end_date', '')).strip()
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', start):
        start = _fmt(_now())
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', end):
        end = _fmt(datetime.datetime.strptime(start, '%Y-%m-%d %H:%M:%S') + datetime.timedelta(hours=CHANGE_HOURS))

    why = str(a.get('justification', '')).strip() or details or 'Requested by %s through the MATRIX console.' % u.get('name', 'an engineer')
    ctype = str(a.get('change_type', '')).strip().lower()
    body = {
        'type': ctype if ctype in ('normal', 'standard', 'emergency') else CHANGE_TYPE,
        'short_description': ('[MATRIX] ' + short)[:160],
        'description': ('%s\n\nServer: %s (environment: %s)\nRequested by: %s via MATRIX chat' % (details or short, host, env, u.get('name', '')))[:3900],
        'justification': why[:1000],
        'implementation_plan': impl[:3900],
        'backout_plan': backout[:1900],
        'test_plan': test[:1900],
        'risk': risk,
        'start_date': start,
        'end_date': end,
    }
    if ci_id:
        body['cmdb_ci'] = ci_id
    gid = G['_group_id'](CHANGE_GROUP) if '_group_id' in G else ''
    if gid:
        body['assignment_group'] = gid

    r = G['sn']('POST', 'change_request', body=body)
    number = G['raw'](r['number'])
    G['add_note'](G['raw'](r['sys_id']), '[MATRIX] %s change created from chat by %s. Plans generated by MATRIX AI. Window %s to %s UTC.' % (kind, u.get('name', ''), start, end))
    return ('Created change %s (%s, %s) for %s. Window %s to %s UTC. '
            'Use %s as the `number` for the follow-up steps (image, launch, patch, playbook, deploy). '
            'A normal change may still need approval in ServiceNow.' % (number, kind, env, host, start, end, number))


# ---------------------------------------------------------------- tool narrowing
# console_api sends every tool (59 here, roughly 6k+ tokens) on every chat call. Small or fallback models then
# miss tools or hit rate limits. This sends only the tools the conversation is about. Tools from modules not
# listed here (awsops, metrics, sre, cost) are always kept. Set NARROW_TOOLS=0 to turn it off.
NARROW = os.environ.get('NARROW_TOOLS', '1') != '0'
CORE = {'create_change_request', 'create_incident_ticket', 'cmdb_lookup', 'kb_search', 'kb_read', 'ops_catalog', 'job_status',
        'list_servers', 'server_info', 'list_incidents', 'incident_timeline', 'search_incidents', 'health_check'}
GROUPS = [
    (r'migrat|\baz\b|availability zone|\bimage\b|\bami\b|clone|launch|relocat|\bdata\b|\bsync\b|decommission|resize', {'migrate_create_image', 'migrate_launch', 'data_sync'}),
    (r'patch|update|upgrade|decommission', {'patch_scan', 'patch_install'}),
    (r'deploy|provision|terraform|new server|infra|build', {'terraform_plan', 'terraform_apply', 'deploy_server'}),
    (r'playbook|ansible|configur', {'playbook_check', 'run_playbook'}),
    (r'cpu|disk|memory|service|restart|start|stop|kill|process|\blogs?\b|alarm|latency|slow|down|error|fail|health|nginx|httpd|crond',
     {'top_cpu_processes', 'disk_usage', 'check_alarms', 'service_status', 'restart_service', 'start_service', 'stop_service', 'kill_process', 'clear_old_logs'}),
    (r'approve|reject|assign|resolve|raise|incident|inc\d|ticket|chg\d|change', {'assign_to_me', 'approve_remediation', 'reject_remediation', 'resolve_incident', 'raise_incident'}),
]
KNOWN = set(CORE).union(*[s for _, s in GROUPS])


def _select(all_tools, text):
    t = str(text or '').lower()
    keep, hit = set(CORE), False
    for rx, names in GROUPS:
        if re.search(rx, t):
            keep |= names
            hit = True
    if not hit:
        return list(all_tools)
    return [x for x in all_tools if x['function']['name'] in keep or x['function']['name'] not in KNOWN]


AZ_RX = re.compile(r'[a-z]{2}-[a-z]+-\d[a-z]?')


def _precreate(q, u, user_text):
    """Planned work on a real server: create (or reuse) the change in code, so the model never has to decide to call a tool.
    The CHG number is handed to the model through the chat context, which console_api adds to the system prompt."""
    try:
        kind = planned_kind(user_text)
        if not kind:
            return q
        host = ''
        for c in [x for x in re.findall(r'[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+', user_text) if not AZ_RX.fullmatch(x.lower())][:4]:
            if G['find_instance'](c):
                host = c
                break
        if not host:
            return q
        res = create_change_request({'ci': host, 'kind': kind, 'short_description': '%s of %s' % (kind.capitalize(), host), 'details': user_text[:400]}, u)
        m = re.search(r'CHG\d+', res)
        if not m:
            print('matrix_change: precreate gave no CHG number: %s' % res[:200])
            return q
        note = ('Change %s already exists for %s (%s). Use %s as number for every tool. Do not ask for a change number or error log.' % (m.group(0), host, kind, m.group(0)))
        print('matrix_change: precreated or reused %s for %s' % (m.group(0), host))
        return dict(q, ctx=(note + ' ' + str(q.get('ctx', ''))).strip())
    except Exception as e:
        print('matrix_change: precreate failed: %s' % str(e)[:200])
        return q


def _wrap_chat(g):
    import json as _json
    orig = g['ACTIONS'].get('chat')
    if not (NARROW and orig):
        return

    def chat(q, u):
        full = list(g['TOOLS'])
        try:
            msgs = _json.loads(q.get('messages') or '[]')
            text = ' '.join(str(m.get('content', ''))[:600] for m in msgs[-4:] if isinstance(m, dict))
            user_text = ' | '.join(str(m.get('content', ''))[:300] for m in msgs[-4:] if isinstance(m, dict) and m.get('role') == 'user')
        except Exception:
            text, user_text = '', ''
        q = _precreate(q, u, user_text)
        chosen = _select(full, text)
        g['TOOLS'][:] = chosen
        print('matrix_change: chat sends %d of %d tools' % (len(chosen), len(full)))
        try:
            return orig(q, u)
        finally:
            g['TOOLS'][:] = full
    g['ACTIONS']['chat'] = chat


# ---------------------------------------------------------------- install
def install(g):
    G.update(g)
    G['_group_id'] = g.get('_group_id') or _lookup_group
    fn = g['_fn']

    g['READ']['create_change_request'] = create_change_request
    g['TOOLS'].append(fn(
        'create_change_request',
        'Create a ServiceNow CHANGE REQUEST for planned work: server migration to another AZ, new server deployment, decommission, patching, resize. '
        'Only the server (CI) is needed from the engineer. Never ask for an error log, plans or a change number: this tool writes the implementation, '
        'backout and test plans itself. Call it first, then use the returned CHG number as `number` in migrate_create_image, migrate_launch, patch_install, '
        'run_playbook, terraform_apply and data_sync.',
        {'ci': 'Server name (CI)', 'kind': 'migration | deployment | decommission | patching | resize | other',
         'short_description': 'One-line summary, for example Migrate matrix-linux-01 to ap-southeast-2a',
         'details': 'Anything useful such as target AZ, new server name, size, reason', 'justification': 'Business reason (optional)',
         'change_type': 'normal | standard | emergency (default normal)',
         'start_date': 'YYYY-MM-DD HH:MM:SS UTC (default now)', 'end_date': 'YYYY-MM-DD HH:MM:SS UTC (default start + a few hours)'},
        opt=('kind', 'short_description', 'details', 'justification', 'change_type', 'start_date', 'end_date')))

    # load check: shows in CloudWatch at cold start and in the output of the ops_catalog tool
    print('matrix_change loaded: create_change_request registered, %d tools in total' % len(g['TOOLS']))
    orig_cat = g['READ'].get('ops_catalog')
    if orig_cat:
        g['READ']['ops_catalog'] = lambda a, u: str(orig_cat(a, u)) + '\nChange requests: create_change_request is available (matrix_change loaded).'

    # planned work must never become an incident that demands an error log
    orig_ticket = g['READ'].get('create_incident_ticket')
    if orig_ticket:
        def guarded_ticket(a, u):
            kind = planned_kind('%s %s' % (a.get('short_description', ''), a.get('details', '')))
            if kind:
                return ('NOT CREATED. This is planned work (%s). Planned work needs a change request, not an incident. '
                        'Call create_change_request now with the server name. Do not ask the engineer for an error log.' % kind)
            return orig_ticket(a, u)
        g['READ']['create_incident_ticket'] = guarded_ticket

    g['CHAT_SYSTEM'] += (
        " TICKET TYPE RULE (overrides earlier ticket and number instructions): "
        "Planned work (server migration, new server deployment, decommission, patching, resize, configuration change) is a CHANGE, not an incident. "
        "For planned work call create_change_request yourself, asking the engineer only for the server name if it is missing. "
        "Never ask the engineer for an error log, a screenshot, a plan or a change number for planned work, and never reuse a resolved or closed incident. "
        "After the change is created, pass its CHG number as `number` to the next tools. For non-production servers a number is not required but pass it anyway. "
        "Only real faults (service down, errors, alarms, outages, performance problems) are incidents: for those use create_incident_ticket and collect the CI, "
        "what is failing, and the error log text or a screenshot description first. "
        "There is no decommission tool: for a decommission create the change, take the backup image, then tell the engineer an L2 engineer must stop and terminate the server.")
    _wrap_chat(g)


def _lookup_group(name):
    r = G['sn']('GET', 'sys_user_group', {'sysparm_query': 'name=' + re.sub(r'[^\w .-]', '', name), 'sysparm_limit': '1', 'sysparm_fields': 'sys_id'}) or []
    return G['raw'](r[0]['sys_id']) if r else ''
