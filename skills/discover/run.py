#!/usr/bin/env python3
"""discover — standalone runner wiring the reference adapters.

This is the zero-config entry point: file in → drafted, linted report out. It is
also the worked example for embedding (see EMBEDDING.md) — swap any adapter for
your own (Twitter source, Feishu publisher, a wiki-backed KnowledgeStore, …).

    python3 run.py --demo                         # zero-key end-to-end (CannedLLM)
    python3 run.py --items my.jsonl --config my.yaml   # real LLM (needs OPENROUTER_API_KEY)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # make `core` and `adapters` importable however we're invoked

from core.adapters import LintPolicy, Persona          # noqa: E402
from core.pipeline import DiscoverPipeline, PipelineConfig  # noqa: E402
from adapters.defaults import (                          # noqa: E402
    CannedLLM,
    FilePublisher,
    FileSource,
    HeuristicScorer,
    JsonKnowledgeStore,
    NullStore,
    OpenRouterLLM,
    StdoutPublisher,
)


def _load_yaml(path: Path) -> dict:
    try:
        import yaml
    except ImportError:
        print(
            f"• PyYAML not installed — ignoring {path.name}, using built-in defaults "
            "(pip install pyyaml to use a config file).",
            file=sys.stderr,
        )
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _build_config(cfg: dict) -> tuple[PipelineConfig, LintPolicy, tuple[str, ...]]:
    content_types = tuple(cfg.get("content_types", ["post", "quote", "reply"]))
    pc = PipelineConfig(
        min_per_type=dict(cfg.get("min_per_type", {"post": 2, "quote": 3, "reply": 0})),
        target_total=int(cfg.get("target_total", 0) or 0),
        hard_min_total=int(cfg.get("hard_min_total", 1) or 1),
        shortlist_size=int(cfg.get("shortlist_size", 12) or 12),
        model=cfg.get("model"),
        temperature=cfg.get("temperature"),
        reasoning=cfg.get("reasoning"),
    )
    lc = cfg.get("lint", {}) or {}
    lp = LintPolicy(
        banned_phrases=tuple(lc.get("banned_phrases", [])),
        first_person_markers=tuple(lc.get("first_person_markers", [])),
        max_line_chars=int(lc.get("max_line_chars", 60) or 60),
        enforce_link_last=bool(lc.get("enforce_link_last", True)),
        require_source_trace=bool(lc.get("require_source_trace", True)),
        min_post_chars=int(lc.get("min_post_chars", 30) or 30),
        min_quote_chars=int(lc.get("min_quote_chars", 15) or 15),
    )
    return pc, lp, content_types


def _demo_canned(items_path: Path) -> str:
    """Build a deterministic, source-traceable LLM response from the sample items
    so the full pipeline (incl. the lint guardrail) runs with no API key."""
    rows = [json.loads(ln) for ln in items_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    posts = [{"source_id": r["source_id"], "text": r["text"]} for r in rows[:2]]
    quotes = [{"source_id": r["source_id"], "text": r["text"]} for r in rows[2:3]]
    return json.dumps({"post": posts, "quote": quotes, "reply": []}, ensure_ascii=False)


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the discover pipeline with the reference adapters.")
    ap.add_argument("--items", default=str(HERE / "examples" / "items.sample.jsonl"), help="JSONL of candidate items")
    ap.add_argument("--config", default=str(HERE / "config.example.yaml"), help="run config YAML")
    ap.add_argument("--persona", default=str(HERE / "prompts" / "persona.example.md"))
    ap.add_argument("--generate", default=str(HERE / "prompts" / "generate.example.md"))
    ap.add_argument("--demo", action="store_true", help="use a zero-key CannedLLM (no OPENROUTER_API_KEY needed)")
    ap.add_argument("--model", help="override the LLM model id")
    ap.add_argument("--out-dir", default="out", help="FilePublisher output dir")
    ap.add_argument("--data-dir", help="run-artifact root (sets DISCOVER_DATA_DIR)")
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--stdout", action="store_true", help="publish to stdout instead of a file")
    args = ap.parse_args()

    if args.data_dir:
        import os
        os.environ["DISCOVER_DATA_DIR"] = args.data_dir

    cfg = _load_yaml(Path(args.config)) if Path(args.config).exists() else {}
    pc, lp, content_types = _build_config(cfg)
    if args.model:
        pc.model = args.model

    persona = Persona(
        system=Path(args.persona).read_text(encoding="utf-8"),
        generate_template=Path(args.generate).read_text(encoding="utf-8"),
        content_types=content_types,
        focus_topics=str(cfg.get("focus_topics", "") or ""),
    )

    items_path = Path(args.items)
    llm = CannedLLM(_demo_canned(items_path)) if args.demo else OpenRouterLLM(model=pc.model or "google/gemini-2.5-pro")
    publisher = StdoutPublisher() if args.stdout else FilePublisher(args.out_dir)

    pipeline = DiscoverPipeline(
        llm=llm,
        source=FileSource(items_path),
        scorer=HeuristicScorer(),
        persona=persona,
        publisher=publisher,
        # demo stays idempotent (no memory); real runs keep cross-run dedup
        store=NullStore() if args.demo else JsonKnowledgeStore(),
        lint_policy=lp,
        config=pc,
    )

    result = pipeline.run(spec={"items_path": str(items_path)}, publish=not args.no_publish)
    print(f"✓ discover run {result.run_id}")
    print(f"  outputs : {len(result.outputs)} clean (dropped {result.meta['dropped_by_lint']} by lint)")
    print(f"  run dir : {result.run_dir}")
    if result.published:
        print(f"  published: {result.published}")


if __name__ == "__main__":
    main()
