"""Upload the runbooks in ../runbooks to MATRIX, so they are saved in the ServiceNow knowledge base and found by the agent.

It signs in to your MATRIX console as YOU, so nothing here stores a password. Set these in your own terminal first:

    set MATRIX_URL=https://<your-console-function-url>/        (the Lambda Function URL the console talks to)
    set MATRIX_USER=<your console username>
    set MATRIX_PASS=<your console password>

Run:
    python tools/upload_runbooks.py            shows what would be uploaded (nothing is changed)
    python tools/upload_runbooks.py --go       uploads the runbooks that are not already in the knowledge base

An article with the same title that is already in ServiceNow is skipped, so it is safe to run twice.
"""
import json
import os
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, '..', 'runbooks')


def call(url, **fields):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, method='POST', headers={'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read())


def main():
    go = '--go' in sys.argv
    url, user, pw = (os.environ.get(k, '').strip() for k in ('MATRIX_URL', 'MATRIX_USER', 'MATRIX_PASS'))
    if not (url and user and pw):
        sys.exit('Set MATRIX_URL, MATRIX_USER and MATRIX_PASS first (see the top of this file).')
    files = sorted(f for f in os.listdir(DIR) if f.endswith('.md'))
    login = call(url, action='login', username=user, password=pw)
    if not login.get('ok'):
        sys.exit('Sign-in failed: %s' % login.get('error'))
    token = login['token']
    have = {a['title'].strip().lower() for a in call(url, action='snow_kb_list', token=token).get('articles', [])}
    for f in files:
        text = open(os.path.join(DIR, f), encoding='utf-8').read()
        title = text.splitlines()[0].lstrip('# ').strip()
        if title.lower() in have:
            print('skip      %-45s already in the knowledge base' % title)
            continue
        if not go:
            print('would add %-45s (%s)' % (title, f))
            continue
        r = call(url, action='kb_publish', token=token, type='runbook', title=title, content=text)
        print('%-9s %-45s %s' % ('added' if r.get('ok') else 'FAILED', title, r.get('number') or r.get('error', '')))
        if r.get('ok') and not r.get('agent_copy'):
            print('          warning: the agent search copy was not updated:', r.get('agent_copy_error', ''))
    if not go:
        print('\nNothing was changed. Run again with --go to upload.')


if __name__ == '__main__':
    main()
