"""Web page fetch and extraction tool."""

from __future__ import annotations

from typing import Any

import httpx
import trafilatura

from src.tools.registry import ToolResult


class WebFetchTool:
    """Fetch a web page and extract its main content."""

    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return (
            "Fetch a web page and extract its main text content. "
            "Useful for reading articles, documentation, and other web pages."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch",
                },
                "max_length": {
                    "type": "integer",
                    "description": "Maximum content length in characters (default: 5000)",
                    "default": 5000,
                },
            },
            "required": ["url"],
        }

    @property
    def category(self) -> str:
        return "information"

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        url = args.get("url", "")
        max_length = args.get("max_length", 5000)

        if not url:
            return ToolResult(content="URL is required", is_error=True)

        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                response = await client.get(
                    url,
                    headers={"User-Agent": "OpenBot/1.0 (Web Fetcher)"},
                )
                response.raise_for_status()
                html = response.text

            # Extract main content using trafilatura
            extracted = trafilatura.extract(
                html,
                include_links=True,
                include_formatting=True,
                favor_precision=True,
            )

            if not extracted:
                return ToolResult(
                    content="Could not extract meaningful content from the page.",
                    metadata={"url": url},
                )

            # Truncate if needed
            content = extracted[:max_length]
            if len(extracted) > max_length:
                content += (
                    f"\n\n[Truncated: {len(extracted)} total chars, showing first {max_length}]"
                )

            return ToolResult(
                content=content,
                metadata={"url": url, "length": len(extracted)},
            )

        except httpx.HTTPStatusError as e:
            return ToolResult(content=f"HTTP error: {e.response.status_code}", is_error=True)
        except httpx.RequestError as e:
            return ToolResult(content=f"Request failed: {e}", is_error=True)
        except Exception as e:
            return ToolResult(content=f"Fetch failed: {e}", is_error=True)
