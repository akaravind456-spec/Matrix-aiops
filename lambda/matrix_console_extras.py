"""MATRIX console extras. Install in lambda_function.py after matrix_ops_install and before learning:

    import matrix_console_extras
    matrix_console_extras.install(g)

Adds these console actions
  llm_cost         tokens per model from the traces, multiplied by a price table: no typing prices by hand
  prices           the resolved price for a list of model names
  snow_kb_list     knowledge articles in ServiceNow (all knowledge bases the integration user can read)
  snow_kb_get      one article as plain text
  ssm_docs_list    AWS Systems Manager documents owned by this account
  ssm_doc_get      one document's content
  kb_publish       one upload box: a SOP or runbook goes to the ServiceNow knowledge base, an executable playbook goes to an AWS SSM document

Prices: built-in defaults below, overridden by the LLM_PRICES environment variable, a JSON object such as
  {"openai/gpt-oss-120b": {"in": 0.15, "out": 0.60}, "my-provider/*": {"in": 1, "out": 3, "note": "contract price"}}
Prices are US dollars per 1M tokens. A key ending in * matches every model that starts with it.
A model with no price shows "price not set". It is never shown as $0.00.

Environment: KB_NAME is the ServiceNow knowledge base that uploads go to (default 'AI SRE Runbooks').
"""
import html
import json
import os
import re

import boto3

G = {}
REGION = os.environ.get('AWS_REGION', 'ap-southeast-2')
KB_NAME = os.environ.get('KB_NAME', 'AI SRE Runbooks')
PB_PREFIX = 'MATRIX-PB-'

# list prices in USD per 1M tokens. Verify them against your provider before relying on them for billing.
DEFAULT_PRICES = {
    'openai/gpt-oss-120b': {'in': 0.15, 'out': 0.60, 'note': 'Groq list price'},
    'openai/gpt-oss-20b': {'in': 0.075, 'out': 0.30, 'note': 'Groq list price'},
    'nvidia/*': {'in': 0.0, 'out': 0.0, 'note': 'NVIDIA free endpoint (rate limited)'},
}


# ---------------------------------------------------------------- prices
def _norm(v):
    if isinstance(v, (list, tuple)) and len(v) >= 2:
        v = {'in': v[0], 'out': v[1]}
    if not isinstance(v, dict):
        return None
    try:
        return {'in': float(v['in']), 'out': float(v['out']), 'note': str(v.get('note', ''))[:80]}
    except (KeyError, TypeError, ValueError):
        return None


def price_table():
    table = {k: _norm(v) for k, v in DEFAULT_PRICES.items()}
    try:
        extra = json.loads(os.environ.get('LLM_PRICES', '') or '{}')
        for k, v in (extra.items() if isinstance(extra, dict) else []):
            n = _norm(v)
            if n:
                table[str(k)] = dict(n, note=n['note'] or 'set in LLM_PRICES')
    except ValueError:
        pass
    return table


def price_for(model, table=None):
    """Exact match first (environment before defaults), then the longest matching prefix*. None when unknown."""
    table = table or price_table()
    if model in table:
        return table[model]
    best = None
    for k, v in table.items():
        if k.endswith('*') and model.startswith(k[:-1]) and (best is None or len(k) > len(best[0])):
            best = (k, v)
    return best[1] if best else None


def cost_rows(models, table=None):
    """models: [{model, calls, in, out}] -> rows with price and cost, plus the known total and the models with no price."""
    table = table or price_table()
    rows, total, unknown = [], 0.0, []
    for m in models:
        p = price_for(m['model'], table)
        cost = None
        if p:
            cost = (m.get('in', 0) * p['in'] + m.get('out', 0) * p['out']) / 1e6
            total += cost
        else:
            unknown.append(m['model'])
        rows.append({'model': m['model'], 'calls': m.get('calls', 0), 'in': m.get('in', 0), 'out': m.get('out', 0),
                     'price_in': p['in'] if p else None, 'price_out': p['out'] if p else None, 'note': p['note'] if p else '', 'cost': round(cost, 6) if cost is not None else None})
    return {'rows': rows, 'total': round(total, 6), 'unknown': unknown}


