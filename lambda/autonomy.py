"""MATRIX autonomy layer. Add AFTER the aiops lines at the end of your Lambda file:

    import aiops, autonomy
    aiops.install(globals())
    autonomy.install(globals())

Adds:
  - agent_run: LLM diagnoses an incident, chooses ONE fix from a fixed catalogue, applies it (or asks for approval), re-diagnoses, then resolves or escalates to L2
  - create_incident_ticket: refuses vague requests, asks for CI / description / error log, then creates the ticket for MATRIX AI and starts the agent
  - approvals and inbox actions for the chat UI (approval cards, L2 escalation notices)
  - health_check tool and deploy_server tool (vCPU / RAM / disk -> instance type -> Terraform module ec2-linux)

Extra environment variables:
  AGENT_KEY       long random secret; lets the alarm flow call agent_run (token "svc:<AGENT_KEY>")
  L1_GROUP        default MATRIX-AI-L1        L2_GROUP  default "L2 Cloud Engineers"
  AUTO_AFTER      default 3: after this many earlier auto-resolved incidents with the same alarm, the pattern counts as known and fixes run without approval
  FAMILIES        default m5,m6i,t3 (instance families deploy_server may pick, in preference order)
  MAX_VCPU / MAX_RAM_GB / MAX_DISK_GB   defaults 8 / 32 / 100
  DEPLOY_SUBNET, DEPLOY_SG, DEPLOY_PROFILE   network, security group and instance profile for new servers
Lambda timeout should be 300 seconds. The Lambda role also needs lambda:InvokeFunction on itself, ec2:DescribeInstanceTypes, ec2:DescribeInstanceStatus.
"""
import hmac, json, os, re, time, urllib.parse, urllib.request, uuid
import boto3
from boto3.dynamodb.conditions import Key
import aiops as AI

REGION = os.environ.get('AWS_REGION', 'ap-southeast-2')
AGENT_KEY = os.environ.get('AGENT_KEY', '').strip()
L1_GROUP = os.environ.get('L1_GROUP', 'MATRIX-AI-L1')
L2_GROUP = os.environ.get('L2_GROUP', 'L2 Cloud Engineers')
AUTO_AFTER = int(os.environ.get('AUTO_AFTER', '3'))
FAMILIES = [x.strip() for x in os.environ.get('FAMILIES', 'm5,m6i,t3').split(',') if x.strip()]
MAX_VCPU, MAX_RAM, MAX_DISK = (int(os.environ.get(k, d)) for k, d in (('MAX_VCPU', '8'), ('MAX_RAM_GB', '32'), ('MAX_DISK_GB', '100')))
DEPLOY = {k: os.environ.get(k, '').strip() for k in ('DEPLOY_SUBNET', 'DEPLOY_SG', 'DEPLOY_PROFILE')}
AGENT_U = {'u': 'matrix.ai', 'name': 'MATRIX AI', 'role': 'AGENT', 'snUser': ''}
TTL = 30 * 86400

lam = boto3.client('lambda', region_name=REGION)
ec2 = boto3.client('ec2', region_name=REGION)
G = {}


# ---------------- storage: approvals + inbox (same DynamoDB table as traces) ----------------
def _tbl():
    if not AI.ddb:
        raise RuntimeError('TRACE_TABLE is not configured')
    return AI.ddb


def inbox_add(kind, number, text):
    AI._put({'pk': 'INBOX', 'sk': '%013d#%s' % (int(time.time() * 1000), uuid.uuid4().hex[:6]), 'kind': kind, 'number': number,
             'text': str(text)[:800], 'ttl': int(time.time()) + TTL})


def a_inbox(q, u):
    r = _tbl().query(KeyConditionExpression=Key('pk').eq('INBOX'), ScanIndexForward=False, Limit=30)
    return {'ok': True, 'inbox': AI._plain([{k: v for k, v in i.items() if k not in ('pk', 'ttl')} for i in r['Items']])}


def a_approvals(q, u):
    r = _tbl().query(KeyConditionExpression=Key('pk').eq('APPROVALS'), ScanIndexForward=False, Limit=50)
    rows = [i for i in AI._plain(r['Items']) if i.get('status') == 'pending']
    return {'ok': True, 'approvals': [{k: i[k] for k in ('sk', 'number', 'host', 'summary', 'reason', 'evidence', 'created') if k in i} for i in rows]}


