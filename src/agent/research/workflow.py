"""Workflow orchestration for multi-round deep research."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from src.core.logging import get_logger

from .helpers import deduplicate_sources, parse_findings, parse_json_list, pick_round_angles
from .models import Finding, ResearchReport, SearchResult
from .providers import ResearchProvider, TavilyResearchProvider

if TYPE_CHECKING:
    from src.infrastructure.event_bus import EventBus
    from src.infrastructure.model_gateway import ModelGateway

logger = get_logger(__name__)

DEFAULT_MAX_ROUNDS = 5
DEFAULT_ANGLES_COUNT = 6
DEFAULT_SATURATION_THRESHOLD = 0.15
DEFAULT_MAX_SOURCES_PER_ROUND = 3


class DeepResearch:
    """Multi-round deep research engine."""

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
        counters = {
            "tokens_in": 0,
            "tokens_out": 0,
            "searches": 0,
            "fetches": 0,
        }
        start = time.monotonic()
        all_findings: list[Finding] = []
        seen_urls: set[str] = set()

        await self._event_bus.publish("research.start", {"topic": topic})
        angles = await self._plan_initial_angles(topic, angles_count, counters)
        rounds_executed, saturated = await self._run_rounds(
            topic=topic,
            angles=angles,
            max_rounds=max_rounds,
            saturation_threshold=saturation_threshold,
            max_sources_per_round=max_sources_per_round,
            counters=counters,
            all_findings=all_findings,
            seen_urls=seen_urls,
        )
        synthesis = await self._build_synthesis(topic, all_findings, counters)
        sources = deduplicate_sources(all_findings)
        latency_ms = int((time.monotonic() - start) * 1000)
        report = ResearchReport(
            topic=topic,
            synthesis=synthesis,
            findings=all_findings,
            sources=sources,
            search_angles=angles,
            rounds_executed=rounds_executed,
            total_searches=counters["searches"],
            total_fetches=counters["fetches"],
            tokens_in=counters["tokens_in"],
            tokens_out=counters["tokens_out"],
            latency_ms=latency_ms,
            saturated=saturated,
        )
        await self._publish_completion(
            topic, rounds_executed, all_findings, sources, saturated, latency_ms
        )
        return report

    async def _plan_initial_angles(
        self,
        topic: str,
        angles_count: int,
        counters: dict[str, int],
    ) -> list[str]:
        await self._event_bus.publish("research.plan", {"topic": topic, "angles": angles_count})
        angles, usage = await self._plan_angles(topic, angles_count)
        _add_usage(counters, usage)
        logger.info("research.angles_planned", topic=topic, angle_count=len(angles))
        return angles

    async def _run_rounds(
        self,
        *,
        topic: str,
        angles: list[str],
        max_rounds: int,
        saturation_threshold: float,
        max_sources_per_round: int,
        counters: dict[str, int],
        all_findings: list[Finding],
        seen_urls: set[str],
    ) -> tuple[int, bool]:
        rounds_executed = 0
        saturated = False
        for round_num in range(1, max_rounds + 1):
            rounds_executed = round_num
            round_angles = self._pick_round_angles(angles, round_num)
            if not round_angles:
                logger.info("research.no_more_angles", round=round_num)
                break
            round_results = await self._search_round(round_angles, counters, seen_urls)
            if not round_results:
                logger.info("research.no_new_results", round=round_num)
                saturated = True
                break
            fetched_contents = await self._fetch_round_sources(
                round_results,
                max_sources_per_round,
                counters,
            )
            new_findings, usage = await self._extract_findings(
                topic,
                round_num,
                round_results,
                fetched_contents,
                all_findings,
            )
            _add_usage(counters, usage)
            if _round_is_saturated(all_findings, new_findings, saturation_threshold):
                logger.info(
                    "research.saturated",
                    round=round_num,
                    novelty_ratio=f"{len(new_findings) / max(len(all_findings), 1):.2f}",
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
            await self._event_bus.publish(
                "research.round",
                {
                    "topic": topic,
                    "round": round_num,
                    "new_findings": len(new_findings),
                    "total_findings": len(all_findings),
                    "saturated": False,
                },
            )
        return rounds_executed, saturated

    async def _search_round(
        self,
        round_angles: list[str],
        counters: dict[str, int],
        seen_urls: set[str],
    ) -> list[tuple[str, SearchResult]]:
        round_results: list[tuple[str, SearchResult]] = []
        for angle in round_angles:
            results = await self._provider.search(angle)
            counters["searches"] += 1
            for result in results:
                if result.url not in seen_urls:
                    round_results.append((angle, result))
                    seen_urls.add(result.url)
        return round_results

    async def _fetch_round_sources(
        self,
        round_results: list[tuple[str, SearchResult]],
        max_sources_per_round: int,
        counters: dict[str, int],
    ) -> list[tuple[str, SearchResult, str]]:
        fetched_contents: list[tuple[str, SearchResult, str]] = []
        for query, result in round_results[:max_sources_per_round]:
            content = await self._provider.fetch(result.url)
            counters["fetches"] += 1
            if content:
                fetched_contents.append((query, result, content))
        return fetched_contents

    async def _build_synthesis(
        self,
        topic: str,
        all_findings: list[Finding],
        counters: dict[str, int],
    ) -> str:
        synthesis, usage = await self._synthesise(topic, all_findings)
        _add_usage(counters, usage)
        return synthesis

    async def _publish_completion(
        self,
        topic: str,
        rounds_executed: int,
        all_findings: list[Finding],
        sources: list[dict[str, str]],
        saturated: bool,
        latency_ms: int,
    ) -> None:
        await self._event_bus.publish(
            "research.complete",
            {
                "topic": topic,
                "rounds": rounds_executed,
                "findings": len(all_findings),
                "sources": len(sources),
                "saturated": saturated,
                "latency_ms": latency_ms,
            },
        )
        logger.info(
            "research.complete",
            topic=topic,
            rounds=rounds_executed,
            findings=len(all_findings),
            sources=len(sources),
            latency_ms=latency_ms,
        )

    async def _plan_angles(
        self,
        topic: str,
        count: int,
    ) -> tuple[list[str], dict[str, Any]]:
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
            {"role": "user", "content": f"Topic: {topic}"},
        ]
        response = await self._gateway.chat(messages=messages)
        return parse_json_list(response.text, fallback_topic=topic), _usage_dict(response)

    async def _extract_findings(
        self,
        topic: str,
        round_num: int,
        search_results: list[tuple[str, SearchResult]],
        fetched: list[tuple[str, SearchResult, str]],
        existing_findings: list[Finding],
    ) -> tuple[list[Finding], dict[str, Any]]:
        existing_summary = _existing_findings_summary(existing_findings)
        source_parts = _source_material(search_results, fetched)
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
        return parse_findings(response.text, round_num), _usage_dict(response)

    async def _synthesise(
        self,
        topic: str,
        findings: list[Finding],
    ) -> tuple[str, dict[str, Any]]:
        if not findings:
            return "No findings to synthesise.", {"tokens_in": 0, "tokens_out": 0}

        findings_text = "\n".join(
            f"- [{finding.source_title}] {finding.content}" for finding in findings
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
        return response.text, _usage_dict(response)

    @staticmethod
    def _pick_round_angles(angles: list[str], round_num: int) -> list[str]:
        return pick_round_angles(angles, round_num)

    @staticmethod
    def _parse_json_list(text: str, *, fallback_topic: str = "") -> list[str]:
        return parse_json_list(text, fallback_topic=fallback_topic)

    @staticmethod
    def _parse_findings(text: str, round_num: int) -> list[Finding]:
        return parse_findings(text, round_num)


def _usage_dict(response: Any) -> dict[str, Any]:
    return {
        "tokens_in": response.usage.tokens_in,
        "tokens_out": response.usage.tokens_out,
    }


def _add_usage(counters: dict[str, int], usage: dict[str, Any]) -> None:
    counters["tokens_in"] += int(usage.get("tokens_in", 0) or 0)
    counters["tokens_out"] += int(usage.get("tokens_out", 0) or 0)


def _round_is_saturated(
    all_findings: list[Finding],
    new_findings: list[Finding],
    saturation_threshold: float,
) -> bool:
    if not all_findings:
        return False
    novelty_ratio = len(new_findings) / max(len(all_findings), 1)
    return novelty_ratio < saturation_threshold


def _existing_findings_summary(existing_findings: list[Finding]) -> str:
    if not existing_findings:
        return ""
    existing_points = [f"- {finding.content[:150]}" for finding in existing_findings[:20]]
    return "Already known findings (avoid duplicates):\n" + "\n".join(existing_points)


def _source_material(
    search_results: list[tuple[str, SearchResult]],
    fetched: list[tuple[str, SearchResult, str]],
) -> list[str]:
    fetched_urls = {result.url for _, result, _ in fetched}
    source_parts = [
        (
            f"## Source: {result.title}\n"
            f"URL: {result.url}\n"
            f"Query: {query}\n"
            f"Content:\n{content[:3000]}\n"
        )
        for query, result, content in fetched
    ]
    source_parts.extend(
        (
            f"## Source: {result.title}\n"
            f"URL: {result.url}\n"
            f"Query: {query}\n"
            f"Snippet: {result.snippet}\n"
        )
        for query, result in search_results
        if result.url not in fetched_urls
    )
    return source_parts


def _deduplicate_sources(findings: list[Finding]) -> list[dict[str, str]]:
    return deduplicate_sources(findings)
