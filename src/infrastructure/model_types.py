"""Shared model gateway value objects and protocols."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@dataclass
class ToolCall:
    """A tool call requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Usage:
    """Token usage metadata for a single request."""

    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    cached_tokens: int | None = None

    @property
    def cache_hit_ratio(self) -> float | None:
        if self.cached_tokens is None or self.tokens_in <= 0:
            return None
        return round(self.cached_tokens / self.tokens_in, 4)


@dataclass
class ModelResponse:
    """Unified response from any model provider."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    latency_ms: int = 0

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

    def to_assistant_message(self) -> dict[str, Any]:
        """Convert to message dict for conversation context."""
        msg: dict[str, Any] = {"role": "assistant"}
        if self.text:
            msg["content"] = self.text
        if self.tool_calls:
            msg["tool_calls"] = [_render_tool_call(tc) for tc in self.tool_calls]
        return msg


@dataclass
class StreamChunk:
    """A single chunk from a streaming model response."""

    type: Literal["text", "tool_call", "tool_status", "done"]
    text: str = ""
    tool_call: ToolCall | None = None
    tool_name: str = ""
    usage: Usage | None = None
    model: str = ""
    iterations: int = 0


@runtime_checkable
class ModelProvider(Protocol):
    """Protocol for model provider implementations."""

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse: ...

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]: ...


def _render_tool_call(tool_call: ToolCall) -> dict[str, Any]:
    return {
        "id": tool_call.id,
        "type": "function",
        "function": {
            "name": tool_call.name,
            "arguments": json.dumps(tool_call.arguments, ensure_ascii=False),
        },
    }
