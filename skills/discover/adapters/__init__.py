"""Reference adapter implementations. Import the ones you need, or use them as
templates for your own (see ../EMBEDDING.md)."""

from .defaults import (
    OpenRouterLLM,
    CannedLLM,
    FileSource,
    HeuristicScorer,
    StdoutPublisher,
    FilePublisher,
    NullStore,
    JsonKnowledgeStore,
    resolve_key,
)

__all__ = [
    "OpenRouterLLM",
    "CannedLLM",
    "FileSource",
    "HeuristicScorer",
    "StdoutPublisher",
    "FilePublisher",
    "NullStore",
    "JsonKnowledgeStore",
    "resolve_key",
]
