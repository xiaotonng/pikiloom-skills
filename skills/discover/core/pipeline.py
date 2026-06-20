"""Orchestrator — wires the adapters into one run.

  collect → score/shortlist → draft → lint (drop hard-fails, enforce floor)
          → persist artifacts → publish (non-blocking) → sediment to store

Adapted from an internal discover pipeline's orchestrator + lint policy, dependency-inverted:
the pipeline imports only the adapter Protocols, never a concrete project module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import generate, io, lint
from .adapters import LintPolicy, Persona
from .schemas import Output, RunPaths


@dataclass
class PipelineConfig:
    # how many of each content type to aim for; total target = sum unless overridden
    min_per_type: dict[str, int] = field(default_factory=lambda: {"post": 2, "quote": 3, "reply": 0})
    target_total: int = 0
    hard_min_total: int = 1       # abort the run (don't publish junk) below this many clean outputs
    shortlist_size: int = 12      # cap the candidates handed to the drafter
    model: str | None = None
    temperature: float | None = None
    reasoning: str | None = None

    def total_target(self) -> int:
        return max(sum(int(v or 0) for v in self.min_per_type.values()), int(self.target_total or 0))


@dataclass
class RunResult:
    run_id: str
    run_dir: str
    outputs: list[Output]
    report_md: str
    meta: dict[str, Any]
    published: dict[str, Any] | None


class DiscoverPipeline:
    def __init__(
        self,
        *,
        llm,
        source,
        scorer,
        persona: Persona,
        publisher=None,
        store=None,
        usage=None,
        lint_policy: LintPolicy | None = None,
        config: PipelineConfig | None = None,
    ) -> None:
        self.llm = llm
        self.source = source
        self.scorer = scorer
        self.persona = persona
        self.publisher = publisher
        self.store = store
        self.usage = usage
        self.lint_policy = lint_policy or LintPolicy()
        self.config = config or PipelineConfig()

    def run(
        self,
        *,
        spec: dict[str, Any] | None = None,
        run_id: str | None = None,
        publish: bool = True,
        base: Path | None = None,
    ) -> RunResult:
        spec = spec or {}
        if self.usage is not None:
            self.usage.reset()

        run_id = run_id or io.build_run_id()
        paths: RunPaths = io.build_run_paths(run_id, base=base)
        io.ensure_run_dir(paths)

        # ── collect ──
        items, collect_meta = self.source.collect(run_id=run_id, spec=spec)
        io.write_jsonl_atomic(paths.items_raw, items)
        if not items:
            raise RuntimeError(f"SourceCollector returned 0 items (collect_meta={collect_meta}).")

        # ── score / shortlist (the scorer applies blacklist + posted-dedup via the store) ──
        shortlist, score_meta = self.scorer.shortlist(items, store=self.store, spec=spec)
        shortlist = list(shortlist[: self.config.shortlist_size])
        io.write_jsonl_atomic(paths.scored, shortlist)
        if not shortlist:
            raise RuntimeError(
                f"No candidates after scoring/shortlist (collected={len(items)}; score_meta={score_meta})."
            )

        # ── draft (one LLM call + retry) ──
        outputs = generate.draft(
            llm=self.llm,
            persona=self.persona,
            items=shortlist,
            config=self.config,
            store=self.store,
            run_id=run_id,
        )

        # ── lint: drop hard-failed items, enforce the floor ──
        lookup = {str(i.get("source_id", "")).strip(): i for i in shortlist}
        lint.lint_outputs(outputs, lookup, self.lint_policy)
        dropped = [o for o in outputs if not o.get("lint_passed", True)]
        clean = [o for o in outputs if o.get("lint_passed", True)]
        if len(clean) < self.config.hard_min_total:
            io.write_jsonl_atomic(paths.outputs, outputs)  # keep the rejects for debugging
            raise RuntimeError(
                f"Lint left too few clean outputs to publish: clean={len(clean)} "
                f"< hard_min_total={self.config.hard_min_total}. Run dir: {paths.run_dir}"
            )
        outputs = clean

        report_md = generate.build_report(outputs, self.persona.content_types)
        meta = {
            "run_id": run_id,
            "collected": len(items),
            "shortlisted": len(shortlist),
            "dropped_by_lint": len(dropped),
            "clean": len(outputs),
            "collect_meta": collect_meta,
            "score_meta": score_meta,
        }

        # ── persist ──
        io.write_jsonl_atomic(paths.outputs, outputs)
        io.write_text_atomic(paths.report, report_md)
        io.write_json_atomic(paths.meta, meta)
        if self.usage is not None:
            io.write_json_atomic(paths.usage, self.usage.summary())

        # ── publish (never fatal) ──
        published: dict[str, Any] | None = None
        if publish and self.publisher is not None:
            try:
                published = self.publisher.publish(report_md=report_md, outputs=outputs, run_id=run_id)
            except Exception as e:  # noqa: BLE001 — publish must not crash the run
                published = {"ok": False, "error": str(e)}

        # ── sediment to cross-run memory ──
        if self.store is not None:
            try:
                if published is None or published.get("ok", True):
                    self.store.mark_posted(run_id, outputs)
                self.store.record_run(run_id, {"meta": meta})
            except Exception:  # noqa: BLE001 — best-effort
                pass

        return RunResult(
            run_id=run_id,
            run_dir=str(paths.run_dir),
            outputs=outputs,
            report_md=report_md,
            meta=meta,
            published=published,
        )
