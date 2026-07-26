"""Pure helpers for the ReAct streaming loop."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.core.logging import get_logger
from src.infrastructure.model_gateway import StreamChunk, Usage

logger = get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class UsageTotals:
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


def reply_chunks(
    final_text: str,
    *,
    pending_final_text: str,
    pending_final_chunks: list[StreamChunk],
) -> list[StreamChunk]:
    if not final_text:
        return []
    if final_text == pending_final_text:
        return pending_final_chunks or [StreamChunk(type="text", text=final_text)]
    return [StreamChunk(type="text", text=final_text)]


def timeout_text(agent: Any, elapsed: float, iterations: int) -> str:
    task_timeout = agent.config.task_timeout
    if task_timeout <= 0:
        return ""
    if elapsed < task_timeout:
        return ""
    logger.warning(
        "task_failed",
        surface="operational",
        reason="task_timeout",
        elapsed_s=int(elapsed),
        iterations=iterations,
    )
    return f"Task exceeded time limit ({task_timeout}s). Completed {iterations} iterations."


def accumulate_usage(
    totals: UsageTotals,
    usage: Usage | None,
) -> UsageTotals:
    if usage is None:
        return totals
    return UsageTotals(
        tokens_in=totals.tokens_in + usage.tokens_in,
        tokens_out=totals.tokens_out + usage.tokens_out,
        cost_usd=totals.cost_usd + usage.cost_usd,
    )


def cost_limit_text(agent: Any, total_cost_usd: float, iterations: int) -> str:
    max_task_cost = agent.config.max_task_cost
    if max_task_cost <= 0 or total_cost_usd < max_task_cost:
        return ""
    logger.warning(
        "task_failed",
        surface="operational",
        reason="task_cost_limit",
        total_cost_usd=round(total_cost_usd, 6),
        max_task_cost=max_task_cost,
        iterations=iterations,
    )
    return f"Task exceeded cost limit (${max_task_cost:.2f}). Current spend: ${total_cost_usd:.4f}."


def append_assistant_tool_calls(
    messages: list[dict[str, Any]],
    *,
    accumulated_text: str,
    reasoning_content: str,
    collected_tool_calls: list[Any],
) -> None:
    assistant_msg: dict[str, Any] = {"role": "assistant"}
    if accumulated_text:
        assistant_msg["content"] = accumulated_text
    if reasoning_content:
        assistant_msg["reasoning_content"] = reasoning_content
    assistant_msg["tool_calls"] = [
        {
            "id": tool_call.id,
            "type": "function",
            "function": {
                "name": tool_call.name,
                "arguments": json.dumps(tool_call.arguments, ensure_ascii=False),
            },
        }
        for tool_call in collected_tool_calls
    ]
    messages.append(assistant_msg)


def is_stuck(
    threshold: int,
    recent_tool_sigs: list[str],
    round_result: Any,
) -> bool:
    if threshold <= 0:
        return False
    signature = "|".join(
        f"{tool_call.name}:{json.dumps(tool_call.arguments, sort_keys=True)}"
        for tool_call in round_result.collected_tool_calls
    )
    recent_tool_sigs.append(signature)
    if len(recent_tool_sigs) > threshold:
        recent_tool_sigs.pop(0)
    return len(recent_tool_sigs) >= threshold and len(set(recent_tool_sigs)) == 1
