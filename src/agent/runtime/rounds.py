"""Helpers for one streamed model round inside the ReAct loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.infrastructure.model_gateway import Usage


@dataclass(frozen=True)
class ModelRoundResult:
    """Collected output of one streamed model round."""

    accumulated_text: str
    collected_tool_calls: list[Any]
    usage: Usage | None
    model: str


async def stream_model_round(
    agent: Any,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    route_decision: Any = None,
):
    """Yield streamed text chunks, then a final ``ModelRoundResult`` event."""
    accumulated_text = ""
    collected_tool_calls: list[Any] = []
    iter_usage: Usage | None = None
    final_model = ""

    async for chunk in agent.model_gateway.chat_stream(
        messages=messages,
        tools=tools,
        **_route_kwargs(route_decision),
    ):
        if chunk.type == "text":
            accumulated_text += chunk.text
            yield chunk
            continue
        if chunk.type == "tool_call" and chunk.tool_call is not None:
            collected_tool_calls.append(chunk.tool_call)
            continue
        if chunk.type == "done":
            iter_usage = chunk.usage
            final_model = chunk.model

    yield ModelRoundResult(
        accumulated_text=accumulated_text,
        collected_tool_calls=collected_tool_calls,
        usage=iter_usage,
        model=final_model,
    )


def _route_kwargs(route_decision: Any) -> dict[str, str]:
    if route_decision is None:
        return {}
    return {
        "route_tier": route_decision.tier,
        "route_reason": route_decision.reason,
    }
