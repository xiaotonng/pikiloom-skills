"""Offline tests for video-use's pure helper functions.

The ffmpeg/Playwright/PIL paths need real binaries and are exercised by the
SKILL's manual pipeline, not here. These tests cover the deterministic logic:
SRT timestamp formatting, subtitle cue splitting, and spec derivation from a
recorder manifest — all importable with the stdlib alone.
"""

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "video-use" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import compose_narrated as cn  # noqa: E402


class SrtTimestampTests(unittest.TestCase):
    def test_formats_hms_millis(self):
        self.assertEqual(cn.srt_ts(3661.5), "01:01:01,500")

    def test_zero(self):
        self.assertEqual(cn.srt_ts(0), "00:00:00,000")


class SplitCuesTests(unittest.TestCase):
    def test_splits_on_punctuation_proportionally(self):
        cues = cn.split_cues("第一句,第二句。第三句", 10.0, 6.0)
        self.assertEqual([t for _a, _b, t in cues], ["第一句", "第二句", "第三句"])
        # equal-length parts → equal durations summing to the total
        self.assertAlmostEqual(cues[0][0], 10.0)
        self.assertAlmostEqual(cues[-1][1], 16.0)

    def test_empty_text_yields_no_cues(self):
        self.assertEqual(cn.split_cues("   ", 0.0, 5.0), [])


class DeriveSpecTests(unittest.TestCase):
    def test_builds_one_segment_per_narrated_page(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            man = tmp / "m.json"
            nar = tmp / "n.json"
            raw = tmp / "raw.webm"
            raw.write_bytes(b"x")
            man.write_text(json.dumps({"events": [
                {"page": "Home", "enter": 1.0, "settled": 1.5, "leave": 5.0},
                {"page": "Agents", "enter": 5.0, "settled": 5.4, "leave": 9.0},
            ]}))
            nar.write_text(json.dumps({"Home": "首页旁白", "Agents": "代理旁白"}))
            args = argparse.Namespace(
                manifest=str(man), narration=str(nar), source=str(raw),
                out_dir=None, head_trim=1.0, speed=4.0, load_window=1.2,
            )
            spec = cn.derive_spec_from_manifest(args)
        self.assertEqual([s["name"] for s in spec["segments"]], ["Home", "Agents"])
        self.assertEqual(spec["segments"][0]["narration"], "首页旁白")
        self.assertTrue(spec["source"].endswith("raw.webm"))

    def test_pages_without_narration_are_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            man = tmp / "m.json"
            nar = tmp / "n.json"
            raw = tmp / "raw.webm"
            raw.write_bytes(b"x")
            man.write_text(json.dumps({"events": [
                {"page": "Home", "enter": 1.0, "settled": 1.5, "leave": 5.0},
                {"page": "Hidden", "enter": 5.0, "settled": 5.4, "leave": 9.0},
            ]}))
            nar.write_text(json.dumps({"Home": "只讲首页"}))
            args = argparse.Namespace(
                manifest=str(man), narration=str(nar), source=str(raw),
                out_dir=None, head_trim=1.0, speed=4.0, load_window=1.2,
            )
            spec = cn.derive_spec_from_manifest(args)
        self.assertEqual([s["name"] for s in spec["segments"]], ["Home"])


if __name__ == "__main__":
    unittest.main()
