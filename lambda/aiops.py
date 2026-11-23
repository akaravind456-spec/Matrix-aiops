"""MATRIX AIOps extension. Drop next to your Lambda file and add two lines at the very END of it:

    import aiops
    aiops.install(globals())

It adds to the existing chat agent (nothing else in your file changes):
  - Trace/observability: every chat turn is stored in DynamoDB (each LLM call with token counts, each tool call with args/result/timing)
  - CMDB lookup (ServiceNow cmdb_ci_server) and KB search (kb_knowledge)
  - Patching (SSM Patch Manager), Ansible playbooks (SSM AWS-RunAnsiblePlaybook), Terraform (CodeBuild)
  - Server migration (AMI + relaunch in another AZ/size) and data migration (through an S3 ops bucket)
Everything that changes something goes through the same Confirm button as restart/kill.

Extra environment variables:
  TRACE_TABLE   DynamoDB table (pk String, sk String, TTL attribute "ttl")
  OPS_BUCKET    S3 bucket holding playbooks/<name>.yml, terraform/<module>/*.tf and migrations/
  PLAYBOOKS     comma list of allowed playbook names (without .yml)
  TF_MODULES    comma list of allowed Terraform module folder names
  TF_PROJECT    CodeBuild project name that runs terraform (see buildspec.yml)
  ALLOWED_TYPES instance types a migration may use (default t3.micro,t3.small,t3.medium)
"""
import json, os, re, time, uuid
import boto3
from boto3.dynamodb.conditions import Key

REGION = os.environ.get('AWS_REGION', 'ap-southeast-2')
TRACE_TABLE = os.environ.get('TRACE_TABLE', '').strip()
OPS_BUCKET = os.environ.get('OPS_BUCKET', '').strip()
TF_PROJECT = os.environ.get('TF_PROJECT', '').strip()
PLAYBOOKS = [x.strip() for x in os.environ.get('PLAYBOOKS', '').split(',') if x.strip()]
TF_MODULES = [x.strip() for x in os.environ.get('TF_MODULES', '').split(',') if x.strip()]
ALLOWED_TYPES = [x.strip() for x in os.environ.get('ALLOWED_TYPES', 't3.micro,t3.small,t3.medium').split(',') if x.strip()]
DEV_ENVS = {'dev', 'development', 'test'}
TTL_DAYS = 30

ssm = boto3.client('ssm', region_name=REGION)
ec2 = boto3.client('ec2', region_name=REGION)
cb = boto3.client('codebuild', region_name=REGION)
logs = boto3.client('logs', region_name=REGION)
ddb = boto3.resource('dynamodb', region_name=REGION).Table(TRACE_TABLE) if TRACE_TABLE else None

G = {}   # the main module's globals, filled by install()
T = {}   # the trace currently being recorded (one request at a time per Lambda container)


# ---------------- tracing ----------------
def _put(item):
    if ddb:
        try:
            ddb.put_item(Item=item)
        except Exception:
            pass


def _summary():
    _put({'pk': 'TRACES', 'sk': T['sk'], 'trace_id': T['id'], 'user': T['user'], 'kind': T['kind'], 'prompt': T['prompt'],
          'prompt_tokens': T['pt'], 'completion_tokens': T['ct'], 'tools': T['tools'], 'status': T['status'],
          'models': json.dumps(T.get('models', {})), 'ms': int((time.time() - T['t0']) * 1000), 'ttl': int(time.time()) + TTL_DAYS * 86400})


def t_start(kind, user, prompt):
    now = time.time(); tid = uuid.uuid4().hex[:12]
    T.clear()
    T.update(id=tid, seq=0, t0=now, user=user, kind=kind, prompt=str(prompt)[:300], pt=0, ct=0, tools=0, status='running',
             sk='%013d#%s' % (int(now * 1000), tid))
    _summary()


def t_end(status):
    if T:
        T['status'] = status
        _summary()


def ev(kind, name, data, t0):
    if not T:
        return
    T['seq'] += 1
    _put({'pk': T['id'], 'sk': '%04d' % T['seq'], 'kind': kind, 'name': name, 'data': json.dumps(data, default=str)[:6000],
          'at': int(time.time() * 1000), 'ms': int((time.time() - t0) * 1000), 'ttl': int(time.time()) + TTL_DAYS * 86400})


