"""Pure helpers for the deep research engine."""

from __future__ import annotations

import json

from src.core.logging import get_logger

from .models import Finding

logger = get_logger(__name__)


def pick_round_angles(angles: list[str], round_num: int) -> list[str]:
    """Pick 2-3 angles per round, cycling through the list."""
    per_round = 2
    start = (round_num - 1) * per_round
    if start >= len(angles):
        return []
    return angles[start : start + per_round]


def parse_json_list(text: str, *, fallback_topic: str = "") -> list[str]:
    """Parse a JSON array of strings from LLM output."""
    cleaned = _strip_code_fences(text)
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return [str(item) for item in parsed if item]
    except json.JSONDecodeError:
        pass

    lines = [
        line.strip().lstrip("0123456789.-) ").strip('"')
        for line in text.strip().split("\n")
        if line.strip() and not line.strip().startswith("```")
    ]
    return lines if lines else [fallback_topic]


def parse_findings(text: str, round_num: int) -> list[Finding]:
    """Parse LLM findings JSON into ``Finding`` objects."""
    cleaned = _strip_code_fences(text)
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
        findings.append(
            Finding(
                content=content,
                source_url=item.get("source_url", ""),
                source_title=item.get("source_title", ""),
                query="",
                round=round_num,
            )
        )
    return findings


def deduplicate_sources(findings: list[Finding]) -> list[dict[str, str]]:
    """Build a deduplicated list of sources from findings."""
    seen: set[str] = set()
    sources: list[dict[str, str]] = []
    for finding in findings:
        if finding.source_url and finding.source_url not in seen:
            seen.add(finding.source_url)
            sources.append({"url": finding.source_url, "title": finding.source_title})
    return sources


def _strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if not cleaned.startswith("```"):
        return cleaned
    lines = cleaned.split("\n")
    lines = [line for line in lines if not line.strip().startswith("```")]
    return "\n".join(lines)
