"""Offline tests for the ops tools. No AWS or ServiceNow needed: boto3 and the network are stubbed.
Run:  python -m unittest discover -s tests -v   (from the repo root)
"""
import io
import json
import os
import sys
import types
import unittest
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambda"))

# ---- stub boto3 so the modules import without AWS
_b = types.ModuleType("boto3")
_b.client = lambda *a, **k: None
_b.resource = lambda *a, **k: None
_b.Session = lambda *a, **k: None
sys.modules.setdefault("boto3", _b)

import gateway                      # noqa: E402
import matrix_guardrails as gr      # noqa: E402
import matrix_ops_install as oi     # noqa: E402
import matrix_ops_skills as sk      # noqa: E402
import matrix_snow_tools as sn      # noqa: E402


class FakeEC2:
    """Just enough of the EC2 client for the gate and decommission checks."""
    def __init__(self, state="stopped", transition="User initiated (2020-01-01 00:00:00 GMT)", tags=None, backup=True):
        self.state, self.transition, self.backup = state, transition, backup
        self.tags = tags if tags is not None else {"matrix-managed": "true", "environment": gr.ENV, "Name": "web-01"}
        self.calls = []

    def describe_instances(self, InstanceIds=None, **kw):
        inst = {"InstanceId": "i-1", "State": {"Name": self.state}, "StateTransitionReason": self.transition,
                "Tags": [{"Key": k, "Value": v} for k, v in self.tags.items()], "InstanceType": "t3.micro",
                "Placement": {"AvailabilityZone": "x"}}
        return {"Reservations": [{"Instances": [inst]}]}

    def describe_images(self, **kw):
        return {"Images": [{"ImageId": "ami-1", "State": "available"}] if self.backup else []}

    def stop_instances(self, **kw):
        self.calls.append(("stop", kw))

    def terminate_instances(self, **kw):
        self.calls.append(("terminate", kw))


class FakeSession:
    def __init__(self, ec2):
        self.ec2 = ec2

    def client(self, name, **kw):
        return self.ec2


class Base(unittest.TestCase):
    def setUp(self):
        self._orig = (gr.validate_ticket, gr._session, gr.worknote, gr._audit, sk.DECOM_ROLE)
        gr.validate_ticket = lambda n: (True, "ok", {"_table": "change_request", "sys_id": "x"})
        gr.worknote = lambda *a, **k: None
        gr._audit = lambda *a, **k: None

    def tearDown(self):
        gr.validate_ticket, gr._session, gr.worknote, gr._audit, sk.DECOM_ROLE = self._orig

    def use(self, ec2):
        gr._session = lambda: FakeSession(ec2)
        return ec2


class TestGate(Base):
    def test_no_confirm_is_refused(self):
        r = sk.decommission_stop(instance_id="i-1", change_number="CHG0030001", approved=False)
        self.assertFalse(r["ok"])
        self.assertIn("needs_approval", r["error"])

    def test_incident_number_is_not_enough_for_a_change(self):
        for fn in (sk.decommission_stop, sk.decommission_snapshot, sk.decommission_terminate):
            r = fn(instance_id="i-1", change_number="INC0000001", approved=True)
            self.assertFalse(r["ok"], fn.__name__)
            self.assertIn("CHG", r["error"])

    def test_unapproved_change_is_refused(self):
        gr.validate_ticket = lambda n: (False, "CHG0030001 is not approved", {})
        r = sk.patch_install(instance_ids=["i-1"], change_number="CHG0030001", approved=True)
        self.assertFalse(r["ok"])
        self.assertIn("ticket_invalid", r["error"])

    def test_unmanaged_instance_is_refused(self):
        self.use(FakeEC2(tags={"Name": "other"}))
        r = sk.decommission_snapshot(instance_id="i-1", change_number="CHG0030001", approved=True)
        self.assertFalse(r["ok"])
        self.assertIn("matrix-managed", r["error"])


class TestDecommission(Base):
    def test_stop_needs_final_backup(self):
        e = self.use(FakeEC2(state="running", backup=False))
        r = sk.decommission_stop(instance_id="i-1", change_number="CHG0030001", approved=True)
        self.assertFalse(r["ok"])
        self.assertIn("final backup", r["error"])
        self.assertEqual(e.calls, [])

    def test_terminate_must_be_stopped(self):
        self.use(FakeEC2(state="running"))
        r = sk.decommission_terminate(instance_id="i-1", change_number="CHG0030001", approved=True)
        self.assertIn("stopped first", r["error"])

    def test_terminate_respects_hold_period(self):
        self.use(FakeEC2(transition="User initiated (%s GMT)" % __import__("time").strftime("%Y-%m-%d %H:%M:%S", __import__("time").gmtime())))
        r = sk.decommission_terminate(instance_id="i-1", change_number="CHG0030001", approved=True)
        self.assertIn("days yet", r["error"])

    def test_terminate_needs_backup(self):
        self.use(FakeEC2(backup=False))
        r = sk.decommission_terminate(instance_id="i-1", change_number="CHG0030001", approved=True)
        self.assertIn("final backup", r["error"])

    def test_terminate_needs_human_tag(self):
        self.use(FakeEC2())
        r = sk.decommission_terminate(instance_id="i-1", change_number="CHG0030001", approved=True)
        self.assertIn("decommission-approved=true", r["error"])

    def test_terminate_off_by_default(self):
        tags = {"matrix-managed": "true", "environment": gr.ENV, "decommission-approved": "true"}
        e = self.use(FakeEC2(tags=tags))
        sk.DECOM_ROLE = ""
        r = sk.decommission_terminate(instance_id="i-1", change_number="CHG0030001", approved=True)
        self.assertFalse(r["ok"])
        self.assertIn("not enabled", r["error"])
        self.assertEqual(e.calls, [])


