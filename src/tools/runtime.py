"""Runtime context helpers for tool execution."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


@dataclass(frozen=True)
class ToolExecutionContext:
    """Per-call context exposed to tools during execution."""

    conversation_id: str = ""
    platform: str = "unknown"

    @property
    def target_id(self) -> str:
        """Default response target for follow-up work."""
        return self.conversation_id


_TOOL_CONTEXT: ContextVar[ToolExecutionContext | None] = ContextVar(
    "tool_execution_context",
    default=None,
)


@contextmanager
def tool_execution_context(context: ToolExecutionContext) -> Iterator[None]:
    """Temporarily bind runtime context for a tool call."""
    token = _TOOL_CONTEXT.set(context)
    try:
        yield
    finally:
        _TOOL_CONTEXT.reset(token)


def get_tool_execution_context() -> ToolExecutionContext | None:
    """Return the current tool execution context if one is active."""
    return _TOOL_CONTEXT.get()
