"""A 404 from one model slot must fall through to the next slot, not stop the request."""
import io
import json
import os
import sys
import types
import unittest
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambda"))
_b = types.ModuleType("boto3")
_b.client = lambda *a, **k: None
sys.modules.setdefault("boto3", _b)

import gateway as GW  # noqa: E402


def slot(i, model):
    return {"id": "t%d" % i, "role": "x", "url": "http://x/%d" % i, "key": "k", "model": model, "label": model}


class Resp:
    def __init__(self, data):
        self.d = data

    def read(self):
        return json.dumps(self.d).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class T(unittest.TestCase):
    def setUp(self):
        GW.COOL.clear()
        self.orig = GW.urllib.request.urlopen

    def tearDown(self):
        GW.urllib.request.urlopen = self.orig

    def test_404_on_first_slot_uses_the_next(self):
        def fake(req, timeout=0):
            if req.full_url.endswith("/1"):
                raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, io.BytesIO(b"404 page not found"))
            return Resp({"choices": [{"message": {"content": "ok"}}]})
        GW.urllib.request.urlopen = fake
        r = GW.post([slot(1, "bad-model"), slot(2, "good-model")], {"messages": []})
        self.assertEqual(r["model"], "good-model")

    def test_all_404_names_the_slot(self):
        def fake(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, io.BytesIO(b"404 page not found"))
        GW.urllib.request.urlopen = fake
        with self.assertRaises(RuntimeError) as c:
            GW.post([slot(1, "bad-model")], {"messages": []})
        self.assertIn("bad-model", str(c.exception))
        self.assertIn("404", str(c.exception))


if __name__ == "__main__":
    unittest.main()