def a_llm_cost(q, u):
    try:
        days = min(max(int(q.get('days') or 7), 1), 90)
    except (TypeError, ValueError):
        days = 7
    o = G['ACTIONS']['obs']({'days': days}, u)
    if not o.get('ok'):
        return o
    res = cost_rows(o.get('models') or [])
    res.update(ok=True, days=days, currency='USD', note='Dollars = tokens x the price table. Change prices with the LLM_PRICES setting.')
    return res


def a_prices(q, u):
    try:
        names = json.loads(q.get('models') or '[]')
    except ValueError:
        names = []
    t = price_table()
    return {'ok': True, 'prices': {str(n): price_for(str(n), t) for n in names[:50]}}


# ---------------------------------------------------------------- ServiceNow knowledge base
def _slug(text, n=60):
    return re.sub(r'-{2,}', '-', re.sub(r'[^a-z0-9]+', '-', str(text).lower())).strip('-')[:n] or 'document'


def _val(x):
    return x.get('display_value', x.get('value', '')) if isinstance(x, dict) else (x or '')


def a_snow_kb_list(q, u):
    try:
        rows = G['sn']('GET', 'kb_knowledge', {'sysparm_query': 'ORDERBYDESCsys_updated_on', 'sysparm_limit': '100', 'sysparm_display_value': 'true',
                                               'sysparm_fields': 'number,short_description,workflow_state,kb_knowledge_base,author,sys_updated_on'}) or []
    except Exception as e:
        return {'ok': False, 'error': str(e)[:250]}
    return {'ok': True, 'articles': [{'number': _val(r.get('number')), 'title': _val(r.get('short_description')), 'state': _val(r.get('workflow_state')),
                                      'kb': _val(r.get('kb_knowledge_base')), 'author': _val(r.get('author')), 'updated': _val(r.get('sys_updated_on'))} for r in rows],
            'kb_name': KB_NAME}


def a_snow_kb_get(q, u):
    num = re.sub(r'[^A-Za-z0-9]', '', str(q.get('number', '')))
    if not re.fullmatch(r'KB\d{4,}', num):
        return {'ok': False, 'error': 'Give a knowledge article number like KB0010001'}
    try:
        r = G['sn']('GET', 'kb_knowledge', {'sysparm_query': 'number=' + num, 'sysparm_limit': '1', 'sysparm_fields': 'number,short_description,text'}) or []
    except Exception as e:
        return {'ok': False, 'error': str(e)[:250]}
    if not r:
        return {'ok': False, 'error': num + ' not found'}
    return {'ok': True, 'number': num, 'title': r[0].get('short_description', ''), 'text': G['kb_clean'](r[0].get('text', '')).strip()[:30000]}


def _kb_base_id():
    r = G['sn']('GET', 'kb_knowledge_base', {'sysparm_query': 'title=' + re.sub(r'[\^=]', ' ', KB_NAME), 'sysparm_limit': '1', 'sysparm_fields': 'sys_id'}) or []
    if not r:
        raise RuntimeError("ServiceNow knowledge base '%s' was not found. Create it, or set KB_NAME to an existing one." % KB_NAME)
    return G['raw'](r[0]['sys_id'])


def _to_html(text):
    return '<br>'.join(html.escape(line, quote=False) for line in str(text).replace('\r\n', '\n').split('\n'))


