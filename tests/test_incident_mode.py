"""CHANGE_MODE=incident: planned work is tracked on an INC when the ServiceNow instance has no Change module."""
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

import matrix_guardrails as gr   # noqa: E402
import matrix_ops_skills as sk   # noqa: E402
import matrix_snow_tools as sn   # noqa: E402
import matrix_change as ch       # noqa: E402
import matrix_mode as mode       # noqa: E402


class T(unittest.TestCase):
    def setUp(self):
        os.environ.pop("CHANGE_MODE", None)
        self.orig = (gr.validate_ticket, sn._sn, sn._by_number)
        gr.validate_ticket = lambda n: (True, "ok", {"_table": "incident", "sys_id": "x"})

    def tearDown(self):
        os.environ.pop("CHANGE_MODE", None)
        gr.validate_ticket, sn._sn, sn._by_number = self.orig

    def test_default_still_requires_chg(self):
        err, _ = sk._change("INC0010007", True)
        self.assertIn("CHG", err["error"])

    def test_incident_mode_accepts_inc_but_still_needs_confirm(self):
        os.environ["CHANGE_MODE"] = "incident"
        err, rec = sk._change("INC0010007", True)
        self.assertIsNone(err)
        err, _ = sk._change("INC0010007", False)
        self.assertIn("needs_approval", err["error"])
        err, _ = sk._change("garbage", True)
        self.assertIn("INC", err["error"])

    def test_approval_check_on_an_open_incident(self):
        os.environ["CHANGE_MODE"] = "incident"
        sn._by_number = lambda n: ("incident", {"state": "2", "sys_id": "s"})
        r = sn.check_change_approval(number="INC0010007")
        self.assertTrue(r["change"]["ready_to_execute"])
        sn._by_number = lambda n: ("incident", {"state": "6", "sys_id": "s"})
        self.assertFalse(sn.check_change_approval(number="INC0010007")["change"]["ready_to_execute"])

    def test_approval_check_rejects_inc_in_default_mode(self):
        self.assertFalse(sn.check_change_approval(number="INC0010007")["ok"])

    def test_snow_create_change_makes_an_incident(self):
        os.environ["CHANGE_MODE"] = "incident"
        calls = []

        def fake(method, path, body=None, params=None):
            calls.append((method, path, body))
            if path.endswith("/cmdb_ci"):
                return [{"sys_id": "ci1"}]
            if path.endswith("/sys_user_group") or path.endswith("/sys_user"):
                return [{"sys_id": "g1"}]
            if method == "POST":
                return {"number": "INC0010009", "sys_id": "s9"}
            return []
        sn._sn = fake
        r = sn.create_change(ci="web-01", short_description="Deploy web-02", description="new server")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["number"], "INC0010009")
        post = next(c for c in calls if c[0] == "POST")
        self.assertTrue(post[1].endswith("/incident"))
        self.assertTrue(post[2]["short_description"].startswith("[PLANNED]"))

    def test_chat_tool_creates_incident_for_a_new_server(self):
        os.environ["CHANGE_MODE"] = "incident"
        calls = []

        def sn_(method, path, params=None, body=None):
            calls.append((method, path, body))
            return {"number": "INC0010010", "sys_id": "s10"} if method == "POST" else []

        def need(a):
            raise RuntimeError("server not found")
        ch.G.update({"sn": sn_, "raw": lambda x: x, "need_instance": need, "add_note": lambda *a: None, "_group_id": lambda n: "g1"})
        r = ch.create_change_request({"ci": "Test-server", "kind": "deployment", "short_description": "Deploy Test-server", "details": "2 vCPU 4 GB"}, {"name": "Sam"})
        self.assertIn("INC0010010", r)
        self.assertEqual(next(c for c in calls if c[0] == "POST")[1], "incident")

    def test_mode_helper(self):
        self.assertFalse(mode.incident_mode())
        os.environ["CHANGE_MODE"] = " Incident "
        self.assertTrue(mode.incident_mode())


if __name__ == "__main__":
    unittest.main()
