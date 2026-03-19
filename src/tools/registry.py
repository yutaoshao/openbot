"""Tool protocol and registry.

Defines the unified interface for all tools and the central registry
that manages tool discovery and schema generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from src.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ToolResult:
    """Result from a tool execution."""

    content: str
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_message(self, tool_call_id: str) -> dict[str, Any]:
        """Convert to tool result message for model context."""
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": self.content,
        }


@runtime_checkable
class Tool(Protocol):
    """Protocol that all tools must implement."""

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        ...

    @property
    def category(self) -> str: ...

    async def execute(self, args: dict[str, Any]) -> ToolResult: ...


class ToolRegistry:
    """Central registry for tool management."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._enabled: dict[str, bool] = {}       # tool_name -> enabled flag
        self._config: dict[str, dict] = {}         # tool_name -> extra config
        self._last_used: dict[str, str | None] = {}  # tool_name -> ISO timestamp

    def register(self, tool: Tool, *, enabled: bool = True) -> None:
        """Register a tool."""
        if tool.name in self._tools:
            logger.warning("tool_registry.duplicate", name=tool.name)
        self._tools[tool.name] = tool
        self._enabled.setdefault(tool.name, enabled)
        self._config.setdefault(tool.name, {})
        self._last_used.setdefault(tool.name, None)
        logger.info("tool_registry.registered", name=tool.name, category=tool.category)

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_all(self) -> list[Tool]:
        """List all registered tools."""
        return list(self._tools.values())

    def list_by_category(self, category: str) -> list[Tool]:
        """List tools filtered by category."""
        return [t for t in self._tools.values() if t.category == category]

    def get_schemas(self) -> list[dict[str, Any]]:
        """Get all tool schemas in model-agnostic format.

        Returns a list of dicts with name, description, parameters.
        Provider adapters convert this to their specific format.
        Only includes enabled tools.
        """
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in self._tools.values()
            if self._enabled.get(tool.name, True)
        ]

    # ------------------------------------------------------------------
    # Management API (used by REST routes)
    # ------------------------------------------------------------------

    def list_status(self) -> list[dict[str, Any]]:
        """Return status info for all registered tools."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "category": tool.category,
                "enabled": self._enabled.get(tool.name, True),
                "config": self._config.get(tool.name, {}),
                "last_used": self._last_used.get(tool.name),
            }
            for tool in self._tools.values()
        ]

    def update_config(
        self, name: str, updates: dict[str, Any],
    ) -> dict[str, Any]:
        """Update a tool's configuration. Raises KeyError if not found."""
        tool = self._tools.get(name)
        if not tool:
            raise KeyError(name)

        if "enabled" in updates:
            self._enabled[name] = bool(updates.pop("enabled"))
        if updates:
            self._config.setdefault(name, {}).update(updates)

        logger.info("tool_registry.config_updated", name=name)
        return {
            "name": tool.name,
            "description": tool.description,
            "category": tool.category,
            "enabled": self._enabled.get(name, True),
            "config": self._config.get(name, {}),
            "last_used": self._last_used.get(name),
        }

    def record_usage(self, name: str) -> None:
        """Record that a tool was used (updates last_used timestamp)."""
        if name in self._tools:
            self._last_used[name] = datetime.now(UTC).isoformat()