def snow_article(title, text, publish=True):
    """Create one article in the ServiceNow knowledge base. Returns its KB number. Raises on failure."""
    body = {'short_description': str(title)[:160], 'text': _to_html(text), 'kb_knowledge_base': _kb_base_id()}
    if publish:
        body['workflow_state'] = 'published'
    r = G['sn']('POST', 'kb_knowledge', body=body) or {}
    if publish and _val(r.get('workflow_state')) not in ('published', 'Published'):
        # ServiceNow often ignores workflow_state on insert and keeps a draft: publish it with a second call
        try:
            G['sn']('PATCH', 'kb_knowledge/' + G['raw'](r.get('sys_id')), body={'workflow_state': 'published'})
        except Exception as e:
            print('matrix_console_extras: could not publish %s: %s' % (_val(r.get('number')), str(e)[:150]))
    return _val(r.get('number')) or '(created)'


def a_kb_publish_drafts(q, u):
    """Publish every draft article in the runbook knowledge base so the agent and the Runbooks screen can use it."""
    rows = G['sn']('GET', 'kb_knowledge', {'sysparm_query': 'workflow_state=draft^kb_knowledge_base=' + _kb_base_id(), 'sysparm_limit': '100',
                                           'sysparm_fields': 'sys_id,number,short_description'}) or []
    done, failed = [], []
    for r in rows:
        try:
            G['sn']('PATCH', 'kb_knowledge/' + G['raw'](r['sys_id']), body={'workflow_state': 'published'})
            now = G['sn']('GET', 'kb_knowledge', {'sysparm_query': 'sys_id=' + G['raw'](r['sys_id']), 'sysparm_limit': '1', 'sysparm_fields': 'workflow_state'}) or []
            if now and _val(now[0].get('workflow_state')) == 'published':
                done.append(_val(r.get('number')))
            else:
                failed.append(_val(r.get('number')))
        except Exception as e:
            failed.append('%s: %s' % (_val(r.get('number')), str(e)[:120]))
    out = {'ok': True, 'drafts_found': len(rows), 'published': done, 'not_published': failed[:10]}
    if failed and not done:
        out['why'] = ('ServiceNow accepted the request but kept the articles as drafts. The integration user probably lacks the knowledge_admin role, '
                      'or the knowledge base has an approval step. Publish them in ServiceNow: Knowledge > Articles, select the drafts, then Publish.')
    return out


# ---------------------------------------------------------------- AWS Systems Manager documents
def _ssm():
    return boto3.client('ssm', region_name=REGION)


def _origin(name):
    if name.startswith('MATRIX-LEARNED-'):
        return 'Learned by MATRIX'
    if name.startswith(PB_PREFIX):
        return 'Uploaded from the console'
    if name.startswith('MATRIX_'):
        return 'MATRIX playbook'
    return 'Other'


def a_ssm_docs_list(q, u):
    try:
        ssm, out, token = _ssm(), [], None
        while len(out) < 300:
            r = ssm.list_documents(Filters=[{'Key': 'Owner', 'Values': ['Self']}], MaxResults=50, **({'NextToken': token} if token else {}))
            for d in r.get('DocumentIdentifiers', []):
                out.append({'name': d['Name'], 'type': d.get('DocumentType', ''), 'version': d.get('DocumentVersion', ''), 'format': d.get('DocumentFormat', ''),
                            'created': str(d.get('CreatedDate', ''))[:19], 'origin': _origin(d['Name']),
                            'platforms': ', '.join(d.get('PlatformTypes') or [])})
            token = r.get('NextToken')
            if not token:
                break
    except Exception as e:
        return {'ok': False, 'error': str(e)[:250]}
    out.sort(key=lambda x: (x['origin'] == 'Other', x['name'].lower()))
    return {'ok': True, 'docs': out}


def a_ssm_doc_get(q, u):
    name = str(q.get('name', '')).strip()
    if not re.fullmatch(r'[A-Za-z0-9_.-]{3,128}', name):
        return {'ok': False, 'error': 'Invalid document name'}
    try:
        r = _ssm().get_document(Name=name)
    except Exception as e:
        return {'ok': False, 'error': str(e)[:250]}
    return {'ok': True, 'name': name, 'version': r.get('DocumentVersion', ''), 'format': r.get('DocumentFormat', ''), 'text': str(r.get('Content', ''))[:30000]}