def a_approval_decide(q, u):
    if u.get('role') == 'AGENT':
        return {'ok': False, 'error': 'Only a human can decide an approval'}
    aid, ok = re.sub(r'[^0-9a-z#-]', '', str(q.get('id', ''))), q.get('decision') == 'approve'
    t = _tbl()
    item = t.get_item(Key={'pk': 'APPROVALS', 'sk': aid}).get('Item')
    if not item:
        return {'ok': False, 'error': 'Approval not found'}
    try:
        t.update_item(Key={'pk': 'APPROVALS', 'sk': aid}, UpdateExpression='SET #s=:n, decided_by=:b', ConditionExpression='#s=:p',
                      ExpressionAttributeNames={'#s': 'status'}, ExpressionAttributeValues={':n': 'approved' if ok else 'rejected', ':b': u['name'], ':p': 'pending'})
    except Exception:
        return {'ok': False, 'error': 'This approval was already decided'}
    ctx, tool, args = json.loads(item['ctx']), item['tool'], json.loads(item['args'])
    G['add_note'](ctx['sid'], '[MATRIX AI] %s %s the fix: %s.' % (u['name'], 'approved' if ok else 'rejected', item['summary']))
    AI.t_start('approval', u['u'], '%s %s' % (q.get('decision'), item['summary']))
    try:
        if not ok:
            _escalate(ctx, 'Proposed fix was rejected by %s' % u['name'])
            return {'ok': True, 'text': 'Rejected. %s was escalated to %s.' % (ctx['number'], L2_GROUP)}
        try:
            return {'ok': True, 'text': _apply_and_validate(ctx, tool, args, load_seen(item.get('seen')), u)}
        except Exception as e:
            # Never stop silently: say why in the ticket and hand over to L2 with the real reason.
            why = 'The approved fix could not be completed: %s' % str(e)[:200]
            try:
                _escalate(ctx, why)
            except Exception:
                pass
            return {'ok': True, 'text': '%s I passed %s to %s so a person can finish it.' % (why, ctx['number'], L2_GROUP)}
    finally:
        AI.t_end('ok')


# ---------------- ServiceNow helpers ----------------
def _group_id(name):
    r = G['sn']('GET', 'sys_user_group', {'sysparm_query': 'name=' + re.sub(r'[^\w .-]', '', name), 'sysparm_limit': '1', 'sysparm_fields': 'sys_id'}) or []
    return G['raw'](r[0]['sys_id']) if r else ''


def _escalate(ctx, reason):
    reason = re.sub(r'[*`#]+', '', re.sub(r'\s+', ' ', str(reason))).strip()[:400]
    body = {'work_notes': '[MATRIX AI] Escalated to L2 (MATRIX AI). Reason: %s\nWhat happens next: an L2 engineer needs to take this ticket. The notes above show what I already checked and did.' % reason, 'state': '2'}
    gid = _group_id(L2_GROUP)
    if gid:
        body['assignment_group'] = gid
    G['sn']('PATCH', 'incident/' + ctx['sid'], body=body)
    inbox_add('escalation', ctx['number'], '%s on %s needs an L2 engineer. %s' % (ctx['number'], ctx['host'], reason))
    return 'Escalated to %s: %s' % (L2_GROUP, reason)


def _known_pattern(alarm):
    key = re.sub(r'[^\w -]', '', alarm)[:60]
    if not key:
        return False
    r = G['sn']('GET', 'incident', {'sysparm_query': 'state=6^close_notesSTARTSWITHMATRIX AI auto-resolved^short_descriptionLIKE' + key,
                                    'sysparm_limit': str(AUTO_AFTER), 'sysparm_fields': 'sys_id'}) or []
    return len(r) >= AUTO_AFTER


# ---------------- LLM plumbing ----------------
def _llm(messages, tools, force=None):
    t0 = time.time()
    body = {'model': G['OPENAI_MODEL'], 'messages': messages, 'tools': tools}
    if force:
        body['tool_choice'] = {'type': 'function', 'function': {'name': force}}
    import gateway
    res = gateway.post(gateway.CHAIN, body)
    us, m = res.get('usage') or {}, res['choices'][0]['message']
    AI.T['pt'] = AI.T.get('pt', 0) + int(us.get('prompt_tokens', 0)); AI.T['ct'] = AI.T.get('ct', 0) + int(us.get('completion_tokens', 0))
    _mm = AI.T.setdefault('models', {}).setdefault(res.get('model') or G['OPENAI_MODEL'], {'calls': 0, 'in': 0, 'out': 0})
    _mm['calls'] += 1; _mm['in'] += int(us.get('prompt_tokens', 0)); _mm['out'] += int(us.get('completion_tokens', 0))
    AI.ev('llm', res.get('model') or G['OPENAI_MODEL'], {'prompt_tokens': us.get('prompt_tokens', 0), 'completion_tokens': us.get('completion_tokens', 0),
                                     'calls': [c['function']['name'] for c in (m.get('tool_calls') or [])], 'text': (m.get('content') or '')[:600]}, t0)
    return m


