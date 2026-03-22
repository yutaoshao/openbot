"""Deep research engine — multi-round search with saturation detection.

Decomposes a research topic into search angles, executes multiple rounds
of web search + content extraction, detects when new information is
exhausted, and synthesises a structured report.

Usage::

    dr = DeepResearch(model_gateway, event_bus, provider)
    report = await dr.research("Python async frameworks comparison")
    print(report.synthesis)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from src.core.logging import get_logger

if TYPE_CHECKING:
    from src.infrastructure.event_bus import EventBus
    from src.infrastructure.model_gateway import ModelGateway

logger = get_logger(__name__)

# -- Defaults ----------------------------------------------------------------

DEFAULT_MAX_ROUNDS = 5
DEFAULT_ANGLES_COUNT = 6
DEFAULT_SATURATION_THRESHOLD = 0.15  # <15% new findings → saturated
DEFAULT_MAX_SOURCES_PER_ROUND = 3  # top URLs to deep-fetch per round


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

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
    query: str  # the search query that led to this finding
    round: int  # which research round discovered it


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
    cost: float = 0.0
    latency_ms: int = 0
    saturated: bool = False


# ---------------------------------------------------------------------------
# ResearchProvider protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class ResearchProvider(Protocol):
    """Pluggable backend for search and content extraction."""

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Execute a web search and return results."""
        ...

    async def fetch(self, url: str, max_length: int = 8000) -> str:
        """Fetch and extract text content from a URL."""
        ...


# ---------------------------------------------------------------------------
# Built-in provider: Tavily (web_search + web_fetch tools)
# ---------------------------------------------------------------------------

class TavilyResearchProvider:
    """ResearchProvider backed by WebSearchTool and WebFetchTool.

    Reuses the existing built-in tools so all configuration (API keys,
    timeouts) is shared with the agent's tool layer.
    """

    def __init__(self) -> None:
        from src.tools.builtin.web_fetch import WebFetchTool
        from src.tools.builtin.web_search import WebSearchTool

        self._search_tool = WebSearchTool()
        self._fetch_tool = WebFetchTool()

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        result = await self._search_tool.execute({
            "query": query,
            "max_results": max_results,
        })
        if result.is_error:
            logger.warning("research.search_error", query=query, error=result.content)
            return []
        return self._parse_search_results(result.content)

    async def fetch(self, url: str, max_length: int = 8000) -> str:
        result = await self._fetch_tool.execute({
            "url": url,
            "max_length": max_length,
        })
        if result.is_error:
            logger.warning("research.fetch_error", url=url, error=result.content)
            return ""
        return result.content

    @staticmethod
    def _parse_search_results(raw: str) -> list[SearchResult]:
        """Parse WebSearchTool's formatted output back to structured data."""
        results: list[SearchResult] = []
        current_title = ""
        current_url = ""
        current_snippet = ""

        for line in raw.split("\n"):
            line = line.strip()
            if not line:
                continue

            # Lines like: "1. [Title](url)"
            if line[0].isdigit() and ". [" in line:
                # Save previous
                if current_url:
                    results.append(SearchResult(
                        title=current_title, url=current_url,
                        snippet=current_snippet.strip(),
                    ))
                # Parse new
                try:
                    bracket_start = line.index("[") + 1
                    bracket_end = line.index("](")
                    paren_end = line.index(")", bracket_end + 2)
                    current_title = line[bracket_start:bracket_end]
                    current_url = line[bracket_end + 2:paren_end]
                    current_snippet = ""
                except ValueError:
                    current_title = line
                    current_url = ""
                    current_snippet = ""
            elif line.startswith("Summary:"):
                continue  # skip Tavily summary line
            else:
                current_snippet += " " + line

        # Don't forget the last one
        if current_url:
            results.append(SearchResult(
                title=current_title, url=current_url,
                snippet=current_snippet.strip(),
            ))

        return results


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

