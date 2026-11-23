"""VENDOR-ONLY tool: make a signing key pair, and issue signed MATRIX licence keys.

Never ship this file to a customer, and never put the private key file in the repository or a customer's account.

  python tools/matrix_licence_sign.py keygen  <private_key_file>
      Makes a new key pair. Saves the PRIVATE key (hex) to the file and prints the PUBLIC key (hex).
      Put the public key in lambda/matrix_licence_key.py (PUBLIC_KEY_HEX) before building a release.

  python tools/matrix_licence_sign.py issue <private_key_file> --customer "Acme" --account 123456789012 \
        --plan team --servers 100 --seats 10 --days 365 --serial 1
      Prints one licence key (MTX1.xxx.yyy). Give it to the customer to set as LICENSE_KEY.
      --account '*' makes a key that works in any account (use only for evaluations). --servers 0 = unlimited.

  python tools/matrix_licence_sign.py check <key> [--account 123456789012]
      Checks a key against the public key in the product.
"""
import argparse
import os
import secrets
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lambda'))
import matrix_ed25519 as ed          # noqa: E402
import matrix_licence_key as LK      # noqa: E402


def _public(secret):
    for name in ('public_key', 'publickey', 'pubkey', 'secret_to_public'):
        if hasattr(ed, name):
            return getattr(ed, name)(secret)
    raise SystemExit('matrix_ed25519 has no public-key function')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    k = sub.add_parser('keygen')
    k.add_argument('private_key_file')
    i = sub.add_parser('issue')
    i.add_argument('private_key_file')
    i.add_argument('--customer', required=True)
    i.add_argument('--account', required=True)
    i.add_argument('--plan', default='custom')
    i.add_argument('--servers', type=int, default=0)
    i.add_argument('--seats', type=int, default=0)
    i.add_argument('--days', type=int, default=365)
    i.add_argument('--serial', type=int, default=1)
    c = sub.add_parser('check')
    c.add_argument('key')
    c.add_argument('--account', default='')
    a = ap.parse_args(argv)

    if a.cmd == 'keygen':
        if os.path.exists(a.private_key_file):
            raise SystemExit('Refusing to overwrite %s' % a.private_key_file)
        secret = secrets.token_bytes(32)
        with open(a.private_key_file, 'w') as f:
            f.write(secret.hex())
        print('Private key saved to', a.private_key_file, '(keep it offline, back it up, never commit it)')
        print('PUBLIC_KEY_HEX =', _public(secret).hex())
        return 0
    if a.cmd == 'issue':
        secret = bytes.fromhex(open(a.private_key_file).read().strip())
        payload = {'c': a.customer, 'a': a.account, 'p': a.plan, 's': a.servers, 'u': a.seats,
                   'e': int(time.time() + a.days * 86400), 'n': a.serial}
        key = LK.make_key(secret, payload)
        chk = LK.check(key, a.account if a.account != '*' else '')
        if not chk['valid']:
            raise SystemExit('The key does not verify against the public key in the product: ' + chk['reason'] +
                             '\nThis private key is not the pair of PUBLIC_KEY_HEX in lambda/matrix_licence_key.py.')
        print(key)
        return 0
    r = LK.check(a.key, a.account)
    print('valid' if r['valid'] else 'NOT valid: ' + r['reason'], r['claims'])
    return 0 if r['valid'] else 1


if __name__ == '__main__':
    sys.exit(main())
