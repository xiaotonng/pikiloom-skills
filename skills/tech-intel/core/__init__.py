"""tech-intel — an embeddable signal pipeline.

collect (SourceCollector) → score (Scorer) → draft (one LLM call) → lint
(guardrail) → publish (Publisher), with a KnowledgeStore for cross-run memory.

Everything project-specific (where signals come from, what voice to draft in,
where drafts go, what to remember) is injected through the adapter Protocols in
``core.adapters``. The package ships runnable reference adapters in
``adapters.defaults`` so it works standalone, and a worked embedding example in
EMBEDDING.md.
"""

from .schemas import Item, Output, RunPaths, build_item, build_output
from .adapters import (
    LLMClient,
    SourceCollector,
    Scorer,
    Publisher,
    KnowledgeStore,
    UsageMeter,
    Persona,
    LintPolicy,
)
from .pipeline import TechIntelPipeline, PipelineConfig

__all__ = [
    "Item",
    "Output",
    "RunPaths",
    "build_item",
    "build_output",
    "LLMClient",
    "SourceCollector",
    "Scorer",
    "Publisher",
    "KnowledgeStore",
    "UsageMeter",
    "Persona",
    "LintPolicy",
    "TechIntelPipeline",
    "PipelineConfig",
]
