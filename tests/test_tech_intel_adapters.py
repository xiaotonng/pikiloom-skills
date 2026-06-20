"""Tests for the reference adapters and the generate/parse helpers.

No API key, no network: OpenRouterLLM is never instantiated; CannedLLM and the
file-backed store/source exercise the real code paths.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "skills" / "tech-intel"
sys.path.insert(0, str(SKILL))

from core import generate  # noqa: E402
from adapters.defaults import (  # noqa: E402
    FileSource,
    HeuristicScorer,
    JsonKnowledgeStore,
    NullStore,
    resolve_key,
)


class ParseJsonTests(unittest.TestCase):
    def test_plain_object(self):
        self.assertEqual(generate.parse_json_object('{"post": []}'), {"post": []})

    def test_strips_code_fences(self):
        self.assertEqual(generate.parse_json_object('```json\n{"post": []}\n```'), {"post": []})

    def test_extracts_from_prose(self):
        self.assertEqual(
            generate.parse_json_object('Here is the JSON: {"post": [{"a": 1}]} done'),
            {"post": [{"a": 1}]},
        )

    def test_garbage_returns_none(self):
        self.assertIsNone(generate.parse_json_object("no json here"))


class HeuristicScorerTests(unittest.TestCase):
    def test_scores_and_sorts_by_engagement(self):
        items = [
            {"source_id": "a", "text": "alpha one", "author": "x", "metrics": {"likes": 10, "views": 1000}},
            {"source_id": "b", "text": "beta", "author": "y", "metrics": {"likes": 100}},
        ]
        kept, meta = HeuristicScorer().shortlist(items, store=NullStore(), spec={})
        self.assertEqual([k["source_id"] for k in kept], ["b", "a"])  # 100 > (10 + 1000/100)
        self.assertEqual(kept[0]["score"], 100.0)
        self.assertEqual(kept[1]["score"], 20.0)
        self.assertEqual(meta["kept"], 2)

    def test_one_liner_is_filled(self):
        # _one_liner splits on 。！？!? and newlines (not the ASCII period)
        kept, _ = HeuristicScorer().shortlist(
            [{"source_id": "a", "text": "First line here\nSecond line"}], store=NullStore(), spec={}
        )
        self.assertEqual(kept[0]["one_liner"], "First line here")


class FileSourceTests(unittest.TestCase):
    def test_parses_jsonl_skips_blanks_and_falls_back_to_url(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "items.jsonl"
            p.write_text(
                '{"source_id":"s1","text":"hello","metrics":{"likes":3}}\n'
                "\n"  # blank line is skipped
                '{"url":"u2","text":"world"}\n',  # no source_id → url used
                encoding="utf-8",
            )
            items, meta = FileSource(p).collect(run_id="r", spec={})
        self.assertEqual([(i["source_id"], i["text"]) for i in items], [("s1", "hello"), ("u2", "world")])
        self.assertEqual(meta["count"], 2)

    def test_missing_file_raises(self):
        with self.assertRaises(RuntimeError):
            FileSource("/no/such/file.jsonl").collect(run_id="r", spec={})


class JsonKnowledgeStoreTests(unittest.TestCase):
    def test_posted_roundtrip_is_case_insensitive(self):
        with tempfile.TemporaryDirectory() as d:
            ks = JsonKnowledgeStore(root=d)
            self.assertFalse(ks.is_posted("http://x/1"))
            added = ks.mark_posted("run1", [{"source_id": "http://x/1"}, {"source_id": "http://x/2"}])
            self.assertEqual(added, 2)
            self.assertTrue(ks.is_posted("http://X/1"))  # case-insensitive match

    def test_blacklist_dedup_filters_in_scorer(self):
        with tempfile.TemporaryDirectory() as d:
            ks = JsonKnowledgeStore(root=d)
            ks.mark_posted("run1", [{"source_id": "u/seen"}])
            items = [
                {"source_id": "u/seen", "text": "already shipped", "author": "a"},
                {"source_id": "u/new", "text": "fresh signal", "author": "b"},
            ]
            kept, meta = HeuristicScorer().shortlist(items, store=ks, spec={})
        self.assertEqual([k["source_id"] for k in kept], ["u/new"])
        self.assertEqual(meta["drops"]["already_posted"], 1)


class ResolveKeyTests(unittest.TestCase):
    def test_env_var_wins(self):
        os.environ["TECH_INTEL_TEST_KEY"] = "from-env"
        try:
            self.assertEqual(resolve_key("TECH_INTEL_TEST_KEY"), "from-env")
        finally:
            del os.environ["TECH_INTEL_TEST_KEY"]

    def test_missing_key_returns_empty(self):
        self.assertEqual(resolve_key("DEFINITELY_NOT_SET_4Q7X"), "")


if __name__ == "__main__":
    unittest.main()