def _args(c):
    try:
        return json.loads(c['function'].get('arguments') or '{}')
    except Exception:
        return {}


def _read(name, args, ctx, seen=None):
    t0 = time.time()
    args = dict(args, host=ctx['host'], number=ctx['number'])
    try:
        out = str(G['READ'][name](args, AGENT_U))[:2000]
    except Exception as e:
        out = 'Error: ' + str(e)[:200]
    AI.T['tools'] = AI.T.get('tools', 0) + 1
    AI.ev('tool', name, {'args': args, 'result': out[:1500]}, t0)
    G['add_note'](ctx['sid'], '[MATRIX AI] I checked %s. %s' % (CHECK_NAMES.get(name, name.replace('_', ' ')), _short(out)))
    if seen is not None:
        seen.append(out)
    return out


FIXES = ('restart_service', 'clear_old_logs', 'kill_process')

# Plain names for the ticket's work notes, so a person can read them without knowing the tool names.
CHECK_NAMES = {'health_check': 'the overall health of the server', 'disk_usage': 'the disk space', 'top_cpu_processes': 'the busiest processes',
               'service_status': 'the status of the service', 'check_alarms': 'the alarms on the server', 'kb_search': 'the runbooks',
               'cmdb_lookup': 'the server record', 'incident_timeline': 'the earlier notes on this ticket'}
FIX_NAMES = {'restart_service': 'restart the service', 'clear_old_logs': 'delete old rotated log files', 'kill_process': 'stop the runaway process'}


def _short(text, n=220):
    """One readable line from raw tool output."""
    t = re.sub(r'\s+', ' ', str(text)).strip()
    return ('Result: ' + t[:n] + ('...' if len(t) > n else '')) if t else 'Nothing was returned.'


def _tools(*names):
    fn = G['_fn']
    out = [t for t in G['TOOLS'] if t['function']['name'] in names]
    return out


EXTRA = lambda: [
    G['_fn']('propose_fix', 'Choose the single fix to apply. action must be one of: restart_service, clear_old_logs, kill_process.',
             {'action': 'restart_service | clear_old_logs | kill_process', 'service': 'Service name (restart_service only)', 'pid': 'PID (kill_process only)',
              'name': 'Exact process name from top_cpu_processes (kill_process only)', 'reason': 'Evidence from the diagnostics that justifies this fix'},
             opt=('service', 'pid', 'name')),
    G['_fn']('escalate', 'Hand the incident to a human L2 engineer when no allowed fix fits or the evidence is unclear.', {'reason': 'Why a human is needed'}),
    G['_fn']('no_action_needed', 'Use this when the checks show there is nothing to fix: the alarm is already back to OK and CPU, memory, disk and services are all normal. '
             'Do not use it if any alarm is still in ALARM or any measurement is bad.', {'reason': 'One or two plain sentences with the numbers you saw'}),
]


def _diagnose(ctx):
    system = ("You are MATRIX AI, the L1 SRE agent. Incident %(number)s on server %(host)s, alarm %(alarm)s. Description: %(desc)s\n"
              "Approved runbook (follow it, do not go beyond it):\n%(runbook)s\n"
              "Diagnose with the read-only tools (health_check first, then whatever the alarm needs; use kb_search for the approved runbook). "
              "Then call propose_fix with ONE fix, or no_action_needed if the alarm is already back to OK and everything measured is normal (do not escalate a healthy server), or escalate. Fixes available: restart_service (only services: %(svc)s), clear_old_logs, kill_process. "
              "Never invent a PID or process name: take them from top_cpu_processes output. Never claim a state that no tool result shows. "
              "If the evidence points to something outside these fixes (hardware, network, application bug, data), escalate.") % dict(ctx, svc=', '.join(G['SERVICES']))
    tools = _tools('health_check', 'top_cpu_processes', 'disk_usage', 'service_status', 'check_alarms', 'kb_search', 'cmdb_lookup', 'incident_timeline') + EXTRA()
    msgs, seen = [{'role': 'system', 'content': system}, {'role': 'user', 'content': 'Start the investigation.'}], []
    for _ in range(8):
        m = _llm(msgs, tools)
        calls = m.get('tool_calls') or []
        if not calls:
            return {'action': 'escalate', 'reason': (m.get('content') or 'No decision from the model')[:300]}, seen
        msgs.append({'role': 'assistant', 'content': m.get('content'), 'tool_calls': calls})
        for c in calls:
            n, a = c['function']['name'], _args(c)
            if n == 'no_action_needed':
                return {'action': 'no_action', 'reason': a.get('reason', '')}, seen
            if n in ('propose_fix', 'escalate'):
                return dict(a, action=a.get('action') if n == 'propose_fix' else 'escalate'), seen
            msgs.append({'role': 'tool', 'tool_call_id': c['id'], 'content': _read(n, a, ctx, seen)})
    return {'action': 'escalate', 'reason': 'Diagnosis did not converge within the step limit'}, seen


