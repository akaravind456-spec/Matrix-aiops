"""MATRIX knowledge base / RAG. Add after the other installs at the end of your Lambda file:

    import aiops, autonomy, rag
    aiops.install(globals()); autonomy.install(globals()); rag.install(globals())

Storage (all in OPS_BUCKET, no extra service):
  kb/docs/<name>        the original runbook / SOP / playbook text
  kb/index.json         chunks used for retrieval
  playbooks/<name>.yml  Ansible playbooks (uploaded with type=playbook, usable by run_playbook straight away)
Retrieval is BM25 keyword search (free, no key). If you set EMBED_URL / EMBED_MODEL / EMBED_KEY (any OpenAI-compatible /embeddings endpoint),
chunks also get vectors and results are re-ranked with cosine similarity. Confidence = share of the query's weighted terms found in the best chunk (0 to 1).
Env: RAG_MIN (default 0.5, minimum confidence for the agent to act), RAG_REQUIRED (default 1: with no matching runbook the agent escalates).
"""
import json, math, os, re, time, urllib.request
from collections import Counter
import boto3
import aiops as AI

REGION = os.environ.get('AWS_REGION', 'ap-southeast-2')
BUCKET = os.environ.get('OPS_BUCKET', '').strip()
EMBED_URL, EMBED_MODEL, EMBED_KEY = (os.environ.get(k, '').strip() for k in ('EMBED_URL', 'EMBED_MODEL', 'EMBED_KEY'))
RAG_MIN = float(os.environ.get('RAG_MIN', '0.5'))
RAG_REQUIRED = os.environ.get('RAG_REQUIRED', '1') != '0'
STOP = set('the a an and or of to in on is it for with at by from this that are was be as not no if then when'.split())
TYPES = ('runbook', 'sop', 'playbook')
s3 = boto3.client('s3', region_name=REGION)
G = {}


def tok(s):
    return [w[:-1] if len(w) > 3 and w.endswith('s') else w for w in re.findall(r'[a-z0-9]+', str(s).lower()) if w not in STOP and len(w) > 1]


def _get(key):
    try:
        return s3.get_object(Bucket=BUCKET, Key=key)['Body'].read()
    except Exception:
        return None


def _put(key, data, meta=None):
    s3.put_object(Bucket=BUCKET, Key=key, Body=data if isinstance(data, bytes) else data.encode(), **({'Metadata': meta} if meta else {}))


def _index():
    raw = _get('kb/index.json')
    return json.loads(raw) if raw else {'chunks': []}


def chunk(text):
    out = []
    for p in re.split(r'\n(?=#{1,3} )', text):
        p = p.strip()
        while len(p) > 1200:
            cut = p.rfind('\n', 0, 1000)
            cut = cut if cut > 200 else 1000
            out.append(p[:cut]); p = p[cut:].strip()
        if p:
            out.append(p)
    return out


def embed(texts):
    if not (EMBED_URL and EMBED_KEY and EMBED_MODEL):
        return None
    try:
        req = urllib.request.Request(EMBED_URL, data=json.dumps({'model': EMBED_MODEL, 'input': texts}).encode(), method='POST',
                                     headers={'Authorization': 'Bearer ' + EMBED_KEY, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=40) as r:
            return [[round(x, 4) for x in d['embedding']] for d in json.loads(r.read())['data']]
    except Exception:
        return None


def retrieve(query, k=4):
    ch = _index()['chunks']
    q = list(dict.fromkeys(tok(query)))
    if not ch or not q:
        return []
    docs = [Counter(tok(c['doc'] + ' ' + c['text'])) for c in ch]
    N, avg = len(ch), sum(sum(d.values()) for d in docs) / len(ch)
    idf = {w: math.log(1 + (N - sum(1 for d in docs if w in d) + .5) / (sum(1 for d in docs if w in d) + .5)) for w in q}
    total = sum(idf.values()) or 1
    res = []
    for c, d in zip(ch, docs):
        ln = sum(d.values())
        bm = sum(idf[w] * d[w] * 2.2 / (d[w] + 1.2 * (.25 + .75 * ln / avg)) for w in q if w in d)
        res.append({'doc': c['doc'], 'text': c['text'], 'score': bm, 'coverage': sum(idf[w] for w in q if w in d) / total, 'vec': c.get('vec')})
    qv = embed([query])
    if qv and any(r['vec'] for r in res):
        def cos(a, b):
            return sum(x * y for x, y in zip(a, b)) / ((math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))) or 1)
        vr = {id(r): i for i, r in enumerate(sorted((r for r in res if r['vec']), key=lambda r: -cos(qv[0], r['vec'])))}
        br = {id(r): i for i, r in enumerate(sorted(res, key=lambda r: -r['score']))}
        for r in res:
            r['score'] = 1 / (60 + br[id(r)]) + (1 / (60 + vr[id(r)]) if id(r) in vr else 0)
    res = [r for r in sorted(res, key=lambda r: -r['score']) if r['coverage'] > 0][:k]
    return [{k_: v for k_, v in r.items() if k_ != 'vec'} for r in res]


