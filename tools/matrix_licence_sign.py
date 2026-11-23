"""VENDOR TOOL: make a signed MATRIX licence key for one customer. Never ship this file or the private key to customers.

Example:
  python tools/matrix_licence_sign.py --key C:/path/to/matrix-licence-private.key --customer "Acme Ltd" --account 123456789012 --plan team --servers 100 --seats 10 --days 365

The private key is a file with 64 hex characters. Keep it offline and backed up; if it is lost no new keys can be made, and if it leaks
anyone can make keys. The matching public key is already inside lambda/matrix_licence_key.py.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda'))
import matrix_ed25519 as ed  # noqa: E402
import matrix_licence_key as lk  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--key', required=True, help='path to the private key file (64 hex characters)')
    ap.add_argument('--customer', required=True)
    ap.add_argument('--account', default='*', help='the customer AWS account id, or * for any (pilots only)')
    ap.add_argument('--plan', default='custom', choices=['starter', 'team', 'commander', 'custom'])
    ap.add_argument('--servers', type=int, default=0, help='0 = unlimited')
    ap.add_argument('--seats', type=int, default=0, help='0 = unlimited')
    ap.add_argument('--days', type=int, default=365)
    ap.add_argument('--serial', default='')
    a = ap.parse_args()
    secret = bytes.fromhex(open(a.key).read().strip())
    if ed.public_key(secret).hex() != lk.PUBLIC_KEY_HEX:
        sys.exit('This private key does not match the public key inside the product. Refusing to sign.')
    exp = int(time.time() + a.days * 86400)
    payload = {'c': a.customer, 'a': a.account, 'p': a.plan, 's': a.servers, 'u': a.seats, 'e': exp, 'n': a.serial or str(int(time.time()))}
    print(lk.make_key(secret, payload))


if __name__ == '__main__':
    main()
