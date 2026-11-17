"""After an engineer presses Confirm on a chat change that carries an INC number:
add one bullet-style work note and resolve the incident. Install before learning.install(g)."""
import json, re


def install(g):
    orig = g['a_chat_confirm']

    def a_chat_confirm(q, u):
        r = orig(q, u)
        try:
            d = json.loads(g['b64d'](str(q.get('confirm', '')).split('.')[0]))
            tool, a = d['t'], d['a']
            num = re.sub(r'[^A-Za-z0-9]', '', str(a.get('number', '')))
            if not (r.get('ok') and num.startswith('INC')):
                return r
            # ServiceNow record edits and planned-work tools must never auto-resolve the incident they were filed under
            if tool.startswith(('snow_', 'patch_', 'migration_', 'deployment_', 'decommission_')):
                return r
            # long jobs (AMI, patching, terraform) are not finished yet: leave the ticket open
            if re.search(r'Job id:', r.get('text') or '') or tool in ('migrate_create_image', 'migrate_launch', 'terraform_apply', 'patch_install', 'run_playbook', 'data_sync'):
                sid = g['sys_id_of'](num)
                first = (r.get('text') or '').strip().splitlines()[0][:140]
                g['sn']('PATCH', 'incident/' + sid, body={'work_notes': '[MATRIX AI] Started\n- Action: %s on %s\n- Confirmed by: %s\n- Result: %s\n- Status: In progress, ticket stays open' % (tool, a.get('host', '-'), u['name'], first)})
                r['text'] = (r.get('text') or '') + '\n\nWork note added to %s. Ticket stays open until the job finishes.' % num
                return r
            sid = g['sys_id_of'](num)
            first = (r.get('text') or '').strip().splitlines()[0][:140]
            g['sn']('PATCH', 'incident/' + sid, body={
                'state': '6', 'close_code': g['CLOSE_CODE'],
                'close_notes': 'MATRIX AI auto-resolved: %s completed on %s, confirmed by %s.' % (tool, a.get('host', '-'), u['name']),
                'work_notes': '[MATRIX AI] Done\n- Action: %s on %s\n- Confirmed by: %s\n- Result: %s\n- Status: Resolved' % (tool, a.get('host', '-'), u['name'], first)})
            r['text'] = (r.get('text') or '') + '\n\n%s resolved and work note added.' % num
        except Exception as e:
            r['text'] = (r.get('text') or '') + '\n(Could not update ServiceNow: %s)' % str(e)[:100]
        return r

    g['ACTIONS']['chat_confirm'] = a_chat_confirm
