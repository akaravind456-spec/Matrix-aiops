"""'I stopped after too many steps': a new-server deploy wasted the 6 allowed steps on tools that cannot work (no Change module)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda'))
os.environ.setdefault('AWS_DEFAULT_REGION', 'ap-southeast-2')


class NewServerName(unittest.TestCase):
    def setUp(self):
        import matrix_change
        self.mc = matrix_change

    def test_name_label(self):
        self.assertEqual(self.mc._new_server_name('deploy a linux server with t2-micro | name: test-01 | environment : Dev'), 'test-01')

    def test_bare_name_skips_instance_type_and_az(self):
        self.assertEqual(self.mc._new_server_name('deploy a t2-micro server called web-02 in ap-southeast-2a'), 'web-02')

    def test_no_name(self):
        self.assertEqual(self.mc._new_server_name('deploy a linux server with t2-micro'), '')

    def test_change_tool_is_hidden_in_incident_mode(self):
        self.assertIn('snow_create_change', self.mc.NO_CHANGE_MODULE_TOOLS)


class StepLimitReply(unittest.TestCase):
    def setUp(self):
        import chat_text
        self.ca = chat_text

    def test_says_what_was_tried_and_the_last_problem(self):
        tried = [('snow_create_change', 'Error: not_found'), ('list_servers', '[]'), ('create_change_request', 'Created incident INC1')]
        r = self.ca.step_limit_reply(tried, False)
        self.assertIn('snow create change', r)
        self.assertIn('last problem', r)
        self.assertIn('not_found', r)
        self.assertNotIn('too many steps', r)

    def test_mentions_buttons_when_a_confirmation_is_waiting(self):
        self.assertIn('confirmation buttons', self.ca.step_limit_reply([('restart_service', 'ok')], True))


if __name__ == '__main__':
    unittest.main()


class UsableTools(unittest.TestCase):
    def setUp(self):
        import matrix_change
        self.mc = matrix_change
        self.tools = [{'function': {'name': n}} for n in ('deploy_server', 'deployment_apply', 'snow_create_change', 'list_servers')]

    def names(self, incident, tf):
        return [t['function']['name'] for t in self.mc._usable(self.tools, incident, tf)]

    def test_without_terraform_the_direct_deploy_tool_remains(self):
        n = self.names(True, False)
        self.assertNotIn('deploy_server', n)
        self.assertNotIn('snow_create_change', n)
        self.assertIn('deployment_apply', n)
        self.assertIn('list_servers', n)

    def test_with_terraform_deploy_server_is_kept(self):
        self.assertIn('deploy_server', self.names(False, True))

    def test_change_mode_keeps_snow_create_change(self):
        self.assertIn('snow_create_change', self.names(False, True))


class DeploySize(unittest.TestCase):
    """test-02 failed with int(None): the model sent no instance size at all."""

    def setUp(self):
        import matrix_change
        import matrix_ops_skills as ops
        self.mc, self.ops = matrix_change, ops

    def test_asked_size_is_read_from_the_request(self):
        self.assertEqual(self.mc._asked_size('deploy a linux server with t2-micro name: test-02'), 't2.micro')
        self.assertEqual(self.mc._asked_size('use a t3.small please'), 't3.small')
        self.assertEqual(self.mc._asked_size('deploy a server with 2 vCPU'), '')

    def test_no_size_gets_the_default_instead_of_crashing(self):
        self.assertEqual(self.ops.size_args(None, None, None), (self.ops.DEFAULT_INSTANCE_TYPE, None, None))

    def test_named_type_is_used_and_dash_becomes_dot(self):
        self.assertEqual(self.ops.size_args('t2-micro', None, None), ('t2.micro', None, None))

    def test_vcpu_and_ram_are_kept_when_no_type_is_named(self):
        self.assertEqual(self.ops.size_args(None, 2, 8), (None, 2, 8))


class FreeTierFallback(unittest.TestCase):
    """RunInstances refused t2.micro on a Free Plan account; the deploy now retries with the smallest allowed type."""

    def test_free_tier_type_picks_the_smallest_x86(self):
        import matrix_guardrails as gr

        class Pager:
            def paginate(self, **kw):
                assert {"Name": "free-tier-eligible", "Values": ["true"]} in kw["Filters"]
                return [{"InstanceTypes": [{"InstanceType": "t3.small", "MemoryInfo": {"SizeInMiB": 2048}},
                                           {"InstanceType": "t3.micro", "MemoryInfo": {"SizeInMiB": 1024}}]}]

        class Ec2:
            def get_paginator(self, name):
                return Pager()

        class Sess:
            def client(self, n):
                return Ec2()

        self.assertEqual(gr.free_tier_type(Sess()), "t3.micro")


class IncidentModeCloseTool(unittest.TestCase):
    def test_change_close_tool_is_hidden_without_a_change_module(self):
        import matrix_change as mc
        tools = [{'function': {'name': n}} for n in ('snow_close_change', 'resolve_incident')]
        names = [t['function']['name'] for t in mc._usable(tools, True, True)]
        self.assertEqual(names, ['resolve_incident'])


class ConsoleHistory(unittest.TestCase):
    def test_confirm_results_are_sent_back_to_the_model(self):
        html = open(os.path.join(os.path.dirname(__file__), '..', 'frontend', 'matrix-ui.html'), encoding='utf-8').read()
        self.assertIn("[Console: \"'+c.summary", html)


class ServiceNowAsleep(unittest.TestCase):
    def test_hibernating_page_gives_a_plain_message(self):
        src = open(os.path.join(os.path.dirname(__file__), '..', 'lambda', 'console_api.py'), encoding='utf-8').read()
        self.assertIn("ServiceNow is asleep", src)


class MadeUpImageId(unittest.TestCase):
    def test_launch_falls_back_to_the_real_image(self):
        import aiops
        calls = {}

        class E:
            def describe_images(self, **kw):
                if 'ImageIds' in kw:
                    raise RuntimeError('InvalidAMIID.Malformed')
                calls['owners'] = kw['Owners']
                return {'Images': [{'ImageId': 'ami-094f198b2c6be81a1', 'State': 'available', 'CreationDate': '2026-01-02'},
                                   {'ImageId': 'ami-0aaaaaaaaaaaaaaaa', 'State': 'available', 'CreationDate': '2026-01-01'}]}

            def describe_instances(self, **kw):
                return {'Reservations': [{'Instances': [{'VpcId': 'v', 'SecurityGroups': [{'GroupId': 'sg-1'}], 'Tags': []}]}]}

            def describe_subnets(self, **kw):
                return {'Subnets': [{'SubnetId': 'subnet-1'}]}

            def run_instances(self, **kw):
                calls['image'] = kw['ImageId']
                return {'Instances': [{'InstanceId': 'i-0123456789abcdef0'}]}

        old = (aiops.ec2, aiops._inst, aiops._audit)
        aiops.ec2 = E()
        aiops._inst = lambda h: {'id': 'i-1', 'host': 'test-03', 'type': 't3.micro'}
        aiops._audit = lambda *a, **k: None
        try:
            out = aiops.migrate_launch({'host': 'test-03', 'image_id': 'ami-05c65ae687e3ca889', 'az': 'ap-southeast-2a', 'new_name': 'test-03-migrated'}, {})
        finally:
            aiops.ec2, aiops._inst, aiops._audit = old
        self.assertEqual(calls['image'], 'ami-094f198b2c6be81a1')
        self.assertIn('Launched', out)