def _alarm_is_ok(seen):
    """True only if an alarm check was run, it shows OK for the alarms, and no alarm line says ALARM."""
    text = '\n'.join(str(x) for x in seen)
    return bool(re.search(r':\s*OK\b', text)) and not re.search(r':\s*ALARM\b', text)


def _vet(d, ctx, seen):
    """Never trust the model: the fix must be in the catalogue and its arguments must match real diagnostic output."""
    act = str(d.get('action', ''))
    base = {'host': ctx['host'], 'number': ctx['number']}
    if act == 'restart_service':
        svc = str(d.get('service', '')).lower()
        if svc not in G['SERVICES']:
            raise RuntimeError('service %s is not managed. Allowed: %s' % (svc, ', '.join(G['SERVICES'])))
        return act, dict(base, service=svc)
    if act == 'clear_old_logs':
        return act, base
    if act == 'kill_process':
        pid, name = str(d.get('pid', '')).strip(), str(d.get('name', '')).strip()
        if not re.fullmatch(r'\d{2,7}', pid) or not name or name.lower() in G['NEVER_KILL']:
            raise RuntimeError('invalid or protected process')
        if not re.search(r'(^|\s)%s\s+%s\s' % (pid, re.escape(name[:15])), '\n'.join(seen)):
            raise RuntimeError('PID %s (%s) does not appear in the diagnostic output, so it will not be killed' % (pid, name))
        return act, dict(base, pid=pid, name=name)
    raise RuntimeError('action %s is not in the fix catalogue' % act)


