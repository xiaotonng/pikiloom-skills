#!/usr/bin/env python3
"""tech-intel — standalone runner wiring the reference adapters.

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
from core.pipeline import TechIntelPipeline, PipelineConfig  # noqa: E402
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
from adapters.feishu import FeishuPublisher              # noqa: E402
from adapters.twitter_list import TwitterListSource      # noqa: E402


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
        report_style=str(cfg.get("report_style", "buckets") or "buckets"),
        report_title=str(cfg.get("report_title", "Tech-Intel Report") or "Tech-Intel Report"),
        section_titles=dict(cfg.get("section_titles", {}) or {}),
    )
    lc = cfg.get("lint", {}) or {}
    lp = LintPolicy(
        banned_phrases=tuple(lc.get("banned_phrases", [])),
        first_person_markers=tuple(lc.get("first_person_markers", [])),
        scrub_replacements=dict(lc.get("scrub_replacements", {}) or {}),
        max_line_chars=int(lc.get("max_line_chars", 60) or 60),
        enforce_link_last=bool(lc.get("enforce_link_last", True)),
        require_source_trace=bool(lc.get("require_source_trace", True)),
        trace_scope=str(lc.get("trace_scope", "item") or "item"),
        min_post_chars=int(lc.get("min_post_chars", 30) or 30),
        min_quote_chars=int(lc.get("min_quote_chars", 15) or 15),
    )
    return pc, lp, content_types


def _demo_canned(items_path: Path, content_types: tuple[str, ...]) -> str:
    """Build a deterministic, source-traceable LLM response from the sample items
    so the full pipeline (incl. the lint guardrail) runs with no API key. Keys match
    the configured content_types (e.g. posts/quotes), so --demo works whatever the
    default config uses."""
    rows = [json.loads(ln) for ln in items_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    types = list(content_types) or ["post", "quote", "reply"]
    result: dict[str, list] = {t: [] for t in types}
    first = types[0]
    second = types[1] if len(types) > 1 else types[0]
    result[first] = [{"source_id": r["source_id"], "text": r["text"]} for r in rows[:2]]
    result[second] = result[second] + [{"source_id": r["source_id"], "text": r["text"]} for r in rows[2:3]]
    return json.dumps(result, ensure_ascii=False)


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the tech-intel pipeline with the reference adapters.")
    ap.add_argument("--items", default=str(HERE / "examples" / "items.sample.jsonl"), help="JSONL of candidate items")
    ap.add_argument("--config", default=str(HERE / "config.example.yaml"), help="run config YAML")
    ap.add_argument("--persona", default=str(HERE / "prompts" / "persona.example.md"))
    ap.add_argument("--generate", default=str(HERE / "prompts" / "generate.example.md"))
    ap.add_argument("--demo", action="store_true", help="use a zero-key CannedLLM (no OPENROUTER_API_KEY needed)")
    ap.add_argument("--model", help="override the LLM model id")
    ap.add_argument("--out-dir", default="out", help="FilePublisher output dir")
    ap.add_argument("--data-dir", help="run-artifact root (sets TECH_INTEL_DATA_DIR)")
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--stdout", action="store_true", help="publish to stdout instead of a file")
    ap.add_argument("--feishu", action="store_true", help="publish to Feishu (create a doc + DM a card); needs FEISHU_APP_ID/SECRET/RECEIVE_ID")
    ap.add_argument("--feishu-folder", default="", help="optional Feishu folder_token to create the doc in")
    ap.add_argument("--no-headless", action="store_true", help="show the browser window (twitter-list source debugging)")
    args = ap.parse_args()

    if args.data_dir:
        import os
        os.environ["TECH_INTEL_DATA_DIR"] = args.data_dir

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
    llm = CannedLLM(_demo_canned(items_path, content_types)) if args.demo else OpenRouterLLM(model=pc.model or "google/gemini-2.5-pro")

    # Source: config `source.type: twitter-list` → fresh Playwright collection; else FileSource.
    src_cfg = cfg.get("source", {}) or {}
    if not args.demo and str(src_cfg.get("type", "file")).lower() in ("twitter-list", "twitter", "x-list"):
        source = TwitterListSource(
            profile=src_cfg.get("profile"),
            headless=False if args.no_headless else bool(src_cfg.get("headless", True)),
            lists=src_cfg.get("lists") or [],
            list_rounds=int(src_cfg.get("list_rounds", 36) or 36),
            search_queries=src_cfg.get("search_queries") or [],
            search_count_per_query=int(src_cfg.get("search_count_per_query", 15) or 15),
            search_sort=str(src_cfg.get("search_sort", "latest")),
            min_score=float(src_cfg.get("min_score", 0.0) or 0.0),
            max_items=int(src_cfg.get("max_items", 180) or 180),
            enrich_threads=bool(src_cfg.get("enrich_threads", True)),
            max_threads=int(src_cfg.get("max_threads", 12) or 12),
            thread_scroll_rounds=int(src_cfg.get("thread_scroll_rounds", 8) or 8),
        )
        spec: dict = {}
    else:
        source = FileSource(items_path)
        spec = {"items_path": str(items_path)}

    # Publisher: --feishu (or config feishu.enabled) → Feishu doc + card; else stdout/file.
    feishu_cfg = cfg.get("feishu", {}) or {}
    if args.feishu or bool(feishu_cfg.get("enabled")):
        publisher = FeishuPublisher(
            folder_token=args.feishu_folder or str(feishu_cfg.get("folder_token", "") or ""),
            title=str(feishu_cfg.get("title") or pc.report_title),
        )
    elif args.stdout:
        publisher = StdoutPublisher()
    else:
        publisher = FilePublisher(args.out_dir)

    # Store / cross-run dedup. Off for --demo, and off when config `dedup: false`
    # (a once-a-day feed doesn't want yesterday's still-trending tweets filtered out).
    dedup = bool(cfg.get("dedup", True))
    pipeline = TechIntelPipeline(
        llm=llm,
        source=source,
        scorer=HeuristicScorer(),
        persona=persona,
        publisher=publisher,
        store=NullStore() if (args.demo or not dedup) else JsonKnowledgeStore(),
        lint_policy=lp,
        config=pc,
    )

    result = pipeline.run(spec=spec, publish=not args.no_publish)
    print(f"✓ tech-intel run {result.run_id}")
    print(f"  outputs : {len(result.outputs)} clean (dropped {result.meta['dropped_by_lint']} by lint)")
    print(f"  run dir : {result.run_dir}")
    if result.published:
        print(f"  published: {result.published}")


if __name__ == "__main__":
    main()
