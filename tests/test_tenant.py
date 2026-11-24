import datetime
import unittest

import matrix_tenant as T

ROLE = 'arn:aws:iam::111111111111:role/matrix-executor-dev'


class FakeSts:
    def __init__(self):
        self.calls = []

    def assume_role(self, **kw):
        self.calls.append(kw)
        exp = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=kw['DurationSeconds'])
        return {'Credentials': {'AccessKeyId': 'AK', 'SecretAccessKey': 'SK', 'SessionToken': 'ST', 'Expiration': exp}}


class FakeTable:
    def __init__(self, items):
        self.items = items

    def get_item(self, Key):
        i = self.items.get(Key['tenant_id'])
        return {'Item': i} if i else {}


class TenantTests(unittest.TestCase):
    def setUp(self):
        T.CACHE.clear()

    def test_default_tenant_comes_from_settings(self):
        t = T.load(None, env={'EXECUTOR_ROLE_ARN': ROLE, 'AWS_REGION': 'ap-southeast-2'})
        self.assertEqual(t['tenant_id'], 'default')
        self.assertEqual(t['account_id'], '111111111111')

    def test_unknown_and_bad_ids_are_refused(self):
        with self.assertRaises(T.TenantError):
            T.load('nope', table=FakeTable({}))
        with self.assertRaises(T.TenantError):
            T.load('a/b', table=FakeTable({}))
        with self.assertRaises(T.TenantError):
            T.load('x' * 65, table=FakeTable({}))

    def test_role_must_belong_to_the_tenants_own_account(self):
        tab = FakeTable({'acme': {'account_id': '222222222222', 'role_arn': ROLE, 'status': 'active'}})
        with self.assertRaises(T.TenantError):
            T.load('acme', table=tab, secret=lambda i: 'x')

    def test_suspended_tenant_gets_nothing(self):
        tab = FakeTable({'acme': {'account_id': '111111111111', 'role_arn': ROLE, 'status': 'suspended'}})
        with self.assertRaises(T.TenantError):
            T.load('acme', table=tab, secret=lambda i: 'x')

    def test_external_id_comes_from_the_secret_not_the_table(self):
        tab = FakeTable({'acme': {'account_id': '111111111111', 'role_arn': ROLE, 'status': 'active', 'external_id': 'IN-TABLE'}})
        t = T.load('acme', table=tab, secret=lambda i: 'FROM-SECRET')
        self.assertEqual(t['external_id'], 'FROM-SECRET')

    def test_assume_role_sends_the_external_id(self):
        sts = FakeSts()
        t = {'tenant_id': 'acme', 'account_id': '111111111111', 'role_arn': ROLE, 'external_id': 'EXT', 'region': 'ap-southeast-2'}
        T.session_for(t, 'INC1', sts=sts)
        self.assertEqual(sts.calls[0]['ExternalId'], 'EXT')
        self.assertEqual(sts.calls[0]['RoleArn'], ROLE)

    def test_no_external_id_means_none_is_sent(self):
        sts = FakeSts()
        T.session_for({'tenant_id': 'default', 'role_arn': ROLE, 'region': 'ap-southeast-2'}, 'INC1', sts=sts)
        self.assertNotIn('ExternalId', sts.calls[0])

    def test_credentials_are_cached_until_near_expiry(self):
        sts = FakeSts()
        t = {'tenant_id': 'acme', 'role_arn': ROLE, 'external_id': 'E', 'region': 'ap-southeast-2'}
        T.session_for(t, 'INC1', sts=sts)
        T.session_for(t, 'INC1', sts=sts)
        self.assertEqual(len(sts.calls), 1)
        T.session_for(t, 'INC2', sts=sts)            # another session name is another entry
        self.assertEqual(len(sts.calls), 2)
        T.session_for(t, 'INC1', sts=sts, now=__import__('time').time() + 10000)   # expired
        self.assertEqual(len(sts.calls), 3)

    def test_cache_never_crosses_tenants(self):
        sts = FakeSts()
        a = {'tenant_id': 'a', 'role_arn': ROLE, 'external_id': 'EA', 'region': 'ap-southeast-2'}
        b = {'tenant_id': 'b', 'role_arn': ROLE, 'external_id': 'EB', 'region': 'ap-southeast-2'}
        T.session_for(a, 'INC1', sts=sts)
        T.session_for(b, 'INC1', sts=sts)
        self.assertEqual([c['ExternalId'] for c in sts.calls], ['EA', 'EB'])


if __name__ == '__main__':
    unittest.main()
