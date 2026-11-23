"""Signed licence key for the self-hosted edition.

A key looks like  MTX1.<payload>.<signature>  (base64url). The payload is JSON:
    {"c": customer, "a": AWS account id, "p": plan, "s": max servers (0 = unlimited), "u": max seats, "e": expiry (unix seconds), "n": serial}
The vendor signs it with a private key that is never shipped. This file holds only the PUBLIC key, so the product can check a key but
nobody can make or edit one. Changing the limits, the account or the expiry breaks the signature.

Honest limit: whoever owns the AWS account can still edit this code to skip the check. A compiled build makes that costly, and the
vendor-hosted edition (see IPR-001) removes it. This key stops casual copying, sharing between accounts and editing of limits.
"""
import base64
import json
import time

import matrix_ed25519 as ed

# The vendor's PUBLIC key (hex). It is deliberately a constant and not a setting, so it cannot be swapped by editing an environment variable.
PUBLIC_KEY_HEX = 'd63dcfca1dd58dd755beea82e5065395a0e83e439162bd4f1503eea7ae73afc4'
PREFIX = 'MTX1'


def _b64e(b):
    return base64.urlsafe_b64encode(b).decode().rstrip('=')


def _b64d(s):
    return base64.urlsafe_b64decode(str(s) + '=' * (-len(str(s)) % 4))


def make_key(secret, payload):
    """Vendor side only (see tools/matrix_licence_sign.py). secret = 32 bytes."""
    body = _b64e(json.dumps(payload, separators=(',', ':'), sort_keys=True).encode())
    sig = ed.sign(secret, (PREFIX + '.' + body).encode())
    return '%s.%s.%s' % (PREFIX, body, _b64e(sig))


def check(key, account_id='', now=None, public_hex=None):
    """Returns {'valid': bool, 'reason': str, 'claims': dict}. Never raises."""
    now = time.time() if now is None else now
    try:
        parts = str(key or '').strip().split('.')
        if len(parts) != 3 or parts[0] != PREFIX:
            return {'valid': False, 'reason': 'not a MATRIX licence key', 'claims': {}}
        pub = bytes.fromhex(public_hex or PUBLIC_KEY_HEX)
        if not ed.verify(pub, (parts[0] + '.' + parts[1]).encode(), _b64d(parts[2])):
            return {'valid': False, 'reason': 'the signature does not match (the key was changed or is not from the vendor)', 'claims': {}}
        claims = json.loads(_b64d(parts[1]))
        if not isinstance(claims, dict):
            return {'valid': False, 'reason': 'unreadable key', 'claims': {}}
    except Exception:
        return {'valid': False, 'reason': 'unreadable key', 'claims': {}}
    exp = claims.get('e')
    if isinstance(exp, (int, float)) and exp and now > exp:
        return {'valid': False, 'reason': 'the licence expired', 'claims': claims}
    acct = str(claims.get('a', '')).strip()
    if acct and acct != '*' and account_id and acct != str(account_id):
        return {'valid': False, 'reason': 'this key belongs to a different AWS account', 'claims': claims}
    return {'valid': True, 'reason': '', 'claims': claims}
