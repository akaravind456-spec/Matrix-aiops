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
