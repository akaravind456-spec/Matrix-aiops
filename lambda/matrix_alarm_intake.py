"""Alarm intake inside the one MATRIX Lambda: CloudWatch alarm -> ServiceNow incident -> agent starts -> console notice.

Replaces the separate intake / create-ticket / starter functions. Two ways in, both handled by lambda_function.handler:

  1. EventBridge rule on "CloudWatch Alarm State Change" with state ALARM, target = this Lambda (instant).
  2. EventBridge schedule {"matrix_task": "alarm_sweep"} every 5 minutes (catches alarms that were missed, and shows what is active).

For each alarm in ALARM: skip if an open [MATRIX] incident already exists for that alarm, otherwise create the incident
(assignment group L1_GROUP, CI = the server), add a work note, tell the console, and start the agent (autonomy._kick).
Needs the same settings as before: SN_*, L1_GROUP, AGENT_KEY, TRACE_TABLE. ALARM_PREFIX (optional, comma list) limits which
alarm names create incidents, for example "MATRIX-,Disk-High". Leave it empty to react to every alarm.
"""
import os
import re

import boto3

import autonomy as AU

REGION = os.environ.get('AWS_REGION', 'ap-southeast-2')
PREFIXES = [p.strip() for p in os.environ.get('ALARM_PREFIX', '').split(',') if p.strip()]
MAX_PER_RUN = int(os.environ.get('ALARM_MAX_PER_RUN', '5'))
cw = boto3.client('cloudwatch', region_name=REGION)
ec2 = boto3.client('ec2', region_name=REGION)
G = {}


def _wanted(name):
    return not PREFIXES or any(name.startswith(p) for p in PREFIXES)


def _host(instance_id):
    if not instance_id:
        return ''
    try:
        r = ec2.describe_instances(InstanceIds=[instance_id])['Reservations'][0]['Instances'][0]
        return next((t['Value'] for t in r.get('Tags', []) if t['Key'] == 'Name'), instance_id)
    except Exception:
        return instance_id


def _instance_of_event(detail):
    for m in (detail.get('configuration') or {}).get('metrics', []):
        dims = ((m.get('metricStat') or {}).get('metric') or {}).get('dimensions') or {}
        if dims.get('InstanceId'):
            return dims['InstanceId']
    return ''


def _already_open(name):
    t = re.sub(r'[^\w .\-\[\]]', '', name)[:60]
    r = G['sn']('GET', 'incident', {'sysparm_query': 'stateIN1,2,3^short_descriptionLIKE[MATRIX]^short_descriptionLIKE' + t,   # resolved (6) and closed (7) tickets do not count as open
                                    'sysparm_limit': '1', 'sysparm_fields': 'number'}) or []
    return G['val'](r[0]['number']) if r else ''


def raise_incident(name, reason, instance_id=''):
    """Create the incident and start the agent. Returns a short result line (never raises)."""
    try:
        if not _wanted(name):
            return {'alarm': name, 'result': 'ignored (not in ALARM_PREFIX)'}
        have = _already_open(name)
        if have:
            return {'alarm': name, 'result': 'already open as ' + have}
        host = _host(instance_id)
        body = {'short_description': ('[MATRIX] ' + name)[:160], 'urgency': '2', 'impact': '2',
                'description': ('Alarm: %s\nInstance: %s (%s)\nReason: %s\nRaised automatically by MATRIX from CloudWatch.' % (name, host or '-', instance_id or '-', reason))[:3900]}
        gid = AU._group_id(AU.L1_GROUP)
        if gid:
            body['assignment_group'] = gid
        if host:
            cr = G['sn']('GET', 'cmdb_ci_server', {'sysparm_query': 'name=' + host, 'sysparm_limit': '1', 'sysparm_fields': 'sys_id'}) or []
            if cr:
                body['cmdb_ci'] = G['raw'](cr[0]['sys_id'])
        r = G['sn']('POST', 'incident', body=body)
        number, sid = G['raw'](r['number']), G['raw'](r['sys_id'])
        G['add_note'](sid, '[MATRIX] Created from CloudWatch alarm %s. Assigned to %s.' % (name, AU.L1_GROUP))
        AU.inbox_add('incident', number, '%s created from alarm %s%s.' % (number, name, (' on ' + host) if host else ''))
        started = AU._kick(number, host, name) if host else 'No server found for this alarm, so the agent was not started (assign it manually).'
        return {'alarm': name, 'number': number, 'result': 'created', 'agent': started}
    except Exception as e:
        return {'alarm': name, 'result': 'error: ' + str(e)[:200]}