def _plain(x):
    return json.loads(json.dumps(x, default=lambda o: int(o) if o == int(o) else float(o)))


def a_traces(q, u):
    if not ddb:
        return {'ok': False, 'error': 'TRACE_TABLE is not configured'}
    r = ddb.query(KeyConditionExpression=Key('pk').eq('TRACES'), ScanIndexForward=False, Limit=40)
    return {'ok': True, 'traces': _plain([{k: v for k, v in i.items() if k not in ('pk', 'ttl')} for i in r['Items']])}


def a_trace(q, u):
    tid = re.sub(r'[^0-9a-f]', '', str(q.get('trace_id', '')))
    if not ddb or not tid:
        return {'ok': False, 'error': 'TRACE_TABLE is not configured or trace_id missing'}
    r = ddb.query(KeyConditionExpression=Key('pk').eq(tid))
    out = []
    for i in _plain(r['Items']):
        try:
            d = json.loads(i.get('data', '{}'))
        except Exception:
            d = {'raw': i.get('data')}
        out.append({'seq': i['sk'], 'kind': i['kind'], 'name': i['name'], 'at': i['at'], 'ms': i['ms'], 'data': d})
    return {'ok': True, 'events': out}


# ---------------- shared helpers ----------------
def _inst(host):
    return G['need_instance']({'host': host})


def _env(inst_id):
    try:
        t = ec2.describe_tags(Filters=[{'Name': 'resource-id', 'Values': [inst_id]}, {'Name': 'key', 'Values': ['Environment']}])['Tags']
        return t[0]['Value'].lower() if t else 'unknown'
    except Exception:
        return 'unknown'


def _guard(inst, a, what):
    """Only servers tagged production/prod need an incident or change number. Untagged and dev servers need just the Confirm click."""
    env = _env(inst['id'])
    if env in ('prod', 'production') and not str(a.get('number', '')).strip():
        raise RuntimeError('%s is a production server. %s needs a change or incident number. Do NOT ask the engineer: call create_change_request for this server now, then retry with the number it returns as `number`.' % (inst['host'], what))
    return env


def _audit(a, u, text):
    G['add_note'](G['_sid'](a), '[MATRIX L2 Chat] %s: %s' % (u['u'], text[:1500]))


def _send(inst, doc, params, comment):
    if inst['state'] != 'running':
        raise RuntimeError('%s is %s, not running' % (inst['host'], inst['state']))
    r = ssm.send_command(InstanceIds=[inst['id']], DocumentName=doc, Parameters=params, Comment=comment[:90], TimeoutSeconds=120)
    return 'ssm:%s:%s' % (r['Command']['CommandId'], inst['id'])


def _started(job, what):
    return '%s started. Job id: %s. Use job_status to follow it; it is not finished yet.' % (what, job)


def job_status(a, u):
    kind, _, rest = str(a.get('job', '')).partition(':')
    if kind == 'ssm':
        cid, _, iid = rest.partition(':')
        try:
            g = ssm.get_command_invocation(CommandId=cid, InstanceId=iid)
        except ssm.exceptions.InvocationDoesNotExist:
            return 'Status: Pending (not delivered yet)'
        out = (g.get('StandardOutputContent', '') + g.get('StandardErrorContent', '')).strip()[-1800:]
        return 'Status: %s\n%s' % (g['Status'], out)
    if kind == 'cb':
        b = cb.batch_get_builds(ids=[rest])['builds'][0]
        text = 'Build status: %s (phase %s)' % (b['buildStatus'], b.get('currentPhase', ''))
        lg = b.get('logs') or {}
        if lg.get('groupName') and lg.get('streamName') and b['buildStatus'] != 'IN_PROGRESS':
            try:
                ev_ = logs.get_log_events(logGroupName=lg['groupName'], logStreamName=lg['streamName'], limit=50, startFromHead=False)['events']
                text += '\n' + '\n'.join(e['message'].rstrip() for e in ev_)[-1500:]
            except Exception:
                pass
        return text
    if kind == 'ami':
        try:
            im = ec2.describe_images(ImageIds=[rest])['Images']
        except Exception:
            im = []
        if not im:
            return ('Image %s was not found. The id may be wrong: use the exact "Job id: ami:ami-..." text from the earlier Done message, '
                    'do not guess it.' % rest)
        return 'Image %s: %s' % (rest, im[0]['State'])
    return 'Unknown job id. It must look like ssm:..., cb:... or ami:...'


