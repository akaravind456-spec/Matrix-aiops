"""
matrix_license.py - the usage meter behind the Dashboard "Licence" card. It only MEASURES; it never blocks anything.

Entry file (lambda_function.py), before learning.install(g):
    import matrix_license
    matrix_license.install(g)

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


def report(ec2, users, environment, env=None, now=None):
    plan, name, lim = limits(env)
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
    return {'ok': True, 'plan': plan, 'name': name, 'licensed': plan != 'evaluation',
            'servers': {'used': servers, 'limit': lim['servers'], 'state': s_state},
            'seats': {'used': seats, 'limit': lim['seats'], 'state': p_state},
            'status': status, 'enforced': False}


def install(g):
    import boto3

    def a_license(q, u):
        try:
            users = json.loads(os.environ.get('USERS', '[]'))
        except Exception:
            users = []
        try:
            ec2 = boto3.client('ec2')
            return report(ec2, users, os.environ.get('ENVIRONMENT', 'dev'))
        except Exception as e:
            msg = str(e)
            if 'UnauthorizedOperation' in msg or 'AccessDenied' in msg:
                msg = 'The Lambda role needs ec2:DescribeInstances.'
            return {'ok': False, 'error': msg[:300]}

    g['ACTIONS']['license'] = a_license
