"""Deferred tool discovery tool."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
            "Search deferred tools that are not always visible. "
            "Use when you suspect another tool may better fit the task."
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
            return ToolResult(content="query is required", is_error=True)
        matches = self._registry.search_deferred(query)
        if not matches:
            return ToolResult(content="No deferred tools matched the query.")
        lines = ["Deferred tools that match the query:"]
        activate_tools: list[str] = []
        for match in matches:
            activate_tools.append(match["name"])
            lines.append(f"- {match['name']} ({match['category']}): {match['description']}")
        return ToolResult(
            content="\n".join(lines),
            metadata={"activate_tools": activate_tools},
        )