def create_ssm_playbook(title, content, by):
    """Create an SSM Command document from a playbook. Never overwrites an existing document."""
    name = PB_PREFIX + _slug(title, 100)
    text = str(content)
    if text.lstrip().startswith('{'):
        fmt = 'JSON'
        try:
            d = json.loads(text)
        except ValueError as e:
            raise RuntimeError('The playbook is not valid JSON: %s' % e)
        if not isinstance(d, dict) or 'schemaVersion' not in d or 'mainSteps' not in d:
            raise RuntimeError('An SSM playbook needs schemaVersion and mainSteps')
    else:
        fmt = 'YAML'
        if not re.search(r'^schemaVersion\s*:', text, re.M) or not re.search(r'^mainSteps\s*:', text, re.M):
            raise RuntimeError('An SSM playbook needs schemaVersion and mainSteps (an Ansible playbook is not an SSM document)')
    tags = [{'Key': 'CreatedBy', 'Value': 'MATRIX-Console'}, {'Key': 'UploadedBy', 'Value': re.sub(r'[^\w+=.:/@ -]', '', str(by))[:100] or 'unknown'}]
    ssm = _ssm()
    try:
        ssm.create_document(Content=text, Name=name, DocumentType='Command', DocumentFormat=fmt, Tags=tags)
    except ssm.exceptions.DocumentAlreadyExists:
        raise RuntimeError('An AWS document named %s already exists. Use a different title.' % name)
    return name


# ---------------------------------------------------------------- one upload box
def a_kb_publish(q, u):
    if u.get('role') == 'AGENT':
        return {'ok': False, 'error': 'Only a human can add documents'}
    typ, title, content = str(q.get('type', '')).lower(), str(q.get('title', '')).strip(), str(q.get('content', ''))
    if typ not in ('sop', 'runbook', 'playbook'):
        return {'ok': False, 'error': 'type must be sop, runbook or playbook'}
    if not title or not content.strip() or len(content) > 200000:
        return {'ok': False, 'error': 'Give a title and content (up to 200000 characters)'}
    try:
        if typ == 'playbook':
            name = create_ssm_playbook(title, content, u.get('name') or u.get('u'))
            return {'ok': True, 'destination': 'aws_ssm', 'name': name,
                    'text': 'Created AWS Systems Manager document %s. Run it from Systems Manager, Run Command. To let the agent use it, add it to the allowed playbooks.' % name}
        number = snow_article(title, content)
        out = {'ok': True, 'destination': 'servicenow', 'number': number,
               'text': 'Saved to the ServiceNow knowledge base (%s) as %s, published.' % (KB_NAME, number)}
        try:  # a hidden copy so the agent's own search keeps finding it
            r = G['RAG'].a_kb_upload({'name': _slug(title) + '.md', 'type': typ, 'content': content}, u)
            out['agent_copy'] = bool(r.get('ok'))
        except Exception as e:
            out['agent_copy'] = False
            out['agent_copy_error'] = str(e)[:120]
        if not out['agent_copy']:
            out['text'] += ' The agent search copy could not be updated, so the agent will not use it yet.'
        return out
    except Exception as e:
        return {'ok': False, 'error': str(e)[:300]}


def install(g):
    import rag
    G.update(g)
    G['RAG'] = rag
    g['ACTIONS'].update({'llm_cost': a_llm_cost, 'prices': a_prices, 'snow_kb_list': a_snow_kb_list, 'snow_kb_get': a_snow_kb_get,
                         'ssm_docs_list': a_ssm_docs_list, 'ssm_doc_get': a_ssm_doc_get, 'kb_publish': a_kb_publish, 'kb_publish_drafts': a_kb_publish_drafts})
