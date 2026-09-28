"""Web page fetch and extraction tool."""

from __future__ import annotations

from typing import Any

import httpx
import trafilatura
from pydantic import Field

from src.tools.builtin.validation import StrictToolInput, schema_for, validate_args
from src.tools.effects import EFFECT_NONE, STATUS_COMPLETED, STATUS_ERROR, tool_effect
from src.tools.registry import ToolResult


class WebFetchInput(StrictToolInput):
    url: str = Field(description="The URL to fetch")


class WebFetchTool:
    """Fetch a web page and extract its main content."""

    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return (
            "Fetches one web page and extracts its main readable text content. "
            "Use when the user provides a URL, or a previous search result needs to be "
            "read, summarized, cited, or checked in detail. "
            "Do not use when you still need to discover sources, compare many pages, "
            "or read local workspace files."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return schema_for(WebFetchInput)

    @property
    def category(self) -> str:
        return "information"

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        if args.get("url", "") == "":
            return _result("URL is required", True, "", STATUS_ERROR, EFFECT_NONE)
        data, error = validate_args(WebFetchInput, args, tool_name=self.name)
        if error:
            return error
        url = data.url

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
                    effects=(_effect(url, STATUS_COMPLETED, "page_fetched"),),
                )

            return ToolResult(
                content=extracted,
                metadata={"length": len(extracted)},
                effects=(_effect(url, STATUS_COMPLETED, "page_fetched"),),
            )

        except httpx.HTTPStatusError as e:
            return _result(
                f"HTTP error: {e.response.status_code}",
                True,
                url,
                STATUS_ERROR,
                EFFECT_NONE,
            )
        except httpx.RequestError as e:
            return _result(f"Request failed: {e}", True, url, STATUS_ERROR, EFFECT_NONE)
        except Exception as e:
            return _result(f"Fetch failed: {e}", True, url, STATUS_ERROR, EFFECT_NONE)


def _result(content: str, is_error: bool, url: str, status: str, effect: str) -> ToolResult:
    return ToolResult(content=content, is_error=is_error, effects=(_effect(url, status, effect),))


def _effect(url: str, status: str, effect: str):
    return tool_effect(
        "web.fetch",
        effect,
        status=status,
        target_type="url",
        target=url,
        name="web_fetch",
    )
