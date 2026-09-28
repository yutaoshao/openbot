"""Helpers for one model round inside the ReAct event loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.infrastructure.model_gateway import ModelGateway, Usage
    from src.infrastructure.model_routing import RouteDecision
    from src.infrastructure.model_types import ToolCall


@dataclass(frozen=True)
class ModelRoundResult:
    """Collected output of one model round."""

    accumulated_text: str
    reasoning_content: str
    collected_tool_calls: list[ToolCall]
    usage: Usage | None
    model: str


async def model_round_events(
    gateway: ModelGateway,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    route_decision: RouteDecision | None = None,
):
    """Yield visible text chunks, then a final ``ModelRoundResult`` event."""
    accumulated_text = ""
    reasoning_content = ""
    collected_tool_calls: list[ToolCall] = []
    iter_usage: Usage | None = None
    final_model = ""

    async for chunk in gateway.model_round_chunks(
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
            reasoning_content = chunk.reasoning_content

    yield ModelRoundResult(
        accumulated_text=accumulated_text,
        reasoning_content=reasoning_content,
        collected_tool_calls=collected_tool_calls,
        usage=iter_usage,
        model=final_model,
    )


def _route_kwargs(route_decision: RouteDecision | None) -> dict[str, str]:
    if route_decision is None:
        return {}
    return {
        "route_tier": route_decision.tier,
        "route_reason": route_decision.reason,
    }
