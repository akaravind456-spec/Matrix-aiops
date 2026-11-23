"""
matrix_license.py - the usage meter behind the Dashboard "Licence" card. It only MEASURES; it never blocks anything.

Entry file (lambda_function.py), before learning.install(g):
    import matrix_license
    matrix_license.install(g)

Signed key (self-hosted edition): LICENSE_KEY holds a vendor-signed key (see matrix_licence_key.py). When it is present, the plan, limits,
customer name, AWS account and expiry come ONLY from the signed key and the LICENSE_PLAN/SERVERS/SEATS settings below are ignored, so editing
a setting cannot raise a limit. LICENSE_ENFORCE=1 makes changes (confirm, agent fixes, approvals) stop when there is no valid key.
Settings (all optional):
  LICENSE_PLAN     starter | team | commander | custom      (unset = evaluation, no limits shown)
  LICENSE_SERVERS  number, overrides the plan's server limit (use with custom deals); 0 or 'unlimited' = no limit
  LICENSE_SEATS    number, overrides the plan's seat limit
  LICENSE_NAME     customer label shown on the card
Counts:
  servers = EC2 instances tagged matrix-managed=true and environment=<ENVIRONMENT>, running or stopped (cached 10 minutes)
  seats   = console users in the USERS setting (only the number is returned, never names or passwords)
Prices are NOT in this file. They live in docs/LIC-001-Licensing-and-Pricing.md.
The Lambda role needs ec2:DescribeInstances (already in the stack).
"""
import json, os, time

import matrix_licence_key as LK

PLANS = {
    'starter':   {'servers': 25,   'seats': 2},
    'team':      {'servers': 100,  'seats': 10},
    'commander': {'servers': None, 'seats': 50},     # None = unlimited (fair use)
}
NEAR = 0.9
TTL = 600
CACHE = {}


def _num(v):
    """'unlimited', '0', '' -> None; '25' -> 25; garbage -> None"""
    s = str(v if v is not None else '').strip().lower()
    if s in ('', 'unlimited', '0', 'none'):
        return None
    try:
        n = int(s)
        return n if n > 0 else None
    except ValueError:
        return None


def limits(env=None):
    """Returns (plan, name, {'servers': n|None, 'seats': n|None}). plan is 'evaluation' when no licence is set."""
    env = os.environ if env is None else env
    plan = str(env.get('LICENSE_PLAN', '')).strip().lower()
    name = str(env.get('LICENSE_NAME', '')).strip()[:80]
    if plan not in PLANS and plan != 'custom':
        return 'evaluation', name, {'servers': None, 'seats': None}
    base = dict(PLANS.get(plan, {'servers': None, 'seats': None}))
    if str(env.get('LICENSE_SERVERS', '')).strip() != '':
        base['servers'] = _num(env.get('LICENSE_SERVERS'))
    if str(env.get('LICENSE_SEATS', '')).strip() != '':
        base['seats'] = _num(env.get('LICENSE_SEATS'))
    return plan, name, base


def resolve(env=None, account_id='', now=None):
    """The licence in force. A signed LICENSE_KEY wins over every other setting."""
    env = os.environ if env is None else env
    key = str(env.get('LICENSE_KEY', '')).strip()
    if key:
        c = LK.check(key, account_id, now)
        if c['valid']:
            cl = c['claims']
            return {'plan': str(cl.get('p', 'custom')).lower()[:20], 'name': str(cl.get('c', ''))[:80],
                    'limits': {'servers': _num(cl.get('s')), 'seats': _num(cl.get('u'))},
                    'signed': True, 'valid': True, 'reason': '', 'expires': cl.get('e') or None}
        return {'plan': 'invalid', 'name': str(c['claims'].get('c', ''))[:80], 'limits': {'servers': None, 'seats': None},
                'signed': True, 'valid': False, 'reason': c['reason'], 'expires': c['claims'].get('e') or None}
    plan, name, lim = limits(env)
    return {'plan': plan, 'name': name, 'limits': lim, 'signed': False, 'valid': False,
            'reason': 'no signed licence key is set', 'expires': None}


def enforced(env=None):
    env = os.environ if env is None else env
    return str(env.get('LICENSE_ENFORCE', '')).strip().lower() in ('1', 'true', 'yes')


