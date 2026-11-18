"""Offline tests for matrix_alarm_intake. Run: python -m unittest discover -s tests -v"""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambda"))
_b = types.ModuleType("boto3")
_b.client = lambda *a, **k: None
_b.resource = lambda *a, **k: None
_b.Session = lambda *a, **k: None
sys.modules.setdefault("boto3", _b)
_c = types.ModuleType("boto3.dynamodb.conditions")
_c.Key = lambda *a, **k: None
sys.modules.setdefault("boto3.dynamodb", types.ModuleType("boto3.dynamodb"))
sys.modules.setdefault("boto3.dynamodb.conditions", _c)

import matrix_alarm_intake as AL   # noqa: E402
import autonomy as AU              # noqa: E402

EVENT = {"source": "aws.cloudwatch", "detail-type": "CloudWatch Alarm State Change",
         "detail": {"alarmName": "MATRIX-LNX01-CPU-HIGH", "state": {"value": "ALARM", "reason": "40.9 >= 40"},
                    "configuration": {"metrics": [{"metricStat": {"metric": {"dimensions": {"InstanceId": "i-1"}}}}]}}}


class Setup(unittest.TestCase):
    def setUp(self):
        self.calls, self.kicked, self.inbox, self.open = [], [], [], []

        def sn(method, path, params=None, body=None):
            self.calls.append((method, path, params, body))
            if path == "incident" and method == "GET":
                return self.open
            if path == "incident":
                return {"number": "INC1", "sys_id": "s1"}
            return [{"sys_id": "x"}]
        AL.G.update({"sn": sn, "raw": lambda x: x, "val": lambda x: x, "add_note": lambda s, t: self.calls.append(("NOTE", s, t))})
        AU.G.update(AL.G)
        AL._host = lambda i: "matrix-linux-01" if i else ""
        AU._kick = lambda n, h, a: self.kicked.append((n, h, a)) or "started"
        AU.inbox_add = lambda k, n, t: self.inbox.append((k, n, t))
        AL.PREFIXES = []


class TestIntake(Setup):
    def test_alarm_creates_assigned_incident_notifies_and_starts_agent(self):
        r = AL.on_event(EVENT)
        self.assertEqual((r["result"], r["number"]), ("created", "INC1"))
        post = next(c for c in self.calls if c[0] == "POST")
        self.assertEqual(post[3]["short_description"], "[MATRIX] MATRIX-LNX01-CPU-HIGH")
        self.assertIn("assignment_group", post[3])
        self.assertEqual(self.kicked, [("INC1", "matrix-linux-01", "MATRIX-LNX01-CPU-HIGH")])
        self.assertEqual(self.inbox[0][0], "incident")

    def test_open_incident_for_same_alarm_is_not_duplicated(self):
        self.open = [{"number": "INC9"}]
        r = AL.on_event(EVENT)
        self.assertIn("already open as INC9", r["result"])
        self.assertEqual(self.kicked, [])
        self.assertFalse(any(c[0] == "POST" for c in self.calls))

    def test_ok_transition_is_ignored(self):
        e = {**EVENT, "detail": {**EVENT["detail"], "state": {"value": "OK"}}}
        self.assertEqual(AL.on_event(e)["result"], "not an ALARM transition")

    def test_prefix_filter(self):
        AL.PREFIXES = ["PROD-"]
        self.assertIn("ignored", AL.on_event(EVENT)["result"])

    def test_servicenow_error_does_not_raise(self):
        def bad(*a, **k):
            raise RuntimeError("down")
        AL.G["sn"] = bad
        self.assertTrue(AL.on_event(EVENT)["result"].startswith("error"))

    def test_event_detection(self):
        self.assertTrue(AL.is_alarm_event(EVENT))
        self.assertFalse(AL.is_alarm_event({"matrix_task": "alarm_sweep"}))


if __name__ == "__main__":
    unittest.main()
