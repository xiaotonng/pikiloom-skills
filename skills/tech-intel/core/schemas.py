"""Data contracts for the tech-intel pipeline.

The pipeline passes plain ``dict`` rows internally (cheap to serialize to JSONL,
trivial for adapters to produce). The TypedDicts below document the shape; the
``build_*`` helpers give adapters a typo-proof constructor.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict


class Item(TypedDict, total=False):
    """A candidate signal produced by a SourceCollector.

    Only ``source_id`` and ``text`` are required in practice. ``metrics`` holds
    arbitrary engagement numbers (likes / views / stars / upvotes …) so the
    pipeline stays source-agnostic; a Scorer decides what to do with them.
    """

    source_id: str          # stable, unique id for cross-run dedup (e.g. canonical URL)
    source: str             # which collector produced it (e.g. "twitter-list", "rss")
    text: str               # main content
    context_text: str       # extra body: thread / quoted / parent text
    url: str                # canonical link to the item
    author: str             # handle / name (no leading @ required)
    created_at: str         # ISO timestamp the item was authored
    collected_at: str       # ISO timestamp we collected it
    metrics: dict[str, Any]  # {"likes": 12, "views": 3400, ...} — source-defined
    reference_urls: list[str]  # outbound links worth fetching for grounding
    extra: dict[str, Any]   # any source-specific passthrough
    # ── filled by a Scorer ──
    score: float
    category: str
    one_liner: str
    drop_reason: str


class Output(TypedDict, total=False):
    """A drafted piece of content, keyed back to its source Item."""

    run_id: str
    item_id: str
    source_id: str
    content_type: str       # "post" | "quote" | "reply" | project-defined
    text: str               # the drafted content
    url: str
    author: str
    source_text: str        # source blob the lint guardrail traces facts against
    generated_at: str
    # ── filled by lint ──
    lint_passed: bool
    lint_errors: list[str]
    lint_warnings: list[str]
    extra: dict[str, Any]


def build_item(source_id: str, text: str, **kw: Any) -> Item:
    """Construct an Item with sane defaults. Unknown kwargs land in the row verbatim."""
    row: dict[str, Any] = {
        "source_id": source_id,
        "source": kw.pop("source", ""),
        "text": text,
        "context_text": kw.pop("context_text", ""),
        "url": kw.pop("url", ""),
        "author": kw.pop("author", ""),
        "created_at": kw.pop("created_at", ""),
        "collected_at": kw.pop("collected_at", ""),
        "metrics": kw.pop("metrics", {}) or {},
        "reference_urls": kw.pop("reference_urls", []) or [],
        "extra": kw.pop("extra", {}) or {},
    }
    row.update(kw)
    return row  # type: ignore[return-value]


def build_output(item_id: str, source_id: str, content_type: str, text: str, **kw: Any) -> Output:
    row: dict[str, Any] = {
        "item_id": item_id,
        "source_id": source_id,
        "content_type": content_type,
        "text": text,
        "url": kw.pop("url", ""),
        "author": kw.pop("author", ""),
        "source_text": kw.pop("source_text", ""),
        "generated_at": kw.pop("generated_at", ""),
    }
    row.update(kw)
    return row  # type: ignore[return-value]


@dataclass(frozen=True)
class RunPaths:
    """Run-scoped artifact paths. See core.io.build_run_paths."""

    run_id: str
    run_dir: Path
    items_raw: Path     # collected items (jsonl)
    scored: Path        # scored + shortlisted items (jsonl)
    outputs: Path       # drafted + linted outputs (jsonl)
    report: Path        # human-readable report (md)
    meta: Path          # run metadata (json)
    usage: Path         # llm usage summary (json)
