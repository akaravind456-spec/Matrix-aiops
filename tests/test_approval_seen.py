"""INC0010016: an approval crashed in 5 ms because the saved diagnostics were cut in the middle of the JSON text."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda'))
os.environ.setdefault('AWS_DEFAULT_REGION', 'ap-southeast-2')


class SeenStorage(unittest.TestCase):
    def setUp(self):
        import autonomy
        self.au = autonomy

    def test_long_diagnostics_stay_valid_json(self):
        seen = ['health check output ' * 120, 'disk output ' * 150, 'alarm output ' * 100, 'kb ' * 400]
        raw = self.au.pack_seen(seen)
        self.assertLessEqual(len(raw), 6000)
        self.assertEqual(len(json.loads(raw)), len(seen))

    def test_short_diagnostics_unchanged(self):
        seen = ['a', 'b']
        self.assertEqual(json.loads(self.au.pack_seen(seen)), seen)

    def test_many_items_still_valid(self):
        raw = self.au.pack_seen(['x' * 2000] * 40)
        self.assertLessEqual(len(raw), 6000)
        json.loads(raw)

    def test_broken_stored_value_does_not_stop_the_fix(self):
        self.assertEqual(self.au.load_seen('] was greater than the th'), [])
        self.assertEqual(self.au.load_seen(None), [])
        self.assertEqual(self.au.load_seen('{"a":1}'), [])
        self.assertEqual(self.au.load_seen('["ok"]'), ['ok'])


if __name__ == '__main__':
    unittest.main()
