"""Unit tests for the tech-intel lint guardrail — the anti-fabrication / anti-fluff
pass that makes drafts safe to publish. These are the highest-value tests in the
repo: they pin the *structural* checks that are always on.

Zero-dependency: stdlib `unittest`, no pip install, no API key, no network.
"""

import sys
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "skills" / "tech-intel"
sys.path.insert(0, str(SKILL))

from core import lint  # noqa: E402
from core.adapters import LintPolicy  # noqa: E402

# A source WITH a negation — used for the negation-preservation tests.
SRC_NEG = "Acme cut cold-start latency from 1200ms to 390ms on an M2. Does NOT support Windows."
# A source WITHOUT a negation — used so unsourced/clean tests are not also tripped
# by the negation check.
SRC_CLEAN = "Acme cut cold-start latency to 390ms on an M2. The data layer now uses reflink copies."


class ExtractTests(unittest.TestCase):
    def test_extract_fact_bearing_numbers(self):
        nums = lint.extract_numbers("390ms 8倍 50% v2.3")
        self.assertIn("390ms", nums)
        self.assertIn("8倍", nums)
        self.assertIn("50%", nums)
        self.assertIn("v2.3", nums)  # version tokens count as fact-bearing

    def test_numbers_inside_urls_are_ignored(self):
        # status ids in URLs / handles must not be treated as claims
        self.assertNotIn("123456", lint.extract_numbers("see https://x.com/s/123456 now"))

    def test_extract_handles(self):
        self.assertEqual(lint.extract_handles("hi @marin and @acme_labs"), ["@marin", "@acme_labs"])

    def test_number_forms_unit_equivalence(self):
        # "8倍" in a draft must be recognised against "8x" in the source
        self.assertIn("8x", lint._number_forms("8倍"))


class UnsourcedEntityTests(unittest.TestCase):
    def test_sourced_number_passes(self):
        self.assertEqual(lint.detect_unsourced_entities("now 390ms", SRC_CLEAN), [])

    def test_unsourced_number_flagged(self):
        self.assertEqual(lint.detect_unsourced_entities("up 900%", SRC_CLEAN), ["number:900%"])

    def test_unsourced_handle_flagged(self):
        self.assertEqual(
            lint.detect_unsourced_entities("ping @ghost", "no handles here"), ["handle:@ghost"]
        )

    def test_unit_equivalent_number_is_sourced(self):
        # draft says "8倍", source says "8x" — equivalent, so NOT flagged
        self.assertEqual(lint.detect_unsourced_entities("8倍 faster", "8x faster"), [])


class NegationTests(unittest.TestCase):
    def test_dropped_negation_flagged(self):
        self.assertEqual(
            lint.detect_negation_drop("supports Windows", "does NOT support Windows"),
            ["missing_negation"],
        )

    def test_preserved_chinese_negation_passes(self):
        self.assertEqual(lint.detect_negation_drop("不支持 Windows", "不支持 Windows"), [])

    def test_no_source_negation_is_noop(self):
        self.assertEqual(lint.detect_negation_drop("supports it fully", "all good here"), [])


class ThinContentTests(unittest.TestCase):
    def setUp(self):
        self.policy = LintPolicy()

    def test_empty_is_no_content(self):
        self.assertEqual(
            lint.detect_thin_content("", content_type="post", policy=self.policy), ["no_content"]
        )

    def test_short_post_flags_multiple(self):
        issues = lint.detect_thin_content("hi there", content_type="post", policy=self.policy)
        self.assertIn("too_few_lines", issues)
        self.assertIn("too_short", issues)
        self.assertIn("no_concrete_signal", issues)

    def test_good_post_passes(self):
        good = "Acme v2 shipped today.\nIt cut latency to 390ms."
        self.assertEqual(lint.detect_thin_content(good, content_type="post", policy=self.policy), [])


class LintItemTests(unittest.TestCase):
    def test_clean_post_passes(self):
        item = {
            "text": "Acme cut cold-start latency to 390ms.\nThe data layer uses reflink copies now.",
            "content_type": "post",
        }
        passed, hard, _soft = lint.lint_item(item, SRC_CLEAN, LintPolicy())
        self.assertTrue(passed, msg=f"expected clean, got hard errors: {hard}")
        self.assertEqual(hard, [])

    def test_fabricated_number_is_hard_fail(self):
        item = {"text": "Acme got 900% faster overnight.\nReally quick now.", "content_type": "post"}
        passed, hard, _ = lint.lint_item(item, SRC_CLEAN, LintPolicy())
        self.assertFalse(passed)
        self.assertIn("unsourced:number:900%", hard)

    def test_banned_phrase_is_hard_fail(self):
        policy = LintPolicy(banned_phrases=("revolution",))
        item = {"text": "a revolution in 390ms speed\nsecond line here", "content_type": "post"}
        passed, hard, _ = lint.lint_item(item, SRC_CLEAN, policy)
        self.assertFalse(passed)
        self.assertIn("banned:revolution", hard)

    def test_empty_text_is_hard_fail(self):
        passed, hard, _ = lint.lint_item({"text": "   "}, SRC_CLEAN, LintPolicy())
        self.assertFalse(passed)
        self.assertEqual(hard, ["empty"])


class LintOutputsTests(unittest.TestCase):
    def test_enriches_outputs_in_place(self):
        outputs = [
            {
                "source_id": "s1",
                "content_type": "post",
                "text": "Acme cut latency to 390ms.\nReflink copies now.",
            },
            {"source_id": "s2", "content_type": "post", "text": "Acme is 900% faster.\nWow today."},
        ]
        lookup = {
            "s1": {"text": SRC_CLEAN},
            "s2": {"text": SRC_CLEAN},
        }
        lint.lint_outputs(outputs, lookup, LintPolicy())
        self.assertTrue(outputs[0]["lint_passed"])
        self.assertFalse(outputs[1]["lint_passed"])
        self.assertIn("unsourced:number:900%", outputs[1]["lint_errors"])


if __name__ == "__main__":
    unittest.main()