class TestRegistration(unittest.TestCase):
    def build(self):
        g = {"READ": {}, "WRITE": {}, "TOOLS": [], "CHAT_SYSTEM": "", "find_instance": lambda h: {"id": "i-1"}}
        oi.install(g)
        return g

    def test_all_tools_registered(self):
        g = self.build()
        names = {t["function"]["name"] for t in g["TOOLS"]}
        for n in sk.SKILLS:
            self.assertIn(n, names, n)
        for n in list(oi.SNOW_NAMES) + list(oi.SNOW_WRITE):
            self.assertIn(n, names, n)

    def test_every_change_tool_is_confirm_gated_and_needs_a_number(self):
        g = self.build()
        schemas = {t["function"]["name"]: t["function"]["parameters"] for t in g["TOOLS"]}
        for n in ("patch_install", "migration_cutover", "deployment_apply", "decommission_snapshot", "decommission_stop",
                  "decommission_terminate", "snow_update_ticket", "snow_close_change", "snow_create_problem",
                  "snow_link_ticket", "snow_attach_evidence", "snow_update_cmdb_ci"):
            self.assertIn(n, g["WRITE"], n + " must be a WRITE tool")
            self.assertNotIn(n, g["READ"], n)
            self.assertIn("number", schemas[n]["required"], n)

    def test_router_sends_new_tools_to_the_model(self):
        g = self.build()
        routable = set()
        for grp in gateway.GROUPS.values():
            routable.update(grp)
        for t in g["TOOLS"]:
            self.assertIn(t["function"]["name"], routable, t["function"]["name"] + " is never sent to the LLM")

    def test_router_picks_decommission_group(self):
        g = self.build()
        tools, matched = gateway.select_tools("please decommission web-01", g["TOOLS"])
        self.assertIn("decom", matched)
        self.assertIn("decommission_stop", {t["function"]["name"] for t in tools})


class TestGatewayFailover(unittest.TestCase):
    def test_bad_key_on_one_slot_falls_over(self):
        gateway.COOL.clear()
        a = {"id": "a", "url": "http://a", "key": "bad", "model": "m1", "label": "m1 (primary #0)"}
        b = {"id": "b", "url": "http://b", "key": "ok", "model": "m2", "label": "m2 (standby #1)"}

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *x):
                return False

        def fake(req, timeout=0):
            if req.full_url == "http://a":
                raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(b"bad key"))
            return Resp(json.dumps({"choices": []}).encode())

        orig = gateway.urllib.request.urlopen
        gateway.urllib.request.urlopen = fake
        try:
            res = gateway.post([a, b], {"messages": []})
            self.assertEqual(res["model"], "m2")
            self.assertGreater(gateway.COOL["a"], 0)  # the bad slot is parked
        finally:
            gateway.urllib.request.urlopen = orig

    def test_all_slots_bad_names_the_slot(self):
        gateway.COOL.clear()
        a = {"id": "a", "url": "http://a", "key": "bad", "model": "m1", "label": "m1 (primary #0)"}

        def fake(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(b"bad key"))

        orig = gateway.urllib.request.urlopen
        gateway.urllib.request.urlopen = fake
        try:
            with self.assertRaises(RuntimeError) as cm:
                gateway.post([a], {"messages": []})
            self.assertIn("m1 (primary #0) rejected its API key", str(cm.exception))
        finally:
            gateway.urllib.request.urlopen = orig


class TestSnowTools(unittest.TestCase):
    def test_query_text_cannot_inject(self):
        self.assertNotIn("^", sn._q("a^b=c"))

    def test_search_builds_an_and_query(self):
        seen = {}
        orig = sn._query
        sn._query = lambda table, q, fields="", limit=1: seen.update(q=q, table=table) or []
        try:
            sn.search_tickets(text="disk full^active=false", ci="web-01")
        finally:
            sn._query = orig
        self.assertTrue(seen["q"].startswith("active=true^short_descriptionLIKE"))
        self.assertIn("cmdb_ci.name=web-01", seen["q"])
        self.assertEqual(seen["q"].count("active="), 1)  # the injected active=false was neutralised

    def test_update_ticket_rejects_state_changes(self):
        orig = sn._by_number
        sn._by_number = lambda n: ("incident", {"sys_id": "x"})
        try:
            r = sn.update_ticket(number="INC0000001", fields={"state": "6"})
        finally:
            sn._by_number = orig
        self.assertFalse(r["ok"])
        self.assertIn("state", r["error"])

    def test_change_approval_report(self):
        orig = sn._by_number
        sn._by_number = lambda n: ("change_request", {"approval": "requested", "state": "-5"})
        try:
            r = sn.check_change_approval(number="CHG0030001")
        finally:
            sn._by_number = orig
        self.assertTrue(r["ok"])
        self.assertFalse(r["change"]["ready_to_execute"])


if __name__ == "__main__":
    unittest.main()