def pack_seen(seen, limit=6000):
    """Store the diagnostics as valid JSON that fits the limit (shorten each item, never cut the JSON text itself)."""
    items = [str(s) for s in seen]
    per = max(200, limit // max(1, len(items)))
    while True:
        out = json.dumps([s[-per:] for s in items])
        if len(out) <= limit:
            return out
        if per <= 200:
            return json.dumps([s[-200:] for s in items[-3:]])
        per = max(200, int(per * 0.8))


def load_seen(raw):
    """Read stored diagnostics; an unreadable value gives an empty list so an approved fix still runs."""
    try:
        v = json.loads(raw or '[]')
        return [str(x) for x in v] if isinstance(v, list) else []
    except Exception:
        return []


def _summary(tool, a):
    return G['WRITE'][tool][0](a)


def _apply_and_validate(ctx, tool, args, seen, user, retried=False):
    t0 = time.time()
    out = G['WRITE'][tool][1](args, user)
    AI.T['tools'] = AI.T.get('tools', 0) + 1
    AI.ev('tool', tool, {'args': args, 'result': str(out)[:1500], 'by': user['u']}, t0)
    G['add_note'](ctx['sid'], '[MATRIX AI] I ran the fix: %s.\n%s' % (_summary(tool, args), _short(out, 500)))
    post = {'restart_service': 'service_status', 'clear_old_logs': 'disk_usage', 'kill_process': 'top_cpu_processes'}[tool]
    time.sleep(15)   # let the load settle before measuring again
    after = [_read('health_check', {}, ctx), _read(post, {'service': args.get('service', '')}, ctx)]
    vt = [G['_fn']('verdict', 'Report whether the problem is fixed, judging only from the post-fix diagnostics.',
                   {'resolved': 'yes or no', 'evidence': 'One or two sentences citing the post-fix output'})]
    msgs = [{'role': 'system', 'content': 'You validate an SRE fix. Alarm: %s on %s. Judge only from the outputs given; if they do not clearly show recovery answer no. '
             'IMPORTANT: a CloudWatch alarm only changes state a few minutes after the problem is gone, so an alarm that still says ALARM right after the fix is NOT evidence that the fix failed; ignore the alarm state. '
             'Decide from the live measurements: if the process that caused the problem is gone and CPU, load, memory, disk or the service are back to normal, answer yes.' % (ctx['alarm'], ctx['host'])},
            {'role': 'user', 'content': 'Diagnostics before the fix:\n%s\n\nFix applied: %s\nResult: %s\n\nDiagnostics after the fix:\n%s' % (
                '\n---\n'.join(seen)[-2500:], _summary(tool, args), str(out)[:500], '\n---\n'.join(after)[-2500:])}]
    m = _llm(msgs, vt, force='verdict')
    v = _args((m.get('tool_calls') or [{'function': {}}])[0])
    evidence = str(v.get('evidence', ''))[:400]
    if str(v.get('resolved', '')).lower().startswith('y'):
        G['a_resolve']({'sys_id': ctx['sid'], 'notes': 'MATRIX AI auto-resolved: %s fix verified. %s' % (tool, evidence)}, AGENT_U)
        inbox_add('resolved', ctx['number'], '%s resolved by MATRIX AI. %s' % (ctx['number'], evidence))
        return '%s fixed and verified. %s' % (ctx['number'], evidence)
    if not retried:
        # one more try: look again with what the failed fix taught us, and try a different safe fix before asking a person
        try:
            ctx2 = dict(ctx, desc=(ctx.get('desc', '') + ' A first fix (%s) did not recover it. Evidence: %s' % (_summary(tool, args), evidence))[:900])
            G['add_note'](ctx['sid'], '[MATRIX AI] That fix did not fully recover it. I am looking again before I escalate. %s' % evidence)
            d2, seen2 = _diagnose(ctx2)
            if d2.get('action') in ('restart_service', 'clear_old_logs', 'kill_process'):
                t2, a2 = _vet(d2, ctx, list(seen) + list(seen2))
                inst = G['need_instance']({'host': ctx['host']})
                same = (t2 == tool and a2 == args)
                if not same and ((t2 != 'kill_process' and AI._env(inst['id']) in AI.DEV_ENVS) or _known_pattern(ctx['alarm'])):
                    G['add_note'](ctx['sid'], '[MATRIX AI] Second try. What I found: %s\nWhat I plan to do: %s.' % (str(d2.get('reason', ''))[:300], _summary(t2, a2)))
                    return _apply_and_validate(ctx, t2, a2, list(seen) + list(seen2), user, retried=True)
        except Exception as e:
            print('autonomy: second try failed: %s' % str(e)[:200])
    return _escalate(ctx, 'Fix applied (%s) but post-check did not confirm recovery. %s' % (tool, evidence))


def _dev_host(ctx):
    """A dev server with no matching runbook: the agent may still use the approved safe fixes (restart allowed service, clear logs) and verify."""
    try:
        return AI._env(G['need_instance']({'host': ctx['host']})['id']) in AI.DEV_ENVS
    except Exception:
        return False


def _run(ctx):
    G['add_note'](ctx['sid'], '[MATRIX AI] I picked up this ticket and started looking at %s.' % ctx['host'])
    import rag
    hits = rag.retrieve(ctx['alarm'])
    best = hits[0]['coverage'] if hits else 0
    if best < rag.RAG_MIN and rag.RAG_REQUIRED and not _dev_host(ctx):
        return _escalate(ctx, 'No runbook in the knowledge base covers this alarm (best match %d%%, needs %d%%)' % (best * 100, rag.RAG_MIN * 100))
    ctx['runbook'] = '\n---\n'.join('[%s] %s' % (h['doc'], h['text'][:900]) for h in hits[:2]) or 'None found (RAG_REQUIRED is off).'
    if hits:
        G['add_note'](ctx['sid'], '[MATRIX AI] I am following the runbook "%s" (it matches this alarm about %d%%).' % (hits[0]['doc'], best * 100))
    d, seen = _diagnose(ctx)
    if d.get('action') == 'no_action':
        if not _alarm_is_ok(seen):
            return _escalate(ctx, 'I found no problem to fix, but the alarm check does not clearly show the alarm is back to OK. %s' % d.get('reason', ''))
        why = re.sub(r'[*`#]+', '', re.sub(r'\s+', ' ', str(d.get('reason', '')))).strip()[:400]
        G['add_note'](ctx['sid'], '[MATRIX AI] I checked everything and there is nothing to fix. %s\nThe alarm is already back to OK, so I am closing this ticket. If it comes back, a new ticket will open.' % why)
        G['a_resolve']({'sys_id': ctx['sid'], 'notes': 'MATRIX AI: no action needed. %s' % why}, AGENT_U)
        inbox_add('resolved', ctx['number'], '%s closed by MATRIX AI: no action needed. %s' % (ctx['number'], why))
        return '%s closed: no action needed. %s' % (ctx['number'], why)
    if d.get('action') == 'escalate':
        return _escalate(ctx, d.get('reason', 'Outside approved fixes'))
    try:
        tool, args = _vet(d, ctx, seen)
    except RuntimeError as e:
        return _escalate(ctx, 'Agent proposal rejected by safety checks: %s' % e)
    reason = str(d.get('reason', ''))[:400]
    inst = G['need_instance']({'host': ctx['host']})
    env = AI._env(inst['id'])
    auto = (tool != 'kill_process' and env in AI.DEV_ENVS) or _known_pattern(ctx['alarm'])
    G['add_note'](ctx['sid'], '[MATRIX AI] What I found: %s\nWhat I plan to do: %s.\nNext step: %s' % (
        reason.rstrip('. '), _summary(tool, args),
        'I am running it now, because this is a known pattern or a low-risk fix on a dev server.' if auto else 'I need a person to approve this in the MATRIX chat before I run it.'))
    if auto:
        return _apply_and_validate(ctx, tool, args, seen, AGENT_U)
    aid = '%013d#%s' % (int(time.time() * 1000), uuid.uuid4().hex[:6])
    AI._put({'pk': 'APPROVALS', 'sk': aid, 'status': 'pending', 'number': ctx['number'], 'host': ctx['host'], 'tool': tool, 'args': json.dumps(args),
             'summary': _summary(tool, args), 'reason': reason, 'evidence': '\n---\n'.join(seen)[-1500:], 'ctx': json.dumps(ctx), 'seen': pack_seen(seen),
             'created': int(time.time() * 1000), 'ttl': int(time.time()) + TTL})
    inbox_add('approval', ctx['number'], 'Approval needed on %s: %s. %s' % (ctx['number'], _summary(tool, args), reason))
    return 'Waiting for approval in the chat console: %s' % _summary(tool, args)


def a_agent_run(q, u):
    number = re.sub(r'[^A-Za-z0-9]', '', str(q.get('number', '')))
    sid = G['sys_id_of'](number)
    row = (G['sn']('GET', 'incident', {'sysparm_query': 'sys_id=' + sid, 'sysparm_limit': '1', 'sysparm_display_value': 'true',
                                        'sysparm_fields': 'short_description,description,cmdb_ci'}) or [{}])[0]
    host = re.sub(r'[^A-Za-z0-9._-]', '', str(q.get('host', '')) or G['val'](row.get('cmdb_ci')))
    if not host:
        return {'ok': False, 'error': 'No server (CI) on the incident or in the request'}
    alarm = str(q.get('alarm', '')) or G['val'](row.get('short_description'))
    ctx = {'runbook': '', 'number': number, 'sid': sid, 'host': host, 'alarm': alarm[:120], 'desc': G['val'](row.get('description'))[:600]}
    AI.t_start('agent', 'matrix.ai', '%s %s' % (number, alarm))
    try:
        res = _run(ctx)
        AI.t_end('ok')
    except Exception as e:
        AI.t_end('error')
        try:
            _escalate(ctx, 'Agent error: %s' % str(e)[:200])
        except Exception:
            pass
        return {'ok': False, 'error': str(e)[:300], 'trace_id': AI.T.get('id', '')}
    return {'ok': True, 'text': res, 'trace_id': AI.T.get('id', '')}


# ---------------- chat tools ----------------
HEALTH_SCRIPT = lambda svcs: (
    'echo "== uptime"; uptime; echo "== memory (MB)"; free -m; echo "== disk"; df -h -x tmpfs -x devtmpfs; '
    'echo "== top cpu"; ps -eo pid,comm,%cpu,%mem --sort=-%cpu | head -6; echo "== failed units"; systemctl --failed --no-legend | head -5; '
    'echo "== services"; for s in ' + ' '.join(svcs) + '; do echo "$s: $(systemctl is-active $s 2>&1)"; done')


def health_check(a, u):
    inst = G['need_instance']({'host': a.get('host')})
    st, out = G['ssm_run'](inst, 'health_check', '', 'MATRIX health check')
    text = 'Health check %s [%s]\n%s' % (inst['host'], st, out)
    try:
        s = ec2.describe_instance_status(InstanceIds=[inst['id']], IncludeAllInstances=True)['InstanceStatuses'][0]
        text += '\n== EC2 status checks\nsystem: %s, instance: %s' % (s['SystemStatus']['Status'], s['InstanceStatus']['Status'])
    except Exception:
        pass
    text += '\n== alarms\n' + G['_txt'](G['a_run']({'tool': 'check_alarm', 'host': inst['host']}, u))
    return text[:3500]


def create_ticket(a, u):
    ci, short = str(a.get('ci', '')).strip(), str(a.get('short_description', '')).strip()
    details, log = str(a.get('details', '')).strip(), str(a.get('error_log', '')).strip()
    shot = str(a.get('screenshot_note', '')).strip()
    miss = []
    if not ci: miss.append('the affected server / CI name')
    if len(short) < 10: miss.append('a clear one-line summary')
    if len(details) < 40: miss.append('what is failing, since when, and what changed (a few sentences)')
    if len(log) < 20 and not shot: miss.append('the error log text (paste it) or a screenshot description')
    if miss:
        return 'NOT CREATED. Still missing: %s. Ask the engineer for these; do not create the ticket yet.' % '; '.join(miss)
    inst = G['need_instance']({'host': ci})
    body = {'short_description': ('[MATRIX] ' + short)[:160], 'urgency': {'1': '1', '3': '3'}.get(str(a.get('urgency', '2')), '2'),
            'description': ('%s\n\nCI: %s\nError log:\n%s\n%s\nRaised from MATRIX chat by %s' % (details, inst['host'], log, ('Screenshot: ' + shot) if shot else '', u['name']))[:3900]}
    gid = _group_id(L1_GROUP)
    if gid: body['assignment_group'] = gid
    cr = G['sn']('GET', 'cmdb_ci_server', {'sysparm_query': 'name=' + inst['host'], 'sysparm_limit': '1', 'sysparm_fields': 'sys_id'}) or []
    if cr: body['cmdb_ci'] = G['raw'](cr[0]['sys_id'])
    r = G['sn']('POST', 'incident', body=body)
    number = G['raw'](r['number'])
    G['add_note'](G['raw'](r['sys_id']), '[MATRIX] Created from chat by %s. Assigned to %s.' % (u['name'], L1_GROUP))
    started = _kick(number, inst['host'], short)
    return 'Created %s for %s and assigned it to %s. %s' % (number, inst['host'], L1_GROUP, started)


def _kick(number, host, alarm):
    fn = os.environ.get('AWS_LAMBDA_FUNCTION_NAME')
    if not (AGENT_KEY and fn):
        return 'AGENT_KEY is not set, so the agent was not started automatically.'
    body = urllib.parse.urlencode({'action': 'agent_run', 'token': 'svc:' + AGENT_KEY, 'number': number, 'host': host, 'alarm': alarm[:120]})
    lam.invoke(FunctionName=fn, InvocationType='Event', Payload=json.dumps({'requestContext': {'http': {'method': 'POST'}}, 'body': body}).encode())
    return 'MATRIX AI has started diagnosing it; follow it in Incidents and Traces.'


def _size(a):
    vcpu, ram, disk = int(a['vcpu']), int(a['ram_gb']), int(a['disk_gb'])
    if not (1 <= vcpu <= MAX_VCPU and 1 <= ram <= MAX_RAM and 8 <= disk <= MAX_DISK):
        raise RuntimeError('Outside the allowed size: up to %d vCPU, %d GB RAM, %d GB disk (minimum disk 8 GB)' % (MAX_VCPU, MAX_RAM, MAX_DISK))
    name = re.sub(r'[^A-Za-z0-9-]', '', str(a.get('name', '')))[:40]
    env = str(a.get('environment', 'dev')).lower()
    if not name:
        raise RuntimeError('A server name is required')
    if env not in AI.DEV_ENVS and not str(a.get('number', '')).strip():
        raise RuntimeError('Non-dev deployment needs a change or incident number. Do NOT ask the engineer: call create_change_request (kind deployment) and retry with the number it returns.')
    types = [t['InstanceType'] for t in ec2.describe_instance_types(Filters=[
        {'Name': 'vcpu-info.default-vcpus', 'Values': [str(vcpu)]}, {'Name': 'memory-info.size-in-mib', 'Values': [str(ram * 1024)]},
        {'Name': 'current-generation', 'Values': ['true']}, {'Name': 'processor-info.supported-architecture', 'Values': ['x86_64']}])['InstanceTypes']]
    pick = next((t for f in FAMILIES for t in sorted(types) if t.split('.')[0] == f), '')
    if not pick:
        raise RuntimeError('No instance type in families %s has exactly %d vCPU and %d GB RAM' % (', '.join(FAMILIES), vcpu, ram))
    miss = [k for k, v in DEPLOY.items() if not v]
    if miss:
        raise RuntimeError('Not configured on the Lambda: ' + ', '.join(miss))
    return name, pick, disk, env, 'name=%s,type=%s,disk_gb=%d,subnet_id=%s,sg_id=%s,profile=%s,environment=%s' % (
        name, pick, disk, DEPLOY['DEPLOY_SUBNET'], DEPLOY['DEPLOY_SG'], DEPLOY['DEPLOY_PROFILE'], env)


def deploy_check(a):
    name, pick, disk, env, _ = _size(a)
    return 'DEPLOY new Linux server %s: %s (%s vCPU, %s GB RAM), %d GB disk, environment %s' % (name, pick, a['vcpu'], a['ram_gb'], disk, env)


def deploy_run(a, u):
    name, pick, disk, env, v = _size(a)
    job = AI._tf('apply', {'module': 'ec2-linux', 'vars': v})
    AI._audit(a, u, 'deploy server %s (%s, %d GB) -> %s' % (name, pick, disk, job))
    return AI._started(job, 'Server deployment')


# ---------------- install ----------------
def install(g):
    G.update(g)
    fn = g['_fn']
    g['LIN']['health_check'] = lambda a: HEALTH_SCRIPT([s for s in g['SERVICES'] if re.fullmatch(r'[a-z0-9_.@-]+', s)])
    g['READ'].update({'health_check': health_check, 'create_incident_ticket': create_ticket})
    g['WRITE']['deploy_server'] = (deploy_check, deploy_run)
    g['TOOLS'].extend([
        fn('health_check', 'General health check of a Linux server: uptime, memory, disk, top CPU processes, failed units, managed services, EC2 status checks and alarms (read-only).', {'host': g['ARG_HOST']}),
        fn('create_incident_ticket', 'Create a ServiceNow incident assigned to MATRIX AI and start the agent. Call ONLY after the engineer gave the CI, a real description and error log text or a screenshot description. Refuses if details are missing.',
           {'ci': 'Affected server name', 'short_description': 'One-line summary', 'details': 'What is failing, since when, what changed', 'error_log': 'Error log text the engineer pasted',
            'screenshot_note': 'Description of an attached screenshot', 'urgency': '1 high, 2 medium, 3 low'}, opt=('error_log', 'screenshot_note', 'urgency')),
        fn('deploy_server', 'Deploy a new Linux server with Terraform from a vCPU / RAM / disk request. Needs confirmation.',
           {'name': 'Name tag for the new server', 'vcpu': 'Number of vCPUs', 'ram_gb': 'RAM in GB', 'disk_gb': 'Root disk in GB', 'environment': 'dev, test or prod (default dev)', 'number': g['ARG_NUM']},
           opt=('environment', 'number')),
    ])
    g['CHAT_SYSTEM'] += (
        " General health check: call health_check and summarise CPU, memory, disk, services and alarms, flagging anything abnormal. "
        "Patching: call patch_scan, show what is missing, then patch_install; the host's package repositories supply the latest patches. "
        "Deploying a server: call deploy_server with the requested vCPU, RAM and disk, and report the instance type it picked. "
        "Incident intake: if the engineer asks for a ticket with vague text such as 'java app not working', DO NOT create it. Ask for the affected server (CI), what exactly fails and since when, "
        "and the error log text or a screenshot description, then call create_incident_ticket. The ticket goes to MATRIX AI, which starts diagnosing on its own. "
        "Approvals the agent needs and escalations to L2 appear in the console's Approvals and Inbox panels; tell the engineer to look there when relevant.")

    orig = g['check_token']
    def check_token(t):
        if AGENT_KEY and str(t).startswith('svc:') and hmac.compare_digest(str(t)[4:], AGENT_KEY):
            return dict(AGENT_U, exp=int(time.time() * 1000) + 600000)
        return orig(t)
    g['check_token'] = check_token
    g['ACTIONS'].update({'agent_run': a_agent_run, 'approvals': a_approvals, 'approval_decide': a_approval_decide, 'inbox': a_inbox})