class DeepResearch:
    """Multi-round deep research engine.

    Flow::

        1. Plan search angles (LLM)
        2. For each round:
           a. Execute searches for remaining angles
           b. Deep-fetch top URLs
           c. Extract findings (LLM)
           d. Check saturation
        3. Synthesise structured report (LLM)
    """

    def __init__(
        self,
        model_gateway: ModelGateway,
        event_bus: EventBus,
        provider: ResearchProvider | None = None,
    ) -> None:
        self._gateway = model_gateway
        self._event_bus = event_bus
        self._provider = provider or TavilyResearchProvider()

    async def research(
        self,
        topic: str,
        *,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        angles_count: int = DEFAULT_ANGLES_COUNT,
        saturation_threshold: float = DEFAULT_SATURATION_THRESHOLD,
        max_sources_per_round: int = DEFAULT_MAX_SOURCES_PER_ROUND,
    ) -> ResearchReport:
        """Execute a full deep-research session on *topic*."""
        start = time.monotonic()
        total_tokens_in = 0
        total_tokens_out = 0
        total_cost = 0.0
        total_searches = 0
        total_fetches = 0
        all_findings: list[Finding] = []
        seen_urls: set[str] = set()

        await self._event_bus.publish("research.start", {"topic": topic})

        # Step 1: Plan search angles
        angles, usage = await self._plan_angles(topic, angles_count)
        total_tokens_in += usage.get("tokens_in", 0)
        total_tokens_out += usage.get("tokens_out", 0)
        total_cost += usage.get("cost", 0.0)

        logger.info(
            "research.angles_planned",
            topic=topic,
            angle_count=len(angles),
        )

        # Step 2: Multi-round search
        saturated = False
        rounds_executed = 0

        for round_num in range(1, max_rounds + 1):
            rounds_executed = round_num

            # Pick angles to search this round (rotate through remaining)
            round_angles = self._pick_round_angles(angles, round_num)
            if not round_angles:
                logger.info("research.no_more_angles", round=round_num)
                break

            # Search
            round_results: list[tuple[str, SearchResult]] = []
            for angle in round_angles:
                results = await self._provider.search(angle)
                total_searches += 1
                for r in results:
                    if r.url not in seen_urls:
                        round_results.append((angle, r))
                        seen_urls.add(r.url)

            if not round_results:
                logger.info("research.no_new_results", round=round_num)
                saturated = True
                break

            # Deep-fetch top URLs
            fetched_contents: list[tuple[str, SearchResult, str]] = []
            urls_to_fetch = round_results[:max_sources_per_round]
            for query, sr in urls_to_fetch:
                content = await self._provider.fetch(sr.url)
                total_fetches += 1
                if content:
                    fetched_contents.append((query, sr, content))

            # Extract findings via LLM
            new_findings, usage = await self._extract_findings(
                topic, round_num, round_results, fetched_contents, all_findings,
            )
            total_tokens_in += usage.get("tokens_in", 0)
            total_tokens_out += usage.get("tokens_out", 0)
            total_cost += usage.get("cost", 0.0)

            # Saturation detection
            if all_findings:
                novelty_ratio = len(new_findings) / max(len(all_findings), 1)
                if novelty_ratio < saturation_threshold:
                    logger.info(
                        "research.saturated",
                        round=round_num,
                        novelty_ratio=f"{novelty_ratio:.2f}",
                    )
                    all_findings.extend(new_findings)
                    saturated = True
                    break

            all_findings.extend(new_findings)

            logger.info(
                "research.round_complete",
                round=round_num,
                new_findings=len(new_findings),
                total_findings=len(all_findings),
            )

            await self._event_bus.publish("research.round", {
                "topic": topic,
                "round": round_num,
                "new_findings": len(new_findings),
                "total_findings": len(all_findings),
                "saturated": False,
            })

        # Step 3: Synthesise report
        synthesis, usage = await self._synthesise(topic, all_findings)
        total_tokens_in += usage.get("tokens_in", 0)
        total_tokens_out += usage.get("tokens_out", 0)
        total_cost += usage.get("cost", 0.0)

        latency_ms = int((time.monotonic() - start) * 1000)

        # Deduplicate sources
        sources = _deduplicate_sources(all_findings)

        report = ResearchReport(
            topic=topic,
            synthesis=synthesis,
            findings=all_findings,
            sources=sources,
            search_angles=angles,
            rounds_executed=rounds_executed,
            total_searches=total_searches,
            total_fetches=total_fetches,
            tokens_in=total_tokens_in,
            tokens_out=total_tokens_out,
            cost=total_cost,
            latency_ms=latency_ms,
            saturated=saturated,
        )

        await self._event_bus.publish("research.complete", {
            "topic": topic,
            "rounds": rounds_executed,
            "findings": len(all_findings),
            "sources": len(sources),
            "saturated": saturated,
            "latency_ms": latency_ms,
            "cost": total_cost,
        })

        logger.info(
            "research.complete",
            topic=topic,
            rounds=rounds_executed,
            findings=len(all_findings),
            sources=len(sources),
            latency_ms=latency_ms,
        )

        return report

    # ------------------------------------------------------------------
    # LLM-assisted steps
    # ------------------------------------------------------------------

    async def _plan_angles(
        self, topic: str, count: int,
    ) -> tuple[list[str], dict[str, Any]]:
        """Use LLM to generate diverse search angles for the topic."""
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a research planner. Given a topic, generate "
                    f"{count} diverse search queries that explore different "
                    "aspects of the topic. Return ONLY a JSON array of strings, "
                    "no explanation."
                ),
            },
            {
                "role": "user",
                "content": f"Topic: {topic}",
            },
        ]

        response = await self._gateway.chat(messages=messages)
        angles = self._parse_json_list(response.text, fallback_topic=topic)
        usage = {
            "tokens_in": response.usage.tokens_in,
            "tokens_out": response.usage.tokens_out,
            "cost": response.usage.cost,
        }
        return angles, usage

    async def _extract_findings(
        self,
        topic: str,
        round_num: int,
        search_results: list[tuple[str, SearchResult]],
        fetched: list[tuple[str, SearchResult, str]],
        existing_findings: list[Finding],
    ) -> tuple[list[Finding], dict[str, Any]]:
        """Use LLM to extract novel findings from search results."""
        # Build context of what we already know
        existing_summary = ""
        if existing_findings:
            existing_points = [f"- {f.content[:150]}" for f in existing_findings[:20]]
            existing_summary = (
                "Already known findings (avoid duplicates):\n"
                + "\n".join(existing_points)
            )

        # Build source material
        source_parts: list[str] = []
        for query, sr, content in fetched:
            source_parts.append(
                f"## Source: {sr.title}\n"
                f"URL: {sr.url}\n"
                f"Query: {query}\n"
                f"Content:\n{content[:3000]}\n"
            )

        # Add snippet-only results
        for query, sr in search_results:
            if not any(sr.url == f[1].url for f in fetched):
                source_parts.append(
                    f"## Source: {sr.title}\n"
                    f"URL: {sr.url}\n"
                    f"Query: {query}\n"
                    f"Snippet: {sr.snippet}\n"
                )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a research analyst. Extract key findings from "
                    "the provided sources about the given topic. "
                    "Only extract NEW information not already known. "
                    "Return a JSON array of objects with keys: "
                    '"content" (the finding), "source_url", "source_title".\n'
                    "Return ONLY the JSON array, no explanation."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Research topic: {topic}\n\n"
                    f"{existing_summary}\n\n"
                    "Sources:\n" + "\n".join(source_parts)
                ),
            },
        ]

        response = await self._gateway.chat(messages=messages)
        usage = {
            "tokens_in": response.usage.tokens_in,
            "tokens_out": response.usage.tokens_out,
            "cost": response.usage.cost,
        }

        findings = self._parse_findings(response.text, round_num)
        return findings, usage

    async def _synthesise(
        self, topic: str, findings: list[Finding],
    ) -> tuple[str, dict[str, Any]]:
        """Use LLM to cross-validate findings and produce a structured report."""
        if not findings:
            return "No findings to synthesise.", {"tokens_in": 0, "tokens_out": 0, "cost": 0.0}

        # Group findings by source for cross-validation
        findings_text = "\n".join(
            f"- [{f.source_title}] {f.content}" for f in findings
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a research synthesiser. Given a set of findings "
                    "from multiple sources, write a comprehensive, well-structured "
                    "report. Cross-validate facts that appear in multiple sources. "
                    "Flag any contradictions. Use markdown formatting with headers "
                    "and bullet points. Include a brief executive summary at the top."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"# Research Topic: {topic}\n\n"
                    f"## Collected Findings ({len(findings)} items):\n\n"
                    f"{findings_text}"
                ),
            },
        ]

        response = await self._gateway.chat(messages=messages)
        usage = {
            "tokens_in": response.usage.tokens_in,
            "tokens_out": response.usage.tokens_out,
            "cost": response.usage.cost,
        }
        return response.text, usage

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pick_round_angles(angles: list[str], round_num: int) -> list[str]:
        """Pick 2-3 angles per round, cycling through the list."""
        per_round = 2
        start = (round_num - 1) * per_round
        if start >= len(angles):
            return []
        return angles[start:start + per_round]

    @staticmethod
    def _parse_json_list(text: str, *, fallback_topic: str = "") -> list[str]:
        """Parse a JSON array of strings from LLM output."""
        import json

        # Strip markdown code fences if present
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            cleaned = "\n".join(lines)

        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, list):
                return [str(item) for item in parsed if item]
        except json.JSONDecodeError:
            pass

        # Fallback: split by newlines and clean
        lines = [
            ln.strip().lstrip("0123456789.-) ").strip('"')
            for ln in text.strip().split("\n")
            if ln.strip() and not ln.strip().startswith("```")
        ]
        return lines if lines else [fallback_topic]

    @staticmethod
    def _parse_findings(text: str, round_num: int) -> list[Finding]:
        """Parse LLM findings JSON into Finding objects."""
        import json

        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            cleaned = "\n".join(lines)

        try:
            parsed = json.loads(cleaned)
            if not isinstance(parsed, list):
                parsed = [parsed]
        except json.JSONDecodeError:
            logger.warning("research.findings_parse_failed", text_preview=text[:200])
            return []

        findings: list[Finding] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            content = item.get("content", "")
            if not content:
                continue
            findings.append(Finding(
                content=content,
                source_url=item.get("source_url", ""),
                source_title=item.get("source_title", ""),
                query="",
                round=round_num,
            ))
        return findings


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _deduplicate_sources(findings: list[Finding]) -> list[dict[str, str]]:
    """Build a deduplicated list of sources from findings."""
    seen: set[str] = set()
    sources: list[dict[str, str]] = []
    for f in findings:
        if f.source_url and f.source_url not in seen:
            seen.add(f.source_url)
            sources.append({
                "url": f.source_url,
                "title": f.source_title,
            })
    return sources
