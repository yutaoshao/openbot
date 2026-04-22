"""Tool-call execution helpers for the streamed Agent runtime."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from src.core.logging import get_logger
from src.infrastructure.model_gateway import StreamChunk

from .tool_executor import execute_tool_call, summarize_tool_result

logger = get_logger(__name__)


@dataclass(frozen=True)
class ToolExecutionBatch:
    """Collected tool-call execution records for one model round."""

    executed_calls: list[dict[str, Any]]


async def execute_tool_calls_for_round(
    agent: Any,
    *,
    collected_tool_calls: list[Any],
    conversation_id: str,
    platform: str,
    task_state: Any,
    task_start: float,
    task_timeout: int,
    iterations: int,
    messages: list[dict[str, Any]],
):
    """Yield tool-status chunks, then a final ``ToolExecutionBatch`` event."""
    executed_calls: list[dict[str, Any]] = []
    for tool_call in collected_tool_calls:
        yield StreamChunk(type="tool_status", tool_name=tool_call.name)
        executed_call = await _execute_tool_call(
            agent,
            tool_call=tool_call,
            conversation_id=conversation_id,
            platform=platform,
            task_state=task_state,
            task_start=task_start,
            task_timeout=task_timeout,
            iterations=iterations,
            messages=messages,
        )
        executed_calls.append(executed_call)
    yield ToolExecutionBatch(executed_calls=executed_calls)


async def _execute_tool_call(
    agent: Any,
    *,
    tool_call: Any,
    conversation_id: str,
    platform: str,
    task_state: Any,
    task_start: float,
    task_timeout: int,
    iterations: int,
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    tool_start = time.monotonic()
    tool_result = await execute_tool_call(
        agent,
        tool_call.name,
        tool_call.arguments,
        conversation_id=conversation_id,
        platform=platform,
        task_state=task_state,
        timeout_override=_timeout_override(task_timeout, task_start),
    )
    tool_latency = int((time.monotonic() - tool_start) * 1000)
    _record_tool_context(
        agent,
        conversation_id=conversation_id,
        tool_call=tool_call,
        tool_result=tool_result,
    )
    messages.append(tool_result.to_message(tool_call.id))
    await agent.event_bus.publish(
        "agent.tool.executed",
        {
            "conversation_id": conversation_id,
            "tool": tool_call.name,
            "is_error": tool_result.is_error,
            "iteration": iterations,
        },
    )
    logger.info(
        "tool_called",
        surface="operational",
        tool=tool_call.name,
        status="error" if tool_result.is_error else "success",
        latency_ms=tool_latency,
        result_length=len(tool_result.content),
    )
    return {
        "name": tool_call.name,
        "arguments": tool_call.arguments,
        "result_preview": tool_result.content[:200],
        "is_error": tool_result.is_error,
        "tool_latency": tool_latency,
    }


def _timeout_override(task_timeout: int, task_start: float) -> float | None:
    if task_timeout <= 0:
        return None
    return max(0.001, task_timeout - (time.monotonic() - task_start))


def _record_tool_context(
    agent: Any,
    *,
    conversation_id: str,
    tool_call: Any,
    tool_result: Any,
) -> None:
    activated_tools = tool_result.metadata.get("activated_tools") or []
    if not agent.conversation_manager:
        return
    agent.conversation_manager.record_tool_event(
        conversation_id,
        tool_call.name,
        summarize_tool_result(tool_result.content),
        is_error=tool_result.is_error,
        activated_tools=activated_tools if isinstance(activated_tools, list) else None,
    )
    skill_name = tool_result.metadata.get("skill_name")
    if isinstance(skill_name, str) and skill_name:
        agent.conversation_manager.protect_context(
            conversation_id,
            f"skill:{skill_name}",
            tool_result.content[:4000],
        )
