"""
matrix_tenant.py - who the customer is, and a safe way to act inside THEIR AWS account (vendor-hosted edition, MDA-001 step A2).

A tenant is one customer. For a self-hosted install there is exactly one tenant, called 'default', built from the Lambda's own settings,
so nothing changes for those installs. For the vendor-hosted edition each customer is a record in the tenant table
(settings TENANT_TABLE, default 'matrix-tenants'):

    tenant_id (key), account_id, region, role_arn, status ('active' | 'suspended'), plan, name, snow_url
    The ExternalId is NOT in the table. It is read from Secrets Manager (secret name  matrix/tenant/<tenant_id>/external-id).

Rules this module enforces (they protect one customer from another):
  - a tenant id is letters, digits, dash or underscore only;
  - the role ARN must belong to the tenant's own AWS account id, so a record can never point at someone else's account;
  - a suspended tenant gets no session at all;
  - credentials are cached only until shortly before they expire, and never across tenants.
"""
import os
import re
import time

import boto3

TENANT_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
CACHE = {}
SKEW = 120   # drop cached credentials this many seconds early


class TenantError(Exception):
    pass


def _account_of(arn):
    m = re.match(r'^arn:aws[a-z-]*:iam::(\d{12}):role/', str(arn or ''))
    return m.group(1) if m else ''


def default_tenant(env=None):
    """The single customer of a self-hosted install, from the Lambda's own settings."""
    env = os.environ if env is None else env
    role = env.get('EXECUTOR_ROLE_ARN', '')
    return {'tenant_id': 'default', 'account_id': _account_of(role), 'region': env.get('AWS_REGION', 'ap-southeast-2'),
            'role_arn': role, 'status': 'active', 'plan': env.get('LICENSE_PLAN', ''), 'name': env.get('LICENSE_NAME', ''),
            'external_id': env.get('EXTERNAL_ID', '')}


def _table(env=None):
    env = os.environ if env is None else env
    return boto3.resource('dynamodb').Table(env.get('TENANT_TABLE', 'matrix-tenants'))


def _secret(tenant_id):
    sm = boto3.client('secretsmanager')
    return sm.get_secret_value(SecretId='matrix/tenant/%s/external-id' % tenant_id)['SecretString']


def validate(t):
    """Raises TenantError if the record is unsafe to use."""
    tid = str(t.get('tenant_id', ''))
    if not TENANT_RE.match(tid):
        raise TenantError('bad tenant id')
    if t.get('status', 'active') != 'active':
        raise TenantError('tenant %s is not active' % tid)
    if t.get('role_arn'):
        acct = _account_of(t['role_arn'])
        if not acct:
            raise TenantError('tenant %s has an unreadable role ARN' % tid)
        if t.get('account_id') and str(t['account_id']) != acct:
            raise TenantError('tenant %s: the role belongs to a different AWS account than the tenant record' % tid)
    return t


def load(tenant_id=None, table=None, secret=None, env=None):
    """Return the validated tenant. None or 'default' means the self-hosted single tenant."""
    if not tenant_id or tenant_id == 'default':
        return validate(default_tenant(env))
    if not TENANT_RE.match(str(tenant_id)):
        raise TenantError('bad tenant id')
    item = (table or _table(env)).get_item(Key={'tenant_id': tenant_id}).get('Item')
    if not item:
        raise TenantError('unknown tenant')
    item = dict(item)
    item['tenant_id'] = tenant_id
    validate(item)
    if item.get('role_arn'):
        item['external_id'] = (secret or _secret)(tenant_id)
    return item


def session_for(tenant, session_name='matrix', duration=900, sts=None, now=None):
    """A boto3 Session acting inside the tenant's account, or the Lambda's own session when the tenant has no role."""
    validate(tenant)
    region = tenant.get('region') or None
    if not tenant.get('role_arn'):
        return boto3.Session(region_name=region)
    name = re.sub(r'[^\w=,.@-]', '', str(session_name))[:60] or 'matrix'
    key = (tenant['tenant_id'], tenant['role_arn'], name)
    now = time.time() if now is None else now
    hit = CACHE.get(key)
    if hit and hit[0] - SKEW > now:
        c = hit[1]
    else:
        args = {'RoleArn': tenant['role_arn'], 'RoleSessionName': name, 'DurationSeconds': duration}
        if tenant.get('external_id'):
            args['ExternalId'] = tenant['external_id']
        r = (sts or boto3.client('sts', region_name=region)).assume_role(**args)['Credentials']
        exp = r.get('Expiration')
        exp = exp.timestamp() if hasattr(exp, 'timestamp') else now + duration
        c = r
        CACHE[key] = (exp, c)
    return boto3.Session(aws_access_key_id=c['AccessKeyId'], aws_secret_access_key=c['SecretAccessKey'],
                         aws_session_token=c['SessionToken'], region_name=region)


def client(tenant, service, session_name='matrix', **kw):
    return session_for(tenant, session_name).client(service, **kw)
