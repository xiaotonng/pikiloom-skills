"""Tests for the Feishu publisher — no network, no `requests` install needed.

A fake ``requests`` module is injected into ``sys.modules`` so ``publish()`` runs
the real call sequence (token → create doc → write blocks → send card) against a
recording double. ``md_to_feishu_blocks`` is pure and tested directly.
"""

import json
import os
import sys
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "skills" / "tech-intel"
sys.path.insert(0, str(SKILL))

from adapters.feishu import FeishuPublisher, md_to_feishu_blocks  # noqa: E402


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.ok = 200 <= status < 300
        self.text = json.dumps(payload)

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _FakeRequests:
    """Records POSTs and returns a canned response keyed by URL substring."""

    def __init__(self):
        self.calls = []  # list of (url, json_body)

    def post(self, url, *, json=None, headers=None, timeout=None):
        self.calls.append((url, json))
        if "tenant_access_token" in url:
            return _Resp({"code": 0, "tenant_access_token": "t-abc", "expire": 7200})
        if url.endswith("/docx/v1/documents"):
            return _Resp({"code": 0, "data": {"document": {"document_id": "docxTEST123"}}})
        if "/blocks/" in url:
            return _Resp({"code": 0, "data": {}})
        if "/im/v1/messages" in url:
            return _Resp({"code": 0, "data": {"message_id": "om_x"}})
        return _Resp({"code": 0})


class FeishuBlocksTests(unittest.TestCase):
    def test_heading_divider_bullet_and_inline(self):
        md = "# Title\n\n---\n\n- a **bold** point\n[link](https://x/1)"
        blocks = md_to_feishu_blocks(md)
        self.assertEqual(blocks[0]["block_type"], 3)  # heading1
        self.assertEqual(blocks[0]["heading1"]["elements"][0]["text_run"]["content"], "Title")
        self.assertEqual(blocks[1]["block_type"], 22)  # divider
        self.assertEqual(blocks[2]["block_type"], 12)  # bullet
        # the bullet's "bold" run carries the bold style
        bold = [e for e in blocks[2]["bullet"]["elements"] if e["text_run"]["content"] == "bold"]
        self.assertTrue(bold and bold[0]["text_run"]["text_element_style"].get("bold"))
        # the link paragraph keeps the url
        link_run = blocks[3]["text"]["elements"][0]["text_run"]
        self.assertEqual(link_run["text_element_style"]["link"]["url"], "https://x/1")

    def test_paragraph_lines_join_into_one_block(self):
        blocks = md_to_feishu_blocks("line one\nline two")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["text"]["elements"][0]["text_run"]["content"], "line one\nline two")


class FeishuPublisherTests(unittest.TestCase):
    def setUp(self):
        self._real = sys.modules.get("requests")
        self.fake = _FakeRequests()
        sys.modules["requests"] = self.fake

    def tearDown(self):
        if self._real is not None:
            sys.modules["requests"] = self._real
        else:
            sys.modules.pop("requests", None)

    def _pub(self, **kw):
        return FeishuPublisher(app_id="cli_x", app_secret="sec", receive_id="ou_me", **kw)

    def test_happy_path_creates_doc_and_sends_card(self):
        res = self._pub().publish(report_md="# Tech-Intel Report\n\nfirst fact", outputs=[], run_id="r1")
        self.assertTrue(res["ok"])
        self.assertEqual(res["document_id"], "docxTEST123")
        self.assertIn("docxTEST123", res["doc_url"])

        urls = [u for u, _ in self.fake.calls]
        # token fetched once (cached), then create doc, write blocks, send card — in order
        self.assertEqual(sum("tenant_access_token" in u for u in urls), 1)
        order = [next(i for i, u in enumerate(urls) if frag in u)
                 for frag in ("tenant_access_token", "/docx/v1/documents", "/blocks/", "/im/v1/messages")]
        self.assertEqual(order, sorted(order))

        # the card targets the receive_id as an interactive message
        _, card_body = next((u, b) for u, b in self.fake.calls if "/im/v1/messages" in u)
        self.assertEqual(card_body["receive_id"], "ou_me")
        self.assertEqual(card_body["msg_type"], "interactive")
        self.assertIn("docxTEST123", json.dumps(card_body))  # button links to the doc

    def test_folder_token_is_passed_to_create(self):
        self._pub(folder_token="fld_42").publish(report_md="# R\n\nx", outputs=[], run_id="r2")
        _, body = next((u, b) for u, b in self.fake.calls if u.endswith("/docx/v1/documents"))
        self.assertEqual(body["folder_token"], "fld_42")

    def test_missing_creds_skips_without_calling_api(self):
        # empty args fall back to resolve_feishu_cred (env / skills.env); force a clean miss
        import adapters.feishu as fz
        real_resolve = fz.resolve_feishu_cred
        fz.resolve_feishu_cred = lambda name, override=None: override or ""
        try:
            res = FeishuPublisher().publish(report_md="# R\n\nx", outputs=[], run_id="r3")
        finally:
            fz.resolve_feishu_cred = real_resolve
        self.assertFalse(res["ok"])
        self.assertIn("missing", res["skipped"])
        self.assertEqual(self.fake.calls, [])

    def test_api_error_raises_for_pipeline_to_catch(self):
        # token returns a non-zero code → RuntimeError (the pipeline wraps publish in try/except)
        self.fake.post = lambda url, **kw: _Resp({"code": 99, "msg": "bad app secret"})
        with self.assertRaises(RuntimeError):
            self._pub().publish(report_md="# R\n\nx", outputs=[], run_id="r4")


class FeishuCredResolutionTests(unittest.TestCase):
    """The key fix: skills.env must win over the ambient process env, because a
    pikiloom host injects its own bot's FEISHU_* into the environment."""

    def setUp(self):
        import adapters.feishu as fz
        self.fz = fz
        self._real_from_file = fz._from_skills_env
        for k in ("FEISHU_APP_ID", "TECH_INTEL_FEISHU_APP_ID"):
            os.environ.pop(k, None)

    def tearDown(self):
        self.fz._from_skills_env = self._real_from_file
        for k in ("FEISHU_APP_ID", "TECH_INTEL_FEISHU_APP_ID"):
            os.environ.pop(k, None)

    def test_skills_env_beats_generic_process_env(self):
        self.fz._from_skills_env = lambda name: "from-skills-env"
        os.environ["FEISHU_APP_ID"] = "ambient-bot-app"  # the pikiloom-injected collision
        self.assertEqual(self.fz.resolve_feishu_cred("FEISHU_APP_ID"), "from-skills-env")

    def test_dedicated_override_beats_skills_env(self):
        self.fz._from_skills_env = lambda name: "from-skills-env"
        os.environ["TECH_INTEL_FEISHU_APP_ID"] = "dedicated"
        self.assertEqual(self.fz.resolve_feishu_cred("FEISHU_APP_ID"), "dedicated")

    def test_explicit_arg_wins_over_everything(self):
        self.fz._from_skills_env = lambda name: "from-skills-env"
        os.environ["TECH_INTEL_FEISHU_APP_ID"] = "dedicated"
        self.assertEqual(self.fz.resolve_feishu_cred("FEISHU_APP_ID", "explicit"), "explicit")

    def test_generic_env_is_last_resort_when_no_file(self):
        self.fz._from_skills_env = lambda name: ""
        os.environ["FEISHU_APP_ID"] = "ambient-only"
        self.assertEqual(self.fz.resolve_feishu_cred("FEISHU_APP_ID"), "ambient-only")


if __name__ == "__main__":
    unittest.main()
