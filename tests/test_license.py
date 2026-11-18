import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda'))
import matrix_license as L


class FakeEC2:
    def __init__(self, n=3, boom=None):
        self.n, self.boom, self.calls, self.filters = n, boom, 0, None

    def describe_instances(self, **kw):
        self.calls += 1
        self.filters = kw['Filters']
        if self.boom:
            raise self.boom
        return {'Reservations': [{'Instances': [{}] * self.n}]}


class License(unittest.TestCase):
    def setUp(self):
        L.CACHE.clear()

    def test_unset_is_evaluation(self):
        plan, _, lim = L.limits({})
        self.assertEqual(plan, 'evaluation')
        self.assertEqual(lim, {'servers': None, 'seats': None})

    def test_plans(self):
        self.assertEqual(L.limits({'LICENSE_PLAN': 'Starter'})[2], {'servers': 25, 'seats': 2})
        self.assertEqual(L.limits({'LICENSE_PLAN': ' team '})[2], {'servers': 100, 'seats': 10})
        self.assertEqual(L.limits({'LICENSE_PLAN': 'commander'})[2], {'servers': None, 'seats': 50})

    def test_custom_and_overrides(self):
        self.assertEqual(L.limits({'LICENSE_PLAN': 'custom', 'LICENSE_SERVERS': '40', 'LICENSE_SEATS': '4'})[2],
                         {'servers': 40, 'seats': 4})
        self.assertEqual(L.limits({'LICENSE_PLAN': 'team', 'LICENSE_SERVERS': 'unlimited'})[2]['servers'], None)
        self.assertEqual(L.limits({'LICENSE_PLAN': 'starter', 'LICENSE_SEATS': 'abc'})[2]['seats'], None)

    def test_unknown_plan_is_evaluation(self):
        self.assertEqual(L.limits({'LICENSE_PLAN': 'gold'})[0], 'evaluation')

    def test_state(self):
        self.assertEqual(L.state(5, None), 'ok')
        self.assertEqual(L.state(20, 25), 'ok')
        self.assertEqual(L.state(23, 25), 'near')
        self.assertEqual(L.state(25, 25), 'near')
        self.assertEqual(L.state(26, 25), 'over')

    def test_report_over(self):
        r = L.report(FakeEC2(30), [{'u': 'a', 'p': 'secret'}], 'dev', {'LICENSE_PLAN': 'starter'}, now=1)
        self.assertEqual(r['servers'], {'used': 30, 'limit': 25, 'state': 'over'})
        self.assertEqual(r['seats'], {'used': 1, 'limit': 2, 'state': 'ok'})
        self.assertEqual(r['status'], 'over')
        self.assertFalse(r['enforced'])

    def test_report_never_leaks_users(self):
        r = L.report(FakeEC2(1), [{'u': 'alice', 'p': 'pw123'}], 'dev', {'LICENSE_PLAN': 'team'}, now=1)
        self.assertNotIn('alice', str(r))
        self.assertNotIn('pw123', str(r))

    def test_filters_use_environment_and_tag(self):
        ec2 = FakeEC2(1)
        L.report(ec2, [], 'prod', {}, now=1)
        self.assertIn({'Name': 'tag:matrix-managed', 'Values': ['true']}, ec2.filters)
        self.assertIn({'Name': 'tag:environment', 'Values': ['prod']}, ec2.filters)

    def test_cache(self):
        ec2 = FakeEC2(2)
        L.report(ec2, [], 'dev', {}, now=1000)
        L.report(ec2, [], 'dev', {}, now=1100)
        self.assertEqual(ec2.calls, 1)
        L.report(ec2, [], 'dev', {}, now=1000 + L.TTL + 1)
        self.assertEqual(ec2.calls, 2)

    def test_seats_bad_input(self):
        self.assertEqual(L.count_seats('nope'), 0)

    def test_action_returns_clean_error(self):
        g = {'ACTIONS': {}}
        import types
        fake = types.SimpleNamespace(client=lambda *a, **k: FakeEC2(boom=Exception('UnauthorizedOperation: x')))
        old = sys.modules.get('boto3')
        sys.modules['boto3'] = fake
        try:
            L.install(g)
            out = g['ACTIONS']['license']({}, {})
        finally:
            if old is not None:
                sys.modules['boto3'] = old
            else:
                del sys.modules['boto3']
        self.assertFalse(out['ok'])
        self.assertIn('ec2:DescribeInstances', out['error'])


if __name__ == '__main__':
    unittest.main()
