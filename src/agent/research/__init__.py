"""Research domain exports."""

from __future__ import annotations

from .engine import (
    DeepResearch,
    Finding,
    ResearchProvider,
    ResearchReport,
    SearchResult,
    TavilyResearchProvider,
    _deduplicate_sources,
)

__all__ = [
    "DeepResearch",
    "Finding",
    "ResearchProvider",
    "ResearchReport",
    "SearchResult",
    "TavilyResearchProvider",
    "_deduplicate_sources",
]