# ---------------- actions for the frontend ----------------
def _name(q):
    n = str(q.get('name', '')).strip()
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,80}\.(md|txt|yml|yaml)', n):
        raise RuntimeError('Name must be letters, digits, . _ - and end in .md, .txt, .yml or .yaml')
    return n


def a_kb_list(q, u):
    out = []
    for o in s3.list_objects_v2(Bucket=BUCKET, Prefix='kb/docs/').get('Contents', []):
        h = s3.head_object(Bucket=BUCKET, Key=o['Key'])
        out.append({'name': o['Key'][8:], 'type': h.get('Metadata', {}).get('type', 'runbook'), 'size': o['Size'], 'updated': str(o['LastModified'])[:19]})
    return {'ok': True, 'docs': out}


def a_kb_get(q, u):
    raw = _get('kb/docs/' + _name(q))
    return {'ok': True, 'text': raw.decode('utf8', 'ignore')[:30000]} if raw is not None else {'ok': False, 'error': 'Not found'}


def a_kb_upload(q, u):
    if u.get('role') == 'AGENT':
        return {'ok': False, 'error': 'Only a human can change the knowledge base'}
    name, typ, text = _name(q), str(q.get('type', 'runbook')), str(q.get('content', ''))
    if typ not in TYPES or not text.strip() or len(text) > 200000:
        return {'ok': False, 'error': 'type must be runbook, sop or playbook, and content must be 1 to 200000 characters'}
    if typ == 'playbook' and not name.endswith('.yml'):
        return {'ok': False, 'error': 'Playbooks must be named <name>.yml'}
    _put('kb/docs/' + name, text, {'type': typ})
    if typ == 'playbook':
        _put('playbooks/' + name, text)
    idx = _index()
    idx['chunks'] = [c for c in idx['chunks'] if c['doc'] != name]
    parts = chunk(text)
    vecs = embed([name + ' ' + p for p in parts])
    for i, p in enumerate(parts):
        c = {'doc': name, 'text': p}
        if vecs:
            c['vec'] = vecs[i]
        idx['chunks'].append(c)
    _put('kb/index.json', json.dumps(idx))
    sync_playbooks()
    return {'ok': True, 'text': '%s saved: %d chunks indexed%s.' % (name, len(parts), ' with embeddings' if vecs else ' (keyword search)')}


def a_kb_delete(q, u):
    if u.get('role') == 'AGENT':
        return {'ok': False, 'error': 'Only a human can change the knowledge base'}
    name = _name(q)
    for k in ('kb/docs/' + name, 'playbooks/' + name):
        s3.delete_object(Bucket=BUCKET, Key=k)
    idx = _index()
    idx['chunks'] = [c for c in idx['chunks'] if c['doc'] != name]
    _put('kb/index.json', json.dumps(idx))
    sync_playbooks()
    return {'ok': True, 'text': name + ' deleted'}


def a_kb_search(q, u):
    return {'ok': True, 'hits': [{'doc': h['doc'], 'confidence': round(h['coverage'], 2), 'text': h['text'][:500]} for h in retrieve(q.get('q', ''))]}


def sync_playbooks():
    try:
        names = {o['Key'][10:-4] for o in s3.list_objects_v2(Bucket=BUCKET, Prefix='playbooks/').get('Contents', []) if o['Key'].endswith('.yml')}
        AI.PLAYBOOKS[:] = sorted(set(AI.PLAYBOOKS) | names)
    except Exception:
        pass


# ---------------- LLM tools ----------------
def tool_search(a, u):
    hits = retrieve(a.get('text', ''))
    if hits:
        return '\n\n'.join('[%s, confidence %.2f]\n%s' % (h['doc'], h['coverage'], h['text'][:900]) for h in hits)[:3000]
    return AI.kb_search(a, u)


def tool_read(a, u):
    r = a_kb_get({'name': a.get('name', '')}, u)
    return r.get('text', r.get('error'))[:6000]


def install(g):
    G.update(g)
    g['READ']['kb_search'] = tool_search
    g['READ']['kb_read'] = tool_read
    g['TOOLS'].append(g['_fn']('kb_read', 'Read one full runbook, SOP or playbook from the knowledge base by file name.', {'name': 'File name from kb_search results, for example nginx-down.md'}))
    g['CHAT_SYSTEM'] += (" Before acting on an operational task, call kb_search for the approved runbook and follow it. "
                         "If no runbook matches, say so and offer to escalate to an L2 engineer instead of improvising.")
    g['ACTIONS'].update({'kb_list': a_kb_list, 'kb_get': a_kb_get, 'kb_upload': a_kb_upload, 'kb_delete': a_kb_delete, 'kb_search': a_kb_search})
    orig = g['handler']

    def handler(event, context):
        sync_playbooks()
        return orig(event, context)
    g['handler'] = handler
