"""Signed licence key: the vendor signs, the product verifies, and editing anything breaks it."""
import base64
import json
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda'))
os.environ.setdefault('AWS_DEFAULT_REGION', 'ap-southeast-2')

import matrix_ed25519 as ed  # noqa: E402
import matrix_licence_key as lk  # noqa: E402
import matrix_license as ml  # noqa: E402

SEC = bytes.fromhex('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60')   # RFC 8032 test key, never a real key
PUB = ed.public_key(SEC).hex()


def key(**kw):
    p = {'c': 'Acme', 'a': '111122223333', 's': 25, 'u': 2, 'p': 'starter', 'e': int(time.time()) + 1000}
    p.update(kw)
    return lk.make_key(SEC, p)


class Ed25519(unittest.TestCase):
    def test_rfc8032_vector_1(self):
        pub = bytes.fromhex('d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a')
        sig = bytes.fromhex('e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b')
        self.assertEqual(ed.public_key(SEC), pub)
        self.assertEqual(ed.sign(SEC, b''), sig)
        self.assertTrue(ed.verify(pub, b'', sig))
        self.assertFalse(ed.verify(pub, b'x', sig))
        self.assertFalse(ed.verify(pub, b'', sig[:-1] + b'\x00'))


class LicenceKey(unittest.TestCase):
    def test_valid_key(self):
        r = lk.check(key(), '111122223333', public_hex=PUB)
        self.assertTrue(r['valid'])
        self.assertEqual(r['claims']['s'], 25)

    def test_edited_limits_break_the_signature(self):
        k = key().split('.')
        body = json.loads(base64.urlsafe_b64decode(k[1] + '=='))
        body['s'] = 9999
        k[1] = base64.urlsafe_b64encode(json.dumps(body, separators=(',', ':'), sort_keys=True).encode()).decode().rstrip('=')
        r = lk.check('.'.join(k), '111122223333', public_hex=PUB)
        self.assertFalse(r['valid'])
        self.assertIn('signature', r['reason'])

    def test_wrong_account_expired_and_garbage(self):
        self.assertIn('different AWS account', lk.check(key(), '999999999999', public_hex=PUB)['reason'])
        self.assertIn('expired', lk.check(key(e=int(time.time()) - 5), '111122223333', public_hex=PUB)['reason'])
        self.assertFalse(lk.check('hello', '1', public_hex=PUB)['valid'])
        self.assertFalse(lk.check('', '1', public_hex=PUB)['valid'])

    def test_any_account_key_for_pilots(self):
        self.assertTrue(lk.check(key(a='*'), '555566667777', public_hex=PUB)['valid'])

    def test_key_signed_by_someone_else_is_refused(self):
        other = lk.make_key(bytes(range(32)), {'c': 'Evil', 'a': '*', 's': 0, 'u': 0, 'e': int(time.time()) + 100})
        self.assertFalse(lk.check(other, '1')['valid'])   # checked against the real embedded public key


class MeterUsesTheKey(unittest.TestCase):
    def setUp(self):
        self.good = key()
        self._pub = lk.PUBLIC_KEY_HEX
        lk.PUBLIC_KEY_HEX = PUB

    def tearDown(self):
        lk.PUBLIC_KEY_HEX = self._pub

    def test_settings_cannot_override_a_signed_key(self):
        env = {'LICENSE_KEY': self.good, 'LICENSE_PLAN': 'commander', 'LICENSE_SERVERS': '9999', 'LICENSE_SEATS': '999'}
        r = ml.resolve(env, '111122223333')
        self.assertTrue(r['valid'])
        self.assertEqual(r['limits'], {'servers': 25, 'seats': 2})
        self.assertEqual(r['plan'], 'starter')

    def test_bad_key_is_invalid_not_evaluation(self):
        r = ml.resolve({'LICENSE_KEY': 'MTX1.abc.def', 'LICENSE_PLAN': 'commander'}, '1')
        self.assertFalse(r['valid'])
        self.assertEqual(r['plan'], 'invalid')

    def test_no_key_keeps_the_old_behaviour(self):
        self.assertEqual(ml.resolve({}, '1')['plan'], 'evaluation')
        self.assertEqual(ml.resolve({'LICENSE_PLAN': 'team'}, '1')['limits']['servers'], 100)

    def test_enforcement_blocks_only_when_switched_on(self):
        self.assertEqual(ml.blocked({}, '1'), '')
        self.assertIn('not licensed', ml.blocked({'LICENSE_ENFORCE': '1'}, '1'))
        self.assertEqual(ml.blocked({'LICENSE_ENFORCE': '1', 'LICENSE_KEY': self.good}, '111122223333'), '')
        self.assertIn('different AWS account', ml.blocked({'LICENSE_ENFORCE': '1', 'LICENSE_KEY': self.good}, '000000000000'))

    def test_report_shows_the_key_problem(self):
        class Ec2:
            def describe_instances(self, **kw):
                return {'Reservations': []}
        ml.CACHE.clear()
        r = ml.report(Ec2(), [], 'dev', env={'LICENSE_KEY': 'MTX1.bad.sig'}, account_id='1')
        self.assertEqual(r['status'], 'invalid')
        self.assertTrue(r['key_problem'])


class VendorKeyMatchesProduct(unittest.TestCase):
    def test_public_key_constant_is_a_valid_point(self):
        self.assertEqual(len(bytes.fromhex(lk.PUBLIC_KEY_HEX)), 32)
        self.assertIsNotNone(ed._decompress(bytes.fromhex(lk.PUBLIC_KEY_HEX)))


if __name__ == '__main__':
    unittest.main()
