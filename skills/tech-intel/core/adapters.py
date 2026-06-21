"""Adapter contracts — the only seams between the generic pipeline and a project.

A host project (see the worked example in EMBEDDING.md) supplies a
concrete implementation of each Protocol it needs; the pipeline itself imports
none of them directly. Reference implementations live in ``adapters.defaults``.

Design note: every Protocol is structural (PEP 544) — you do NOT need to subclass
anything. Any object with matching methods satisfies it, so adapting an existing
class (a wiki reader, a Feishu client, an OpenAI wrapper) is a thin shim, not a
rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .schemas import Item, Output


@runtime_checkable
class LLMClient(Protocol):
    """One blocking chat completion. Return the assistant text (the draft step
    parses JSON out of it). Keep retries/backoff inside the implementation."""

    def complete(
        self,
        system: str,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float | None = None,
        reasoning: str | None = None,
    ) -> str: ...


@runtime_checkable
class SourceCollector(Protocol):
    """Produce candidate items for a run. ``spec`` is the per-run override bag
    (topics, source ids, search queries …). Return (items, meta)."""

    def collect(self, *, run_id: str, spec: dict[str, Any]) -> tuple[list[Item], dict[str, Any]]: ...


@runtime_checkable
class Scorer(Protocol):
    """Score, filter, and shortlist items. Sets each kept item's ``score`` /
    ``category`` / ``one_liner`` and returns the shortlist (already sorted)."""

    def shortlist(
        self, items: list[Item], *, store: "KnowledgeStore", spec: dict[str, Any]
    ) -> tuple[list[Item], dict[str, Any]]: ...


@runtime_checkable
class Publisher(Protocol):
    """Deliver the finished report somewhere (Feishu / Slack / file / stdout).
    Must not raise fatally — the pipeline treats publish failure as non-blocking."""

    def publish(self, *, report_md: str, outputs: list[Output], run_id: str) -> dict[str, Any]: ...


@runtime_checkable
class KnowledgeStore(Protocol):
    """Cross-run memory. A no-op store is a valid implementation (see defaults).

    - blacklist / allowlist gate collection
    - is_posted / mark_posted give cross-run dedup
    - writing_context is injected into the draft prompt (style anchors, audience…)
    - record_run persists lessons / proposals after a run
    """

    def blacklist(self) -> set[str]: ...
    def is_posted(self, key: str) -> bool: ...
    def mark_posted(self, run_id: str, outputs: list[Output]) -> int: ...
    def writing_context(self, *, topics: list[str]) -> str: ...
    def record_run(self, run_id: str, refs: dict[str, Any]) -> None: ...


@runtime_checkable
class UsageMeter(Protocol):
    """Optional token/cost accounting around LLM calls."""

    def reset(self) -> None: ...
    def summary(self) -> dict[str, Any]: ...


# ── Configuration value objects (not adapters — plain data the host supplies) ──


@dataclass
class Persona:
    """The voice + format the drafter writes in.

    ``system`` is the system prompt (the *sanitized* example ships in
    prompts/persona.example.md — keep your real brand voice private).
    ``generate_template`` is the user-message template; ``{{ITEMS_BLOCK}}`` and
    ``{{TARGET_TOTAL}}``/``{{MIN_*}}`` placeholders are filled per run.
    ``content_types`` are the output buckets the LLM returns as JSON keys.
    """

    system: str
    generate_template: str
    content_types: tuple[str, ...] = ("post", "quote", "reply")
    focus_topics: str = ""


@dataclass
class LintPolicy:
    """Guardrail configuration. The *structural* checks (unsourced numbers/handles,
    dropped negation, thin content, broken line breaks, link position) are always
    on. The lexical lists below are project-specific and default to small neutral
    examples — supply your own banned phrasing here, not in code."""

    banned_phrases: tuple[str, ...] = ()      # hard-drop if present (marketing fluff etc.)
    first_person_markers: tuple[str, ...] = ()  # hard-drop: brand-voice leakage when writing 3rd-person
    scrub_replacements: dict[str, str] = field(default_factory=dict)  # deterministic pre-lint rewrites: {bad: good} substring swaps (e.g. 死磕→攻坚) — rewrite cheap cringe instead of dropping a good piece
    max_line_chars: int = 60                  # soft warn above this
    enforce_link_last: bool = True            # soft warn if main link isn't the last line
    require_source_trace: bool = True         # hard-drop numbers/@handles absent from source
    trace_scope: str = "item"                 # "item": trace vs the output's own source; "corpus": vs ALL collected items — lets a synthesized piece pull facts across sources while still blocking fabrication
    min_post_chars: int = 30
    min_quote_chars: int = 15
    extra: dict[str, Any] = field(default_factory=dict)
