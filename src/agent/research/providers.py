"""Provider backends for the deep research engine."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.core.logging import get_logger

from .models import SearchResult

logger = get_logger(__name__)


@runtime_checkable
class ResearchProvider(Protocol):
    """Pluggable backend for search and content extraction."""

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Execute a web search and return results."""
        ...

    async def fetch(self, url: str, max_length: int = 8000) -> str:
        """Fetch and extract text content from a URL."""
        ...


class TavilyResearchProvider:
    """ResearchProvider backed by WebSearchTool and WebFetchTool."""

    def __init__(self) -> None:
        from src.tools.builtin.web_fetch import WebFetchTool
        from src.tools.builtin.web_search import WebSearchTool

        self._search_tool = WebSearchTool()
        self._fetch_tool = WebFetchTool()

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        result = await self._search_tool.execute(
            {
                "query": query,
                "max_results": max_results,
            },
        )
        if result.is_error:
            logger.warning("research.search_error", query=query, error=result.content)
            return []
        return self._parse_search_results(result.content)

    async def fetch(self, url: str, max_length: int = 8000) -> str:
        result = await self._fetch_tool.execute(
            {
                "url": url,
                "max_length": max_length,
            },
        )
        if result.is_error:
            logger.warning("research.fetch_error", url=url, error=result.content)
            return ""
        return result.content

    @staticmethod
    def _parse_search_results(raw: str) -> list[SearchResult]:
        """Parse WebSearchTool output back to structured data."""
        results: list[SearchResult] = []
        current_title = ""
        current_url = ""
        current_snippet = ""

        for line in raw.split("\n"):
            line = line.strip()
            if not line:
                continue
            if line[0].isdigit() and ". [" in line:
                if current_url:
                    results.append(
                        SearchResult(
                            title=current_title,
                            url=current_url,
                            snippet=current_snippet.strip(),
                        )
                    )
                current_title, current_url, current_snippet = _parse_result_header(line)
                continue
            if line.startswith("Summary:"):
                continue
            current_snippet += " " + line

        if current_url:
            results.append(
                SearchResult(
                    title=current_title,
                    url=current_url,
                    snippet=current_snippet.strip(),
                )
            )
        return results


def _parse_result_header(line: str) -> tuple[str, str, str]:
    try:
        bracket_start = line.index("[") + 1
        bracket_end = line.index("](")
        paren_end = line.index(")", bracket_end + 2)
    except ValueError:
        return line, "", ""
    return (
        line[bracket_start:bracket_end],
        line[bracket_end + 2 : paren_end],
        "",
    )
