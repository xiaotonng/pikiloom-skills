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
from .feishu import FeishuPublisher, md_to_feishu_blocks
from .twitter_list import TwitterListSource

__all__ = [
    "OpenRouterLLM",
    "CannedLLM",
    "FileSource",
    "TwitterListSource",
    "HeuristicScorer",
    "StdoutPublisher",
    "FilePublisher",
    "FeishuPublisher",
    "md_to_feishu_blocks",
    "NullStore",
    "JsonKnowledgeStore",
    "resolve_key",
]
