"""End-to-end tests for the tech-intel pipeline using the zero-key CannedLLM.

Covers the whole orchestration (collect → score → draft → lint → report) and,
critically, proves the lint guardrail drops a fabricated number inside a real run
— not just in isolation. No API key, no network.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "skills" / "tech-intel"
sys.path.insert(0, str(SKILL))

from core.adapters import LintPolicy, Persona  # noqa: E402
from core.pipeline import PipelineConfig, TechIntelPipeline  # noqa: E402
from adapters.defaults import CannedLLM, FileSource, HeuristicScorer, NullStore  # noqa: E402

ITEMS = [
    {"source_id": "u/a", "text": "Acme Engine shipped today.\nIt cut cold-start latency to 390ms.",
     "metrics": {"likes": 50, "views": 4000}},
    {"source_id": "u/b", "text": "QueryIO added a read cache.\nRead latency dropped to 390ms.",
     "metrics": {"likes": 30}},
    {"source_id": "u/c", "text": "RunWild ships a single 8MB Go binary.\nIt freezes the prefix for caching.",
     "metrics": {"likes": 10}},
]

PERSONA = Persona(
    system="You write concise, source-grounded notes.",
    generate_template="Items:\n{{ITEMS_BLOCK}}\nTarget {{TARGET_TOTAL}}.",
    content_types=("post", "quote", "reply"),
)


def _write_items(tmp: Path) -> Path:
    p = tmp / "items.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in ITEMS) + "\n", encoding="utf-8")
    return p


def _pipeline(canned: str) -> TechIntelPipeline:
    return TechIntelPipeline(
        llm=CannedLLM(canned),
        source=FileSource(),
        scorer=HeuristicScorer(),
        persona=PERSONA,
        publisher=None,           # no publish side effect in tests
        store=NullStore(),        # idempotent, no cross-run memory
        lint_policy=LintPolicy(),
        config=PipelineConfig(),
    )


class PipelineCleanRun(unittest.TestCase):
    def test_all_outputs_pass_lint(self):
        # canned response echoes source text → every fact is sourced → 0 drops
        canned = json.dumps({
            "post": [{"source_id": "u/a", "text": ITEMS[0]["text"]},
                     {"source_id": "u/b", "text": ITEMS[1]["text"]}],
            "quote": [{"source_id": "u/c", "text": ITEMS[2]["text"]}],
            "reply": [],
        }, ensure_ascii=False)
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            result = _pipeline(canned).run(spec={"items_path": str(_write_items(tmp))}, base=tmp)
            # artifacts are persisted under the run dir (checked before tmp is cleaned)
            self.assertTrue((Path(result.run_dir) / "outputs.jsonl").exists())
            self.assertTrue((Path(result.run_dir) / "report.md").exists())
        self.assertEqual(len(result.outputs), 3)
        self.assertEqual(result.meta["dropped_by_lint"], 0)
        self.assertIn("# Tech-Intel Report", result.report_md)


class PipelineGuardrail(unittest.TestCase):
    def test_fabricated_number_is_dropped_end_to_end(self):
        # one post invents "900%" (absent from source) → must be dropped by lint;
        # the sourced quote survives.
        canned = json.dumps({
            "post": [{"source_id": "u/a", "text": "Acme is 900% faster overnight.\nHuge win today."}],
            "quote": [{"source_id": "u/c", "text": ITEMS[2]["text"]}],
            "reply": [],
        }, ensure_ascii=False)
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            result = _pipeline(canned).run(spec={"items_path": str(_write_items(tmp))}, base=tmp)
        self.assertEqual(result.meta["dropped_by_lint"], 1)
        self.assertEqual(len(result.outputs), 1)
        self.assertNotIn("900%", result.outputs[0]["text"])

    def test_too_few_clean_outputs_aborts(self):
        # every draft is a fabrication → nothing clean → run must refuse to publish
        canned = json.dumps({
            "post": [{"source_id": "u/a", "text": "Acme is 900% faster.\nUp 50000x today."}],
            "quote": [],
            "reply": [],
        }, ensure_ascii=False)
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            with self.assertRaises(RuntimeError):
                _pipeline(canned).run(spec={"items_path": str(_write_items(tmp))}, base=tmp)


class DemoSmoke(unittest.TestCase):
    """The README advertises `run.py --demo` as a zero-key smoke test — assert it."""

    def test_demo_runs_clean(self):
        with tempfile.TemporaryDirectory() as d:
            proc = subprocess.run(
                [sys.executable, str(SKILL / "run.py"), "--demo",
                 "--data-dir", str(Path(d) / "data"), "--out-dir", str(Path(d) / "out")],
                capture_output=True, text=True, timeout=60,
            )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("tech-intel run", proc.stdout)
        self.assertIn("clean", proc.stdout)


if __name__ == "__main__":
    unittest.main()
