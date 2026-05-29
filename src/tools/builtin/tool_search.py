"""Deferred tool discovery tool."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.tools.effects import EFFECT_NONE, STATUS_COMPLETED, STATUS_ERROR, tool_effect
from src.tools.registry import ToolResult

if TYPE_CHECKING:
    from src.tools.registry import ToolRegistry


class ToolSearchTool:
    """Expose deferred tools only when the current task needs them."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    @property
    def name(self) -> str:
        return "tool_search"

    @property
    def description(self) -> str:
        return (
            "Searches deferred tools that are registered but not currently visible. "
            "Use when the task may need a capability outside the visible tool list, or "
            "the user mentions a workflow/tool category that is not available yet. "
            "Do not use when the currently visible tools already satisfy the task, or "
            "there is no concrete capability to search for."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Short description of the capability or system you need",
                },
            },
            "required": ["query"],
        }

    @property
    def category(self) -> str:
        return "system"

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        query = str(args.get("query") or "").strip()
        if not query:
            return _result("query is required", True, query, STATUS_ERROR, EFFECT_NONE)
        matches = self._registry.search_deferred(query)
        if not matches:
            return _result(
                "No deferred tools matched the query.",
                False,
                query,
                STATUS_COMPLETED,
                "tools_discovered",
            )
        lines = ["Deferred tools that match the query:"]
        activate_tools: list[str] = []
        for match in matches:
            activate_tools.append(match["name"])
            lines.append(f"- {match['name']} ({match['category']}): {match['description']}")
        return ToolResult(
            content="\n".join(lines),
            effects=(
                _effect(
                    query,
                    STATUS_COMPLETED,
                    "tools_discovered",
                    activated_tools=tuple(activate_tools),
                ),
            ),
        )


def _result(content: str, is_error: bool, query: str, status: str, effect: str) -> ToolResult:
    return ToolResult(content=content, is_error=is_error, effects=(_effect(query, status, effect),))


def _effect(query: str, status: str, effect: str, **details: Any):
    return tool_effect(
        "tool.search",
        effect,
        status=status,
        target_type="query",
        target=query,
        name="tool_search",
        **details,
    )
