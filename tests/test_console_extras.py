"""Offline tests for matrix_console_extras (prices, ServiceNow KB and SSM uploads) and the AWS cost report.
Run:  python -m unittest discover -s tests -v   (from the repo root)
"""
import json
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

import matrix_console_extras as ex   # noqa: E402
import matrix_cost_action as ca      # noqa: E402

HUMAN = {"u": "sam", "name": "Sam", "role": "L2"}


class TestPrices(unittest.TestCase):
    def setUp(self):
        os.environ.pop("LLM_PRICES", None)

    def test_free_nvidia_and_known_groq(self):
        self.assertEqual(ex.price_for("nvidia/nemotron-3-ultra-550b-a55b")["in"], 0.0)
        p = ex.price_for("openai/gpt-oss-120b")
        self.assertEqual((p["in"], p["out"]), (0.15, 0.60))

    def test_unknown_model_has_no_price_not_zero(self):
        self.assertIsNone(ex.price_for("acme/mystery-1"))

    def test_environment_overrides_defaults_and_wildcards(self):
        os.environ["LLM_PRICES"] = json.dumps({"openai/gpt-oss-120b": {"in": 1, "out": 2}, "acme/*": [3, 4], "acme/big*": [9, 9]})
        try:
            self.assertEqual(ex.price_for("openai/gpt-oss-120b")["in"], 1.0)
            self.assertEqual(ex.price_for("acme/small")["out"], 4.0)
            self.assertEqual(ex.price_for("acme/bigger")["in"], 9.0)  # longest prefix wins
        finally:
            os.environ.pop("LLM_PRICES")

    def test_bad_price_json_is_ignored(self):
        os.environ["LLM_PRICES"] = "not json"
        try:
            self.assertEqual(ex.price_for("openai/gpt-oss-20b")["in"], 0.075)
        finally:
            os.environ.pop("LLM_PRICES")

    def test_cost_is_tokens_times_price_and_unknown_is_flagged(self):
        r = ex.cost_rows([{"model": "openai/gpt-oss-120b", "calls": 93, "in": 274900, "out": 17000},
                          {"model": "nvidia/nemotron-3-ultra-550b-a55b", "calls": 25, "in": 118500, "out": 4700},
                          {"model": "acme/mystery-1", "calls": 1, "in": 1000, "out": 1000}])
        self.assertAlmostEqual(r["rows"][0]["cost"], (274900 * 0.15 + 17000 * 0.60) / 1e6, places=6)
        self.assertEqual(r["rows"][1]["cost"], 0.0)
        self.assertIsNone(r["rows"][2]["cost"])
        self.assertEqual(r["unknown"], ["acme/mystery-1"])
        self.assertAlmostEqual(r["total"], r["rows"][0]["cost"], places=6)  # the unknown model adds nothing

    def test_llm_cost_action_uses_the_obs_action(self):
        ex.G["ACTIONS"] = {"obs": lambda q, u: {"ok": True, "models": [{"model": "openai/gpt-oss-20b", "calls": 2, "in": 1000000, "out": 0}]}}
        r = ex.a_llm_cost({"days": 7}, HUMAN)
        self.assertTrue(r["ok"])
        self.assertAlmostEqual(r["total"], 0.075, places=6)