def on_event(event):
    d = event.get('detail') or {}
    if (d.get('state') or {}).get('value') != 'ALARM':
        return {'ok': True, 'result': 'not an ALARM transition'}
    res = {'ok': True, **raise_incident(d.get('alarmName', 'unknown-alarm'), (d.get('state') or {}).get('reason', ''), _instance_of_event(d))}
    print('MATRIX-ALARM-INTAKE', res)   # visible in the CloudWatch log of this function
    return res


PLANNED_TITLE = r'^\[MATRIX\] (Migration|Deployment|Decommission|Operation|Patching|Resize|Other) of '


def pick_up_orphans():
    """Alarm tickets the agent never started on (for example the background start was cut off by a deploy): start it now.
    Only [MATRIX] alarm tickets 3 minutes to 1 day old, still New or In Progress, with no [MATRIX AI] note. Never planned-work tickets."""
    out = []
    try:
        rows = G['sn']('GET', 'incident', {
            'sysparm_query': 'stateIN1,2^short_descriptionSTARTSWITH[MATRIX]^sys_created_onRELATIVELE@minute@ago@3^sys_created_onRELATIVEGE@dayofweek@ago@1',
            'sysparm_limit': '10', 'sysparm_display_value': 'true', 'sysparm_fields': 'number,sys_id,short_description,cmdb_ci'}) or []
        for r in rows:
            title = G['val'](r.get('short_description'))
            if re.match(PLANNED_TITLE, title):
                continue
            sid = G['raw'](r['sys_id'])
            seen = G['sn']('GET', 'sys_journal_field', {'sysparm_query': 'element_id=%s^element=work_notes^valueLIKE[MATRIX AI]' % sid,
                                                          'sysparm_limit': '1', 'sysparm_fields': 'sys_id'}) or []
            if seen:
                continue
            host = G['val'](r.get('cmdb_ci'))
            if not host:
                continue
            alarm = re.sub(r'^\[MATRIX\]\s*', '', title)
            res = AU._kick(G['val'](r['number']), host, alarm)
            print('MATRIX-ORPHAN-PICKUP', G['val'](r['number']), res)
            out.append({'number': G['val'](r['number']), 'agent': res})
    except Exception as e:
        print('MATRIX-ORPHAN-PICKUP error: %s' % str(e)[:200])
    return out


def sweep():
    out, made = [], 0
    for p in cw.get_paginator('describe_alarms').paginate(AlarmTypes=['MetricAlarm'], StateValue='ALARM'):
        for a in p['MetricAlarms']:
            if made >= MAX_PER_RUN:
                return {'ok': True, 'results': out, 'note': 'stopped at ALARM_MAX_PER_RUN; the next sweep continues'}
            iid = next((d['Value'] for d in a.get('Dimensions', []) if d['Name'] == 'InstanceId'), '')
            r = raise_incident(a['AlarmName'], a.get('StateReason', ''), iid)
            print('MATRIX-ALARM-SWEEP', r)
            made += r.get('result') == 'created'
            out.append(r)
    return {'ok': True, 'results': out, 'picked_up': pick_up_orphans()}


def is_alarm_event(event):
    return isinstance(event, dict) and event.get('source') == 'aws.cloudwatch' and event.get('detail-type') == 'CloudWatch Alarm State Change'


def install(g):
    G.update(g)
