"""Tests for the deep research engine."""

from __future__ import annotations

import pytest

from src.agent.deep_research import (
    DeepResearch,
    Finding,
    ResearchReport,
    SearchResult,
    TavilyResearchProvider,
    _deduplicate_sources,
)


# ---------------------------------------------------------------------------
# TavilyResearchProvider._parse_search_results
# ---------------------------------------------------------------------------

class TestParseSearchResults:
    def test_basic_parsing(self) -> None:
        raw = (
            "Summary: Some summary\n\n"
            "1. [First Title](https://example.com/1)\n"
            "   First snippet text here\n\n"
            "2. [Second Title](https://example.com/2)\n"
            "   Second snippet\n"
        )
        results = TavilyResearchProvider._parse_search_results(raw)
        assert len(results) == 2
        assert results[0].title == "First Title"
        assert results[0].url == "https://example.com/1"
        assert "First snippet" in results[0].snippet
        assert results[1].title == "Second Title"
        assert results[1].url == "https://example.com/2"

    def test_empty_input(self) -> None:
        results = TavilyResearchProvider._parse_search_results("")
        assert results == []

    def test_summary_only(self) -> None:
        results = TavilyResearchProvider._parse_search_results("Summary: Just a summary")
        assert results == []


# ---------------------------------------------------------------------------
# DeepResearch._parse_json_list
# ---------------------------------------------------------------------------

class TestParseJsonList:
    def test_valid_json_array(self) -> None:
        text = '["query 1", "query 2", "query 3"]'
        result = DeepResearch._parse_json_list(text)
        assert result == ["query 1", "query 2", "query 3"]

    def test_json_in_code_fence(self) -> None:
        text = '```json\n["a", "b"]\n```'
        result = DeepResearch._parse_json_list(text)
        assert result == ["a", "b"]

    def test_fallback_to_lines(self) -> None:
        text = "1. First query\n2. Second query\n3. Third query"
        result = DeepResearch._parse_json_list(text)
        assert len(result) == 3
        assert "First query" in result[0]

    def test_fallback_topic(self) -> None:
        result = DeepResearch._parse_json_list("", fallback_topic="test topic")
        assert result == ["test topic"]


# ---------------------------------------------------------------------------
# DeepResearch._parse_findings
# ---------------------------------------------------------------------------

class TestParseFindings:
    def test_valid_findings(self) -> None:
        text = '''[
            {"content": "Finding 1", "source_url": "https://a.com", "source_title": "A"},
            {"content": "Finding 2", "source_url": "https://b.com", "source_title": "B"}
        ]'''
        findings = DeepResearch._parse_findings(text, round_num=1)
        assert len(findings) == 2
        assert findings[0].content == "Finding 1"
        assert findings[0].round == 1
        assert findings[1].source_url == "https://b.com"

    def test_code_fenced_findings(self) -> None:
        text = '```json\n[{"content": "Test", "source_url": "", "source_title": ""}]\n```'
        findings = DeepResearch._parse_findings(text, round_num=2)
        assert len(findings) == 1
        assert findings[0].content == "Test"
        assert findings[0].round == 2

    def test_invalid_json(self) -> None:
        findings = DeepResearch._parse_findings("not json at all", round_num=1)
        assert findings == []

    def test_empty_content_skipped(self) -> None:
        text = '[{"content": "", "source_url": "x"}]'
        findings = DeepResearch._parse_findings(text, round_num=1)
        assert findings == []


# ---------------------------------------------------------------------------
# DeepResearch._pick_round_angles
# ---------------------------------------------------------------------------

class TestPickRoundAngles:
    def test_first_round(self) -> None:
        angles = ["a", "b", "c", "d", "e", "f"]
        result = DeepResearch._pick_round_angles(angles, 1)
        assert result == ["a", "b"]

    def test_second_round(self) -> None:
        angles = ["a", "b", "c", "d"]
        result = DeepResearch._pick_round_angles(angles, 2)
        assert result == ["c", "d"]

    def test_exhausted(self) -> None:
        angles = ["a", "b"]
        result = DeepResearch._pick_round_angles(angles, 2)
        assert result == []


# ---------------------------------------------------------------------------
# _deduplicate_sources
# ---------------------------------------------------------------------------

class TestDeduplicateSources:
    def test_basic(self) -> None:
        findings = [
            Finding(content="a", source_url="https://a.com", source_title="A", query="", round=1),
            Finding(content="b", source_url="https://a.com", source_title="A", query="", round=1),
            Finding(content="c", source_url="https://b.com", source_title="B", query="", round=2),
        ]
        sources = _deduplicate_sources(findings)
        assert len(sources) == 2
        assert sources[0]["url"] == "https://a.com"
        assert sources[1]["url"] == "https://b.com"

    def test_empty(self) -> None:
        assert _deduplicate_sources([]) == []


# ---------------------------------------------------------------------------
# ResearchReport
# ---------------------------------------------------------------------------

class TestResearchReport:
    def test_defaults(self) -> None:
        report = ResearchReport(topic="test", synthesis="summary")
        assert report.topic == "test"
        assert report.findings == []
        assert report.rounds_executed == 0
        assert report.saturated is False