# ---------------- CMDB and KB ----------------
def cmdb_lookup(a, u):
    n = re.sub(r'[^A-Za-z0-9._-]', '', str(a.get('host', '')))[:60]
    rows = G['sn']('GET', 'cmdb_ci_server', {'sysparm_query': 'nameLIKE' + n, 'sysparm_limit': '5', 'sysparm_display_value': 'true',
                                             'sysparm_fields': 'name,sys_class_name,ip_address,os,environment,support_group,owned_by,location'}) or []
    return json.dumps(rows)[:2000] if rows else 'No CMDB record for ' + n


def kb_search(a, u):
    t = re.sub(r'[^\w\s.-]', '', str(a.get('text', '')))[:60]
    rows = G['sn']('GET', 'kb_knowledge', {'sysparm_query': 'workflow_state=published^short_descriptionLIKE%s^ORtextLIKE%s' % (t, t),
                                           'sysparm_limit': '3', 'sysparm_fields': 'number,short_description,text'}) or []
    out = ['%s %s\n%s' % (r['number'], r['short_description'], re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', r.get('text', '')))[:900]) for r in rows]
    return '\n\n'.join(out) or 'No published KB article matches "%s".' % t


def catalog(a, u):
    return 'Playbooks: %s\nTerraform modules: %s\nAllowed migration instance types: %s' % (
        ', '.join(PLAYBOOKS) or 'none configured', ', '.join(TF_MODULES) or 'none configured', ', '.join(ALLOWED_TYPES))


# ---------------- patching ----------------
def _patch(op, a):
    inst = _inst(a['host'])
    reboot = 'RebootIfNeeded' if str(a.get('reboot', '')).lower() == 'yes' else 'NoReboot'
    return _send(inst, 'AWS-RunPatchBaseline', {'Operation': [op], 'RebootOption': [reboot]}, 'MATRIX patch %s' % op.lower())


def patch_scan(a, u):
    return _started(_patch('Scan', a), 'Patch scan (read-only)')


def patch_install_check(a):
    _guard(_inst(a['host']), a, 'Patching')
    return 'Install OS patches on %s (reboot if needed: %s)' % (a['host'], a.get('reboot', 'no'))


def patch_install(a, u):
    job = _patch('Install', a)
    _audit(a, u, 'patch install on %s -> %s' % (a['host'], job))
    return _started(job, 'Patch install')


# ---------------- Ansible ----------------
def _playbook(a, check):
    pb = str(a.get('playbook', ''))
    if pb not in PLAYBOOKS:
        raise RuntimeError('Playbook not allowed. Allowed: ' + (', '.join(PLAYBOOKS) or 'none configured'))
    if not OPS_BUCKET:
        raise RuntimeError('OPS_BUCKET is not configured')
    xv = str(a.get('extra_vars', '')).strip()
    if xv and not re.fullmatch(r'[A-Za-z0-9_.=-]+( [A-Za-z0-9_.=-]+)*', xv):
        raise RuntimeError('extra_vars must be space separated key=value pairs (letters, digits, . _ -)')
    inst = _inst(a['host'])
    if inst['platform'] != 'linux':
        raise RuntimeError('Playbooks run on Linux servers only')
    return inst, _send(inst, 'AWS-RunAnsiblePlaybook',
                       {'playbookurl': ['s3://%s/playbooks/%s.yml' % (OPS_BUCKET, pb)], 'extravars': [('SSM=True ' + xv).strip()],
                        'check': ['True' if check else 'False'], 'timeoutSeconds': ['600']}, 'MATRIX playbook ' + pb)


def playbook_check(a, u):
    return _started(_playbook(a, True)[1], 'Playbook dry run (check mode, nothing changed)')


def playbook_run_check(a):
    inst = _inst(a['host'])
    _guard(inst, a, 'Running a playbook')
    return 'Run playbook %s on %s%s' % (a['playbook'], a['host'], (' with ' + a['extra_vars']) if a.get('extra_vars') else '')


def playbook_run(a, u):
    inst, job = _playbook(a, False)
    _audit(a, u, 'playbook %s on %s -> %s' % (a['playbook'], inst['host'], job))
    return _started(job, 'Playbook run')


# ---------------- Terraform (CodeBuild) ----------------
def _tf(action, a):
    m = str(a.get('module', ''))
    if m not in TF_MODULES:
        raise RuntimeError('Terraform module not allowed. Allowed: ' + (', '.join(TF_MODULES) or 'none configured'))
    if not TF_PROJECT:
        raise RuntimeError('TF_PROJECT is not configured')
    v = str(a.get('vars', '')).strip()
    if v and not re.fullmatch(r'[A-Za-z0-9_.=,/-]{1,300}', v):
        raise RuntimeError('vars must be comma separated key=value pairs, for example name=web-03,type=t3.micro')
    env = [{'name': 'TF_MODULE', 'value': m, 'type': 'PLAINTEXT'}, {'name': 'TF_ACTION', 'value': action, 'type': 'PLAINTEXT'},
           {'name': 'TF_VARS', 'value': v, 'type': 'PLAINTEXT'}]
    return 'cb:' + cb.start_build(projectName=TF_PROJECT, environmentVariablesOverride=env)['build']['id']


def terraform_plan(a, u):
    return _started(_tf('plan', a), 'Terraform plan (no changes are made)')


def terraform_apply(a, u):
    job = _tf('apply', a)
    _audit(a, u, 'terraform apply module %s vars [%s] -> %s' % (a['module'], a.get('vars', ''), job))
    return _started(job, 'Terraform apply')


# ---------------- migration ----------------
def migrate_create_image(a, u):
    inst = _inst(a['host'])
    r = ec2.create_image(InstanceId=inst['id'], Name='matrix-%s-%d' % (inst['host'], int(time.time())), NoReboot=str(a.get('reboot', '')).lower() != 'yes',
                         TagSpecifications=[{'ResourceType': 'image', 'Tags': [{'Key': 'CreatedBy', 'Value': 'MATRIX'}, {'Key': 'Source', 'Value': inst['host']}]}])
    _audit(a, u, 'image of %s -> %s' % (inst['host'], r['ImageId']))
    return _started('ami:' + r['ImageId'], 'Image creation (crash-consistent unless reboot=yes)')


def _real_image(host, image):
    """The image id if it exists, else the newest available image MATRIX made of this server ('' if none)."""
    try:
        im = ec2.describe_images(ImageIds=[image])['Images']
        if im:
            return image
    except Exception:
        pass
    try:
        mine = ec2.describe_images(Owners=['self'], Filters=[{'Name': 'tag:Source', 'Values': [host]}])['Images']
    except Exception:
        return ''
    mine = [i for i in mine if i['State'] == 'available'] or mine
    return max(mine, key=lambda i: i.get('CreationDate', ''))['ImageId'] if mine else ''


def _launch_label(a):
    img = _real_image(a['host'], str(a.get('image_id', ''))) or str(a.get('image_id', ''))
    return 'Launch %s in %s as a clone of %s from %s' % (a['new_name'], a['az'], a['host'], img)


def migrate_launch(a, u):
    src = _inst(a['host'])
    image, az = str(a.get('image_id', '')), str(a.get('az', ''))
    name = re.sub(r'[^A-Za-z0-9-]', '', str(a.get('new_name', '')))[:40]
    itype = str(a.get('type', '')) or src['type']
    if not re.fullmatch(r'ami-[0-9a-f]{8,17}', image) or not re.fullmatch(r'[a-z]{2}-[a-z]+-\d[a-z]', az) or not name:
        raise RuntimeError('Need image_id (ami-...), az (for example ap-southeast-2a) and new_name')
    if itype not in ALLOWED_TYPES:
        raise RuntimeError('Instance type not allowed. Allowed: ' + ', '.join(ALLOWED_TYPES))
    try:
        im = ec2.describe_images(ImageIds=[image])['Images']
    except Exception:
        im = []
    if not im:
        # the model sometimes writes an image id that does not exist; use the newest real image MATRIX made of this server
        mine = ec2.describe_images(Owners=['self'], Filters=[{'Name': 'tag:Source', 'Values': [src['host']]}])['Images']
        mine = [i for i in mine if i['State'] == 'available'] or mine
        if mine:
            im = [max(mine, key=lambda i: i.get('CreationDate', ''))]
            image = im[0]['ImageId']
    if not im or im[0]['State'] != 'available':
        raise RuntimeError('Image %s is not available yet. Check job_status ami:%s' % (image, image))
    d = ec2.describe_instances(InstanceIds=[src['id']])['Reservations'][0]['Instances'][0]
    subs = ec2.describe_subnets(Filters=[{'Name': 'vpc-id', 'Values': [d['VpcId']]}, {'Name': 'availability-zone', 'Values': [az]}])['Subnets']
    if not subs:
        raise RuntimeError('No subnet in %s in the same VPC as %s' % (az, src['host']))
    tags = [{'Key': 'Name', 'Value': name}, {'Key': 'CreatedBy', 'Value': 'MATRIX'}, {'Key': 'MigratedFrom', 'Value': src['host']}]
    tags += [t for t in d.get('Tags', []) if t['Key'] == 'Environment']
    # tagged like every other MATRIX server, so health checks, cutover and later fixes are allowed on the clone
    have = {t['Key'] for t in tags}
    try:
        env_tag = _env(src['id'])
    except Exception:
        env_tag = os.environ.get('ENVIRONMENT', 'dev')
    if env_tag in ('', 'unknown'):
        env_tag = os.environ.get('ENVIRONMENT', 'dev')
    for k, v in (('matrix-managed', 'true'), ('environment', env_tag), ('change', str(a.get('number', '')) or 'migration')):
        if k not in have:
            tags.append({'Key': k, 'Value': v})
    kw = dict(ImageId=image, InstanceType=itype, MinCount=1, MaxCount=1, SubnetId=subs[0]['SubnetId'],
              SecurityGroupIds=[g['GroupId'] for g in d['SecurityGroups']], TagSpecifications=[{'ResourceType': 'instance', 'Tags': tags}])
    if d.get('IamInstanceProfile'):
        kw['IamInstanceProfile'] = {'Arn': d['IamInstanceProfile']['Arn']}
    new = ec2.run_instances(**kw)['Instances'][0]['InstanceId']
    _audit(a, u, 'launched %s (%s) in %s as clone of %s' % (name, new, az, src['host']))
    return 'Launched %s as %s in %s from %s. The original %s is untouched; stop it yourself after you verify the new server.' % (name, new, az, image, src['host'])


BLOCKED = ('/etc', '/proc', '/sys', '/dev', '/boot', '/root', '/bin', '/sbin', '/usr', '/lib', '/run')


def _sync_cmd(a):
    d = str(a.get('direction', '')).lower()
    path = str(a.get('path', '')).rstrip('/') or '/'
    prefix = str(a.get('prefix', ''))
    if d not in ('up', 'down'):
        raise RuntimeError('direction must be up (server to S3) or down (S3 to server)')
    if not re.fullmatch(r'/[A-Za-z0-9_./-]{1,120}', path) or '..' in path or path == '/' or any(path == b or path.startswith(b + '/') for b in BLOCKED):
        raise RuntimeError('Path not allowed. Use an absolute data path such as /data/app (system folders are blocked).')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', prefix):
        raise RuntimeError('prefix must be letters, digits, _ or -')
    if not OPS_BUCKET:
        raise RuntimeError('OPS_BUCKET is not configured')
    uri = 's3://%s/migrations/%s/' % (OPS_BUCKET, prefix)
    cmd = ('aws s3 sync %s %s --only-show-errors && echo "synced up"' % (path, uri)) if d == 'up' else \
          ('mkdir -p %s && aws s3 sync %s %s --only-show-errors && echo "synced down"' % (path, uri, path))
    return d, path, prefix, cmd


def data_sync_check(a):
    d, path, prefix, _ = _sync_cmd(a)
    _guard(_inst(a['host']), a, 'Data migration')
    if d == 'up':
        return 'Copy %s on %s up to the ops bucket under %s' % (path, a['host'], prefix)
    return 'Copy ops bucket data %s down into %s on %s' % (prefix, path, a['host'])


def data_sync(a, u):
    d, path, prefix, cmd = _sync_cmd(a)
    inst = _inst(a['host'])
    job = _send(inst, 'AWS-RunShellScript', {'commands': [cmd]}, 'MATRIX data sync ' + d)
    _audit(a, u, 'data sync %s %s on %s prefix %s -> %s' % (d, path, inst['host'], prefix, job))
    return _started(job, 'Data sync')


# ---------------- install ----------------
def install(g):
    G.update(g)
    fn = g['_fn']
    H, N = g['ARG_HOST'], g['ARG_NUM']
    opt = ('number',)
    # read-only (run immediately)
    g['READ'].update({
        'cmdb_lookup': cmdb_lookup, 'kb_search': kb_search, 'ops_catalog': catalog, 'job_status': job_status,
        'patch_scan': patch_scan, 'playbook_check': playbook_check, 'terraform_plan': terraform_plan,
    })
    # change something (wait for the Confirm button)
    g['WRITE'].update({
        'patch_install': (patch_install_check, patch_install),
        'run_playbook': (playbook_run_check, playbook_run),
        'terraform_apply': (lambda a: 'Terraform APPLY module %s with [%s]' % (a['module'], a.get('vars', '')), terraform_apply),
        'migrate_create_image': (lambda a: 'Create an image (AMI) of %s' % a['host'], migrate_create_image),
        'migrate_launch': (_launch_label, migrate_launch),
        'data_sync': (data_sync_check, data_sync),
    })
    g['TOOLS'].extend([
        fn('cmdb_lookup', 'Look up a server in the ServiceNow CMDB (owner, environment, support group).', {'host': H}),
        fn('kb_search', 'Search published ServiceNow knowledge articles (runbooks, SOPs).', {'text': 'Search text'}),
        fn('ops_catalog', 'List the playbooks, Terraform modules and instance types this console may use.'),
        fn('job_status', 'Progress and output of a long job. Pass the job id returned by another tool.', {'job': 'Job id such as ssm:..., cb:... or ami:...'}),
        fn('patch_scan', 'Scan a server for missing OS patches (read-only). Returns a job id.', {'host': H}),
        fn('patch_install', 'Install OS patches via SSM Patch Manager. Needs confirmation. Non-dev servers need a change number: call create_change_request first and pass its CHG number.',
           {'host': H, 'reboot': 'yes or no (default no)', 'number': N}, opt=('reboot', 'number')),
        fn('playbook_check', 'Dry-run an Ansible playbook in check mode (read-only). Returns a job id.',
           {'host': H, 'playbook': 'Playbook name from ops_catalog', 'extra_vars': 'Optional key=value pairs separated by spaces'}, opt=('extra_vars',)),
        fn('run_playbook', 'Run an Ansible playbook (deploy, configure, patch app). Needs confirmation. Run playbook_check first.',
           {'host': H, 'playbook': 'Playbook name from ops_catalog', 'extra_vars': 'Optional key=value pairs separated by spaces', 'number': N}, opt=('extra_vars', 'number')),
        fn('terraform_plan', 'Run terraform plan for an allowed module (no changes). Returns a job id.',
           {'module': 'Module name from ops_catalog', 'vars': 'Optional comma separated key=value pairs'}, opt=('vars',)),
        fn('terraform_apply', 'Run terraform apply to create or change infrastructure, such as a new server. Needs confirmation. Show the plan result first.',
           {'module': 'Module name from ops_catalog', 'vars': 'Optional comma separated key=value pairs'}, opt=('vars',)),
        fn('migrate_create_image', 'Step 1 of moving a server: create an AMI of it. Needs confirmation. Returns an ami: job id.',
           {'host': H, 'reboot': 'yes for a consistent image, no (default) for a live image', 'number': N}, opt=('reboot', 'number')),
        fn('migrate_launch', 'Step 2 of moving a server: launch a clone from the AMI in another AZ or size in the same VPC. Needs confirmation. Wait until job_status says the image is available.',
           {'host': H, 'image_id': 'AMI id from step 1', 'az': 'Target AZ, for example ap-southeast-2a', 'new_name': 'Name tag for the new server', 'type': 'Optional instance type'}, opt=('type',)),
        fn('data_sync', 'Copy a data folder through the ops S3 bucket: direction up on the source server, then down on the target server with the same prefix. Needs confirmation.',
           {'host': H, 'direction': 'up or down', 'path': 'Absolute data folder, for example /data/app', 'prefix': 'Migration label shared by the up and down steps', 'number': N}, opt=('number',)),
    ])
    g['CHAT_SYSTEM'] += (
        " Operations tools: patch_scan and patch_install for patching, playbook_check and run_playbook for Ansible deployments and configuration, "
        "terraform_plan and terraform_apply to create servers or other infrastructure, migrate_create_image then migrate_launch to move a server to another AZ or size, "
        "and data_sync (up on the source, then down on the target, same prefix) to move data. "
        "Always run the read-only check first (patch_scan, playbook_check, terraform_plan) and summarise it before proposing the change. "
        "Before changing a server call cmdb_lookup, and use kb_search for the approved runbook when one may exist. "
        "Long jobs return a job id: use job_status and never say a job finished until job_status shows Success or Complete. "
        "For planned work on servers that are not Development, call create_change_request yourself and pass the returned CHG number as number. Never ask the engineer for a change number, error log or plan.")

    orig_openai, orig_run, orig_chat, orig_confirm = g['_openai'], g['_run_tool'], g['a_chat'], g['a_chat_confirm']

    def _openai(messages):
        t0 = time.time()
        try:
            r = orig_openai(messages)
        except Exception as e:
            ev('llm_error', g['OPENAI_MODEL'], {'error': str(e)[:300]}, t0)
            raise
        us = r.get('usage') or {}
        m = r['choices'][0]['message']
        T['pt'] = T.get('pt', 0) + int(us.get('prompt_tokens', 0)); T['ct'] = T.get('ct', 0) + int(us.get('completion_tokens', 0))
        _mm = T.setdefault('models', {}).setdefault(r.get('model') or g['OPENAI_MODEL'], {'calls': 0, 'in': 0, 'out': 0})
        _mm['calls'] += 1; _mm['in'] += int(us.get('prompt_tokens', 0)); _mm['out'] += int(us.get('completion_tokens', 0))
        ev('llm', r.get('model') or g['OPENAI_MODEL'], {'prompt_tokens': us.get('prompt_tokens', 0), 'completion_tokens': us.get('completion_tokens', 0),
                                      'calls': [c['function']['name'] for c in (m.get('tool_calls') or [])], 'text': (m.get('content') or '')[:600]}, t0)
        return r

    def _run_tool(name, args, u, pending):
        t0 = time.time()
        res = orig_run(name, args, u, pending)
        T['tools'] = T.get('tools', 0) + 1
        ev('tool', name, {'args': args, 'result': str(res)[:1500], 'waiting_for_confirm': str(res).startswith('NOT EXECUTED')}, t0)
        return res

    def a_chat(q, u):
        try:
            last = (json.loads(q.get('messages') or '[]') or [{}])[-1].get('content', '')
        except Exception:
            last = ''
        t_start('chat', u['u'], last)
        try:
            r = orig_chat(q, u)
        except Exception:
            t_end('error'); raise
        r['trace_id'] = T.get('id', '')
        t_end('ok' if r.get('ok') else 'error')
        return r

    def a_chat_confirm(q, u):
        t0 = time.time()
        try:
            tool = json.loads(g['b64d'](str(q.get('confirm', '')).split('.')[0])).get('t', '?')
        except Exception:
            tool = '?'
        t_start('confirm', u['u'], 'Confirmed: ' + tool)
        r = orig_confirm(q, u)
        ev('confirmed', tool, {'ok': r.get('ok'), 'result': str(r.get('text') or r.get('error'))[:1500]}, t0)
        r['trace_id'] = T.get('id', '')
        t_end('ok' if r.get('ok') else 'error')
        return r

    g['_openai'], g['_run_tool'] = _openai, _run_tool
    g['ACTIONS'].update({'chat': a_chat, 'chat_confirm': a_chat_confirm, 'traces': a_traces, 'trace': a_trace})
