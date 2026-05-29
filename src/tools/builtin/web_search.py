"""Web search tool using Tavily API."""

from __future__ import annotations

import os
from typing import Any

import httpx

from src.tools.effects import EFFECT_NONE, STATUS_COMPLETED, STATUS_ERROR, tool_effect
from src.tools.registry import ToolResult


class WebSearchTool:
    """Search the web using Tavily API."""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Searches the web for current or external information and returns "
            "titles, URLs, snippets, and an optional summary. "
            "Use when you need recent facts, source discovery, news, or web references "
            "before deciding which pages to read. "
            "Do not use when the user already provided a specific URL to read, the answer "
            "should come from local files, or the task needs deep multi-round research."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        }

    @property
    def category(self) -> str:
        return "information"

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        query = args.get("query", "")
        max_results = args.get("max_results", 5)

        api_key = os.environ.get("TAVILY_API_KEY", "")
        if not api_key:
            return _result("TAVILY_API_KEY not configured", True, query, STATUS_ERROR, EFFECT_NONE)

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    "https://api.tavily.com/search",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "query": query,
                        "max_results": max_results,
                        "include_answer": True,
                    },
                )
                response.raise_for_status()
                data = response.json()

            # Format results
            parts = []
            if data.get("answer"):
                parts.append(f"Summary: {data['answer']}\n")

            for i, result in enumerate(data.get("results", []), 1):
                title = result.get("title", "")
                url = result.get("url", "")
                snippet = result.get("content", "")[:300]
                parts.append(f"{i}. [{title}]({url})\n   {snippet}")

            return ToolResult(
                content="\n\n".join(parts) if parts else "No results found.",
                metadata={"result_count": len(data.get("results", []))},
                effects=(_effect(query, STATUS_COMPLETED, "web_searched"),),
            )

        except httpx.HTTPStatusError as e:
            return _result(
                f"Search API error: {e.response.status_code}",
                True,
                query,
                STATUS_ERROR,
                EFFECT_NONE,
            )
        except Exception as e:
            return _result(f"Search failed: {e}", True, query, STATUS_ERROR, EFFECT_NONE)


def _result(content: str, is_error: bool, query: str, status: str, effect: str) -> ToolResult:
    return ToolResult(content=content, is_error=is_error, effects=(_effect(query, status, effect),))


def _effect(query: str, status: str, effect: str):
    return tool_effect(
        "web.search",
        effect,
        status=status,
        target_type="query",
        target=query,
        name="web_search",
    )
