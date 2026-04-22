"""ReAct loop orchestration for the main Agent."""

from __future__ import annotations

import json
import time
from typing import Any

from src.agent.verification import verify_final_response
from src.core.logging import get_logger
from src.infrastructure.model_gateway import StreamChunk, Usage

from . import prompting
from .finalize import finalize_agent_run
from .rounds import ModelRoundResult, stream_model_round
from .tool_calls import ToolExecutionBatch, execute_tool_calls_for_round

logger = get_logger(__name__)

build_system_prompt = prompting.build_system_prompt
prepare_agent_turn = prompting.prepare_agent_turn
resolve_tools = prompting.resolve_tools


async def run_stream_inner(
    agent: Any,
    input_text: str,
    conversation_id: str,
    platform: str,
    user_id: str,
    ctx: Any,
):
    """Inner streaming loop with trace context active."""
    messages, _ = await prepare_agent_turn(
        agent,
        input_text,
        conversation_id,
        platform,
        user_id,
    )
    await agent.event_bus.publish(
        "agent.think.start",
        {"conversation_id": conversation_id, "input_length": len(input_text)},
    )

    iterations = 0
    total_tokens_in = 0
    total_tokens_out = 0
    all_tool_calls: list[dict[str, Any]] = []
    final_text = ""
    final_model = ""
    task_start = time.monotonic()
    recent_tool_sigs: list[str] = []

    while iterations < agent.max_iterations:
        current_task_state = _task_state(agent, conversation_id)
        current_tools = resolve_tools(agent, input_text, task_state=current_task_state)
        timeout_text = _timeout_text(agent, task_start, iterations)
        if timeout_text:
            final_text = timeout_text
            break

        iterations += 1
        ctx.iteration = iterations
        logger.info(
            "thought_step",
            surface="cognitive",
            iteration=iterations,
            max_iterations=agent.max_iterations,
        )

        round_result = None
        async for event in stream_model_round(agent, messages, current_tools):
            if isinstance(event, StreamChunk):
                yield event
            else:
                round_result = event
        assert isinstance(round_result, ModelRoundResult)
        final_model = round_result.model or final_model
        total_tokens_in, total_tokens_out = _accumulate_usage(
            total_tokens_in,
            total_tokens_out,
            round_result.usage,
        )

        if not round_result.collected_tool_calls:
            logger.info(
                "decision_made",
                surface="cognitive",
                decision="final_reply",
                iteration=iterations,
            )
            final_text = round_result.accumulated_text
            break

        logger.info(
            "decision_made",
            surface="cognitive",
            decision="tool_calls",
            tool_count=len(round_result.collected_tool_calls),
            tools=[tool_call.name for tool_call in round_result.collected_tool_calls],
            iteration=iterations,
        )
        _append_assistant_tool_calls(
            messages,
            accumulated_text=round_result.accumulated_text,
            collected_tool_calls=round_result.collected_tool_calls,
        )

        batch = None
        async for event in execute_tool_calls_for_round(
            agent,
            collected_tool_calls=round_result.collected_tool_calls,
            conversation_id=conversation_id,
            platform=platform,
            task_state=current_task_state,
            task_start=task_start,
            task_timeout=agent.config.task_timeout,
            iterations=iterations,
            messages=messages,
        ):
            if isinstance(event, StreamChunk):
                yield event
            else:
                batch = event
        assert isinstance(batch, ToolExecutionBatch)
        all_tool_calls.extend(batch.executed_calls)

        if _is_stuck(agent.config.stuck_detection_threshold, recent_tool_sigs, round_result):
            final_text = (
                "Agent appears stuck — repeating the same tool calls. "
                "Stopping to avoid wasting resources."
            )
            logger.warning(
                "task_failed",
                surface="operational",
                reason="stuck_loop",
                repeated_sig=recent_tool_sigs[-1][:200],
                iterations=iterations,
            )
            break
    else:
        final_text = "Task exceeded maximum iterations."
        logger.warning(
            "task_failed",
            surface="operational",
            reason="max_iterations",
            iterations=iterations,
        )

    final_text = await _finalize_text(
        agent,
        conversation_id=conversation_id,
        platform=platform,
        final_text=final_text,
        iterations=iterations,
        all_tool_calls=all_tool_calls,
    )
    await finalize_agent_run(
        agent,
        conversation_id=conversation_id,
        user_id=user_id,
        content=final_text,
        model=final_model,
        tokens_in=total_tokens_in,
        tokens_out=total_tokens_out,
        latency_ms=0,
        iterations=iterations,
        all_tool_calls=all_tool_calls,
    )
    yield StreamChunk(
        type="done",
        usage=Usage(tokens_in=total_tokens_in, tokens_out=total_tokens_out),
        model=final_model,
        iterations=iterations,
    )


def _task_state(agent: Any, conversation_id: str) -> Any:
    if not agent.conversation_manager or not conversation_id:
        return None
    return agent.conversation_manager.get_task_state(conversation_id)


def _timeout_text(agent: Any, task_start: float, iterations: int) -> str:
    task_timeout = agent.config.task_timeout
    if task_timeout <= 0:
        return ""
    elapsed = time.monotonic() - task_start
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


def _accumulate_usage(tokens_in: int, tokens_out: int, usage: Usage | None) -> tuple[int, int]:
    if usage is None:
        return tokens_in, tokens_out
    return tokens_in + usage.tokens_in, tokens_out + usage.tokens_out


def _append_assistant_tool_calls(
    messages: list[dict[str, Any]],
    *,
    accumulated_text: str,
    collected_tool_calls: list[Any],
) -> None:
    assistant_msg: dict[str, Any] = {"role": "assistant"}
    if accumulated_text:
        assistant_msg["content"] = accumulated_text
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


def _is_stuck(
    threshold: int,
    recent_tool_sigs: list[str],
    round_result: ModelRoundResult,
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


async def _finalize_text(
    agent: Any,
    *,
    conversation_id: str,
    platform: str,
    final_text: str,
    iterations: int,
    all_tool_calls: list[dict[str, Any]],
) -> str:
    task_state = _task_state(agent, conversation_id)
    verified_text, verified = verify_final_response(
        final_text,
        tool_calls_made=all_tool_calls,
        task_state=task_state,
    )
    if verified:
        await agent.event_bus.publish(
            "harness.completion_verified",
            {
                "conversation_id": conversation_id,
                "platform": platform,
                "iterations": iterations,
            },
        )
    return verified_text
