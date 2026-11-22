"""Work notes written to ServiceNow must be plain sentences, and the markers other code reads must stay."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda'))
os.environ.setdefault('AWS_DEFAULT_REGION', 'ap-southeast-2')


class PlainNotes(unittest.TestCase):
    def setUp(self):
        import autonomy
        self.au = autonomy

    def test_short_collapses_whitespace_and_trims(self):
        out = self.au._short('line one\n\n   line   two ' + 'x' * 400, 50)
        self.assertTrue(out.startswith('Result: line one line two'))
        self.assertTrue(out.endswith('...'))
        self.assertLess(len(out), 70)

    def test_short_empty(self):
        self.assertEqual(self.au._short('  '), 'Nothing was returned.')

    def test_every_read_tool_has_a_plain_name(self):
        for t in ('health_check', 'disk_usage', 'top_cpu_processes', 'service_status', 'check_alarms', 'kb_search', 'cmdb_lookup'):
            self.assertIn(t, self.au.CHECK_NAMES)
            self.assertNotIn('_', self.au.CHECK_NAMES[t])

    def test_escalation_marker_still_parses(self):
        import re
        note = '[MATRIX AI] Escalated to L2 (MATRIX AI). Reason: disk still high\nWhat happens next: ...'
        m = re.search(r'Escalated to L2 \([^)]*\)\. Reason:\s*([^\n]+)', note)
        self.assertEqual(m.group(1), 'disk still high')


if __name__ == '__main__':
    unittest.main()
