"""Tool-call execution helpers for the streamed Agent runtime."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from src.core.logging import get_logger
from src.infrastructure.model_gateway import StreamChunk

from .tool_executor import execute_tool_call, summarize_tool_result
from .tool_output_store import offload_tool_output_if_needed

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
    tool_result = await _run_tool_call(
        agent,
        tool_call,
        conversation_id,
        platform,
        task_state,
        _timeout_override(task_timeout, task_start),
    )
    tool_latency = int((time.monotonic() - tool_start) * 1000)
    _record_tool_context(
        agent,
        conversation_id=conversation_id,
        tool_call=tool_call,
        tool_result=tool_result,
    )
    messages.append(tool_result.to_message(tool_call.id))
    await _publish_tool_event(
        agent,
        conversation_id,
        tool_call.name,
        tool_result.is_error,
        iterations,
    )
    _log_tool_call(tool_call.name, tool_result, tool_latency)
    return _execution_record(tool_call, tool_result, tool_latency)


async def _run_tool_call(
    agent: Any,
    tool_call: Any,
    conversation_id: str,
    platform: str,
    task_state: Any,
    timeout_override: float | None,
) -> Any:
    tool_result = await execute_tool_call(
        agent,
        tool_call.name,
        tool_call.arguments,
        conversation_id=conversation_id,
        platform=platform,
        task_state=task_state,
        timeout_override=timeout_override,
    )
    return offload_tool_output_if_needed(
        tool_result,
        tool_name=tool_call.name,
        tool_call_id=tool_call.id,
    )


def _execution_record(tool_call: Any, tool_result: Any, tool_latency: int) -> dict[str, Any]:
    return {
        "name": tool_call.name,
        "arguments": tool_call.arguments,
        "result_preview": tool_result.content[:200],
        "is_error": tool_result.is_error,
        "metadata": dict(tool_result.metadata),
        "effects": [effect.to_dict() for effect in tool_result.effects],
        "tool_latency": tool_latency,
    }


async def _publish_tool_event(
    agent: Any,
    conversation_id: str,
    tool_name: str,
    is_error: bool,
    iterations: int,
) -> None:
    await agent.event_bus.publish(
        "agent.tool.executed",
        {
            "conversation_id": conversation_id,
            "tool": tool_name,
            "is_error": is_error,
            "iteration": iterations,
        },
    )


def _log_tool_call(tool_name: str, tool_result: Any, tool_latency: int) -> None:
    logger.info(
        "tool_called",
        surface="operational",
        tool=tool_name,
        status="error" if tool_result.is_error else "success",
        latency_ms=tool_latency,
        result_length=len(tool_result.content),
        effects=_effect_log_records(tool_result),
    )


def _effect_log_records(tool_result: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for effect in tool_result.effects:
        record = {
            "action": effect.action,
            "effect": effect.effect,
            "status": effect.status,
        }
        if effect.resource is not None:
            record["resource"] = effect.resource.to_dict()
        elif effect.target:
            record["target"] = effect.target
        records.append(record)
    return records


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
    activated_tools = _activated_tools(tool_result)
    if not agent.conversation_manager:
        return
    agent.conversation_manager.record_tool_event(
        conversation_id,
        tool_call.name,
        summarize_tool_result(tool_result.content),
        is_error=tool_result.is_error,
        activated_tools=activated_tools,
    )
    skill_name = _loaded_skill_name(tool_result)
    if isinstance(skill_name, str) and skill_name:
        agent.conversation_manager.protect_context(
            conversation_id,
            f"skill:{skill_name}",
            tool_result.content[:4000],
        )


def _activated_tools(tool_result: Any) -> list[str] | None:
    activated = tool_result.metadata.get("activated_tools") or []
    if isinstance(activated, list):
        return [str(item) for item in activated]
    for effect in tool_result.effects:
        value = effect.details.get("activated_tools")
        if isinstance(value, tuple | list):
            return [str(item) for item in value]
    return None


def _loaded_skill_name(tool_result: Any) -> str:
    skill_name = tool_result.metadata.get("skill_name")
    if isinstance(skill_name, str):
        return skill_name
    for effect in tool_result.effects:
        if effect.action == "skill.load" and effect.effect == "skill_loaded":
            return str(effect.target)
    return ""