def blocked(env=None, account_id='', now=None):
    """Why changes must stop, or '' when they may run. Only ever non-empty when LICENSE_ENFORCE is on."""
    if not enforced(env):
        return ''
    r = resolve(env, account_id, now)
    return '' if r['valid'] else 'MATRIX is not licensed for changes: %s. Reads still work. Ask the vendor for a valid licence key.' % r['reason']


def state(used, limit):
    if limit is None:
        return 'ok'
    if used > limit:
        return 'over'
    if used >= limit * NEAR:
        return 'near'
    return 'ok'


def count_seats(users):
    return len(users) if isinstance(users, list) else 0


def count_servers(ec2, environment):
    n, token = 0, None
    flt = [{'Name': 'tag:matrix-managed', 'Values': ['true']},
           {'Name': 'tag:environment', 'Values': [environment]},
           {'Name': 'instance-state-name', 'Values': ['pending', 'running', 'stopping', 'stopped']}]
    while True:
        kw = {'Filters': flt, 'MaxResults': 500}
        if token:
            kw['NextToken'] = token
        r = ec2.describe_instances(**kw)
        for res in r.get('Reservations', []):
            n += len(res.get('Instances', []))
        token = r.get('NextToken')
        if not token:
            return n


def report(ec2, users, environment, env=None, now=None, account_id=''):
    lic = resolve(env, account_id, now)
    plan, name, lim = lic['plan'], lic['name'], lic['limits']
    now = time.time() if now is None else now
    key = ('servers', environment)
    hit = CACHE.get(key)
    if hit and now - hit[0] < TTL:
        servers = hit[1]
    else:
        servers = count_servers(ec2, environment)
        CACHE[key] = (now, servers)
    seats = count_seats(users)
    s_state, p_state = state(servers, lim['servers']), state(seats, lim['seats'])
    status = 'over' if 'over' in (s_state, p_state) else 'near' if 'near' in (s_state, p_state) else 'ok'
    if lic['signed'] and not lic['valid']:
        status = 'invalid'
    return {'ok': True, 'plan': plan, 'name': name, 'licensed': plan not in ('evaluation', 'invalid'),
            'servers': {'used': servers, 'limit': lim['servers'], 'state': s_state},
            'seats': {'used': seats, 'limit': lim['seats'], 'state': p_state},
            'status': status, 'enforced': enforced(env),
            'signed': lic['signed'], 'key_valid': lic['valid'], 'key_problem': lic['reason'] if lic['signed'] else '',
            'expires': lic['expires']}


_ACCT = {}


def account_id():
    """The AWS account this Lambda runs in (cached). Empty if it cannot be read."""
    if 'id' not in _ACCT:
        try:
            import boto3
            _ACCT['id'] = boto3.client('sts').get_caller_identity()['Account']
        except Exception:
            return ''
    return _ACCT['id']


def install(g):
    import boto3

    def a_license(q, u):
        try:
            users = json.loads(os.environ.get('USERS', '[]'))
        except Exception:
            users = []
        try:
            ec2 = boto3.client('ec2')
            return report(ec2, users, os.environ.get('ENVIRONMENT', 'dev'), account_id=account_id())
        except Exception as e:
            msg = str(e)
            if 'UnauthorizedOperation' in msg or 'AccessDenied' in msg:
                msg = 'The Lambda role needs ec2:DescribeInstances.'
            return {'ok': False, 'error': msg[:300]}

    g['ACTIONS']['license'] = a_license


def install_gate(g):
    """Call this LAST in lambda_function.py, after every other install, so it wraps whatever the other modules put in ACTIONS.
    With LICENSE_ENFORCE=1, every action that changes something stops unless a valid signed key is present. Reads keep working."""
    def gate(fn):
        def wrapped(q, u):
            why = blocked(account_id=account_id())
            if why:
                return {'ok': False, 'error': why}
            return fn(q, u)
        return wrapped
    for name in ('chat_confirm', 'agent_run', 'decide', 'run', 'service', 'kill'):
        if name in g['ACTIONS']:
            g['ACTIONS'][name] = gate(g['ACTIONS'][name])
