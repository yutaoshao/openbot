"""Web search tool using Tavily API."""

from __future__ import annotations

import os
from typing import Any

import httpx

from src.tools.registry import ToolResult


class WebSearchTool:
    """Search the web using Tavily API."""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web for current information. "
            "Returns relevant results with titles, URLs, and snippets."
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
            return ToolResult(content="TAVILY_API_KEY not configured", is_error=True)

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
                metadata={"query": query, "result_count": len(data.get("results", []))},
            )

        except httpx.HTTPStatusError as e:
            return ToolResult(content=f"Search API error: {e.response.status_code}", is_error=True)
        except Exception as e:
            return ToolResult(content=f"Search failed: {e}", is_error=True)
