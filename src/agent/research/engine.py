"""Compatibility re-exports for the deep research engine."""

from __future__ import annotations

from .models import Finding, ResearchReport, SearchResult
from .providers import ResearchProvider, TavilyResearchProvider
from .workflow import DeepResearch, _deduplicate_sources

__all__ = [
    "DeepResearch",
    "Finding",
    "ResearchProvider",
    "ResearchReport",
    "SearchResult",
    "TavilyResearchProvider",
    "_deduplicate_sources",
]