class TestUploads(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def sn(method, path, params=None, body=None):
            self.calls.append((method, path, params, body))
            if path == "kb_knowledge_base":
                return [{"sys_id": "kbid1"}]
            if path == "kb_knowledge" and method == "POST":
                return {"number": "KB0010099"}
            return []

        class RAG:
            copies = []

            @staticmethod
            def a_kb_upload(q, u):
                RAG.copies.append(q)
                return {"ok": True}
        self.RAG = RAG
        ex.G.update({"sn": sn, "raw": lambda x: x, "RAG": RAG})

    def test_agent_user_is_refused(self):
        r = ex.a_kb_publish({"type": "sop", "title": "x", "content": "y"}, {"u": "a", "name": "a", "role": "AGENT"})
        self.assertFalse(r["ok"])
        self.assertEqual(self.calls, [])

    def test_bad_type_and_empty_content(self):
        self.assertFalse(ex.a_kb_publish({"type": "zip", "title": "x", "content": "y"}, HUMAN)["ok"])
        self.assertFalse(ex.a_kb_publish({"type": "sop", "title": "", "content": "y"}, HUMAN)["ok"])
        self.assertFalse(ex.a_kb_publish({"type": "sop", "title": "x", "content": "   "}, HUMAN)["ok"])

    def test_sop_goes_to_servicenow_published_with_escaped_html_and_an_agent_copy(self):
        r = ex.a_kb_publish({"type": "sop", "title": "Nginx down", "content": "Step 1 <b>check</b>\nStep 2 & restart"}, HUMAN)
        self.assertTrue(r["ok"], r)
        self.assertEqual((r["destination"], r["number"]), ("servicenow", "KB0010099"))
        post = next(c for c in self.calls if c[0] == "POST")
        body = post[3]
        self.assertEqual(body["workflow_state"], "published")
        self.assertEqual(body["kb_knowledge_base"], "kbid1")
        self.assertIn("&lt;b&gt;check&lt;/b&gt;<br>Step 2 &amp; restart", body["text"])
        self.assertEqual(self.RAG.copies[-1]["name"], "nginx-down.md")
        self.assertTrue(r["agent_copy"])

    def test_missing_knowledge_base_is_a_clear_error(self):
        ex.G["sn"] = lambda method, path, params=None, body=None: []
        r = ex.a_kb_publish({"type": "runbook", "title": "x", "content": "y"}, HUMAN)
        self.assertFalse(r["ok"])
        self.assertIn("was not found", r["error"])


class FakeSSM:
    class exceptions:
        class DocumentAlreadyExists(Exception):
            pass

    def __init__(self, exists=False):
        self.exists, self.created = exists, []

    def create_document(self, **kw):
        if self.exists:
            raise self.exceptions.DocumentAlreadyExists()
        self.created.append(kw)


class TestPlaybooks(unittest.TestCase):
    YAML = "schemaVersion: '2.2'\ndescription: x\nmainSteps:\n  - action: aws:runShellScript\n    name: a\n    inputs:\n      runCommand: [df]\n"

    def use(self, fake):
        ex._ssm = lambda: fake
        ex.G["RAG"] = None
        return fake

    def test_yaml_playbook_becomes_an_ssm_document(self):
        f = self.use(FakeSSM())
        r = ex.a_kb_publish({"type": "playbook", "title": "Disk Check", "content": self.YAML}, HUMAN)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["destination"], "aws_ssm")
        self.assertEqual(f.created[0]["Name"], "MATRIX-PB-disk-check")
        self.assertEqual((f.created[0]["DocumentFormat"], f.created[0]["DocumentType"]), ("YAML", "Command"))
        self.assertIn({"Key": "CreatedBy", "Value": "MATRIX-Console"}, f.created[0]["Tags"])

    def test_json_playbook(self):
        f = self.use(FakeSSM())
        doc = json.dumps({"schemaVersion": "2.2", "mainSteps": []})
        self.assertTrue(ex.a_kb_publish({"type": "playbook", "title": "j", "content": doc}, HUMAN)["ok"])
        self.assertEqual(f.created[0]["DocumentFormat"], "JSON")

    def test_ansible_playbook_is_refused_with_an_explanation(self):
        self.use(FakeSSM())
        r = ex.a_kb_publish({"type": "playbook", "title": "a", "content": "- hosts: all\n  tasks:\n    - ping:\n"}, HUMAN)
        self.assertFalse(r["ok"])
        self.assertIn("schemaVersion and mainSteps", r["error"])

    def test_existing_document_is_never_overwritten(self):
        self.use(FakeSSM(exists=True))
        r = ex.a_kb_publish({"type": "playbook", "title": "Disk Check", "content": self.YAML}, HUMAN)
        self.assertFalse(r["ok"])
        self.assertIn("already exists", r["error"])

    def test_document_name_cannot_be_hijacked(self):
        f = self.use(FakeSSM())
        ex.a_kb_publish({"type": "playbook", "title": "../../AWS-Run Shell;rm", "content": self.YAML}, HUMAN)
        self.assertRegex(f.created[0]["Name"], r"^MATRIX-PB-[a-z0-9-]+$")


class FakeCE:
    def get_cost_and_usage(self, **kw):
        g = lambda svc, rt, amt: {"Keys": [svc, rt], "Metrics": {"UnblendedCost": {"Amount": str(amt)}}}
        return {"ResultsByTime": [{"TimePeriod": {"Start": __import__("datetime").date.today().isoformat()},
                                   "Groups": [g("Amazon Elastic Compute Cloud - Compute", "Usage", 5.0), g("Amazon S3", "Usage", 1.25),
                                              g("AWS Lambda", "Usage", 0.0), g("Amazon Elastic Compute Cloud - Compute", "Credit", -2.0)]}]}


class TestCostReport(unittest.TestCase):
    def test_total_is_before_credits_and_credits_are_reported(self):
        ca.boto3.client = lambda *a, **k: FakeCE()
        ca.CACHE.clear()
        g = {"ACTIONS": {}}
        ca.install(g)
        r = g["ACTIONS"]["cost"]({"days": 7}, HUMAN)
        self.assertTrue(r["ok"])
        self.assertAlmostEqual(r["total"], 6.25)          # EC2 + S3, credit excluded
        self.assertAlmostEqual(r["net_total"], 4.25)      # after the credit
        self.assertAlmostEqual(r["credits"], -2.0)
        names = [s["name"] for s in r["services"]]
        self.assertIn("Amazon S3", names)                 # not only EC2
        self.assertNotIn("AWS Lambda", names)             # free-tier service with no cost is not listed


if __name__ == "__main__":
    unittest.main()
