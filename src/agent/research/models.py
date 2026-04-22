"""Data models for the deep research engine."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SearchResult:
    """A single search hit."""

    title: str
    url: str
    snippet: str


@dataclass
class Finding:
    """An extracted piece of information with provenance."""

    content: str
    source_url: str
    source_title: str
    query: str
    round: int


@dataclass
class ResearchReport:
    """Final output of a deep research session."""

    topic: str
    synthesis: str
    findings: list[Finding] = field(default_factory=list)
    sources: list[dict[str, str]] = field(default_factory=list)
    search_angles: list[str] = field(default_factory=list)
    rounds_executed: int = 0
    total_searches: int = 0
    total_fetches: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    saturated: bool = False
