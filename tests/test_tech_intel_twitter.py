"""Tests for the TwitterListSource helpers + item mapping — no browser, no network.

`collect()` needs Playwright + a logged-in profile (exercised live, see SKILL.md);
the pure parts below (count parsing, URL normalization, and the raw-row → Item
mapping with min-score filter / dedup / cap) are covered offline.
"""

import sys
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "skills" / "tech-intel"
sys.path.insert(0, str(SKILL))

from adapters.twitter_list import (  # noqa: E402
    TwitterListSource,
    canonical_status_url,
    normalize_list_url,
    to_int,
)


class ToIntTests(unittest.TestCase):
    def test_suffixes_and_plain(self):
        self.assertEqual(to_int("1.2K"), 1200)
        self.assertEqual(to_int("3M"), 3_000_000)
        self.assertEqual(to_int("1.5万"), 15_000)
        self.assertEqual(to_int("1,234"), 1234)
        self.assertEqual(to_int("42"), 42)
        self.assertEqual(to_int(""), 0)
        self.assertEqual(to_int(None), 0)
        self.assertEqual(to_int("12 likes"), 12)


class UrlTests(unittest.TestCase):
    def test_normalize_list_url(self):
        self.assertEqual(normalize_list_url("1585430245762441216"), "https://x.com/i/lists/1585430245762441216")
        self.assertEqual(normalize_list_url("https://x.com/i/lists/123"), "https://x.com/i/lists/123")
        self.assertEqual(normalize_list_url("x.com/foo/lists/999"), "https://x.com/i/lists/999")
        self.assertEqual(normalize_list_url("not-a-url"), "")

    def test_canonical_status_url(self):
        self.assertEqual(
            canonical_status_url("https://x.com/foo/status/123/photo/1"),
            "https://x.com/foo/status/123",
        )
        self.assertEqual(
            canonical_status_url("https://twitter.com/Bar_9/status/42"),
            "https://x.com/Bar_9/status/42",
        )


class ToItemsTests(unittest.TestCase):
    def _rows(self):
        return [
            {"handle": "@alice", "text": "big news", "likes": "10", "retweets": "2",
             "replies": "1", "views": "5000", "created_at": "2026-06-21T00:00:00.000Z",
             "url": "https://x.com/alice/status/1", "external_links": ["https://blog/x"], "quoted_urls": []},
            {"handle": "@bob", "text": "tiny", "likes": "0", "retweets": "0",
             "replies": "0", "views": "1", "url": "https://x.com/bob/status/2"},
            # duplicate of the first (same canonical url) — should be deduped
            {"handle": "@alice", "text": "big news (again)", "likes": "9",
             "url": "https://x.com/alice/status/1/photo/1"},
        ]

    def test_maps_fields_and_metrics(self):
        src = TwitterListSource(min_score=0.0)
        items, _ = (src._to_items(self._rows()), None)
        a = next(i for i in items if i["author"] == "alice")
        self.assertEqual(a["source_id"], "https://x.com/alice/status/1")
        self.assertEqual(a["url"], "https://x.com/alice/status/1")
        self.assertEqual(a["metrics"], {"likes": 10, "retweets": 2, "replies": 1, "views": 5000})
        self.assertEqual(a["reference_urls"], ["https://blog/x"])
        self.assertEqual(a["source"], "twitter-list")

    def test_dedup_by_canonical_url(self):
        src = TwitterListSource(min_score=0.0)
        items = src._to_items(self._rows())
        ones = [i for i in items if i["source_id"] == "https://x.com/alice/status/1"]
        self.assertEqual(len(ones), 1)  # the /photo/1 dupe folds into the same canonical id

    def test_min_score_filters_and_sorts(self):
        # score = likes*2 + rt*3 + replies + views/100 → alice=10*2+2*3+1+50=77, bob=0+0+0+0.01
        src = TwitterListSource(min_score=1.0)
        items = src._to_items(self._rows())
        self.assertEqual([i["author"] for i in items], ["alice"])  # bob (0.01) dropped, alice kept
        self.assertGreater(items[0]["score"], 1.0)

    def test_max_items_cap(self):
        src = TwitterListSource(min_score=0.0, max_items=1)
        items = src._to_items(self._rows())
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["author"], "alice")  # highest score first


if __name__ == "__main__":
    unittest.main()
