"""ReAct loop orchestration for the main Agent."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from src.agent.state.task_contract_planner import (
    plan_scheduled_task_contract,
    plan_task_contract,
)
from src.agent.verification import verify_final_response
from src.agent.verification.stop import ledger_from_tool_calls, verify_stop
from src.core.logging import get_logger
from src.infrastructure.model_gateway import StreamChunk, Usage
from src.infrastructure.model_routing import RouteRequest
from src.memory.message_format import strip_internal_timestamp_prefixes

from . import prompting
from .finalize import finalize_agent_run
from .loop_helpers import (
    accumulate_usage,
    append_assistant_tool_calls,
    cost_limit_text,
    is_stuck,
    reply_chunks,
    timeout_text,
)
from .rounds import ModelRoundResult, stream_model_round
from .tool_calls import ToolExecutionBatch, execute_tool_calls_for_round
from .write_retry import append_file_write_retry as _append_file_write_retry
from .write_retry import needs_file_write_retry as _needs_file_write_retry

logger = get_logger(__name__)
if TYPE_CHECKING:
    from datetime import datetime
build_system_prompt = prompting.build_system_prompt
prepare_agent_turn = prompting.prepare_agent_turn
resolve_route_tool_names = prompting.resolve_route_tool_names
resolve_tools = prompting.resolve_tools


async def run_stream_inner(
    agent: Any,
    input_text: str,
    conversation_id: str,
    platform: str,
    user_id: str,
    ctx: Any,
    *,
    message_timestamp: datetime,
    source_message_id: str = "",
    platform_user_id: str = "",
):
    """Inner streaming loop with trace context active."""
    messages, _ = await prepare_agent_turn(
        agent,
        input_text,
        conversation_id,
        platform,
        user_id,
        message_timestamp,
        source_message_id,
        platform_user_id,
    )
    route_decision = _route_decision(agent, input_text, _task_state(agent, conversation_id))
    await agent.event_bus.publish(
        "agent.think.start",
        {"conversation_id": conversation_id, "input_length": len(input_text)},
    )

    iterations = 0
    total_tokens_in = 0
    total_tokens_out = 0
    total_cost_usd = 0.0
    all_tool_calls: list[dict[str, Any]] = []
    final_text = ""
    final_model = ""
    pending_final_chunks: list[StreamChunk] = []
    pending_final_text = ""
    task_start = time.monotonic()
    recent_tool_sigs: list[str] = []
    emit_final_text = False
    contract_planner = (
        plan_scheduled_task_contract if platform == "scheduler" else plan_task_contract
    )
    contract = await contract_planner(
        agent.model_gateway,
        input_text,
        messages=messages,
        task_state=_task_state(agent, conversation_id),
    )

    while iterations < agent.max_iterations:
        current_task_state = _task_state(agent, conversation_id)
        current_tools = resolve_tools(agent, input_text, task_state=current_task_state)
        timeout_message = timeout_text(agent, task_start, iterations)
        if timeout_message:
            final_text = timeout_message
            emit_final_text = True
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
        round_text_chunks: list[StreamChunk] = []
        async for event in stream_model_round(
            agent,
            messages,
            current_tools,
            route_decision=route_decision,
        ):
            if isinstance(event, StreamChunk):
                if event.type == "text":
                    round_text_chunks.append(event)
            else:
                round_result = event
        assert isinstance(round_result, ModelRoundResult)
        final_model = round_result.model or final_model
        total_tokens_in, total_tokens_out, total_cost_usd = accumulate_usage(
            total_tokens_in,
            total_tokens_out,
            total_cost_usd,
            round_result.usage,
        )

        if not round_result.collected_tool_calls:
            logger.info(
                "decision_made",
                surface="cognitive",
                decision="final_reply",
                iteration=iterations,
            )
            if _needs_file_write_retry(contract, all_tool_calls):
                _append_file_write_retry(messages, round_result.accumulated_text)
                continue
            final_text = round_result.accumulated_text
            pending_final_text = final_text
            pending_final_chunks = round_text_chunks
            break

        cost_limit_message = cost_limit_text(agent, total_cost_usd, iterations)
        if cost_limit_message:
            final_text = cost_limit_message
            emit_final_text = True
            break

        logger.info(
            "decision_made",
            surface="cognitive",
            decision="tool_calls",
            tool_count=len(round_result.collected_tool_calls),
            tools=[tool_call.name for tool_call in round_result.collected_tool_calls],
            iteration=iterations,
        )
        append_assistant_tool_calls(
            messages,
            accumulated_text=round_result.accumulated_text,
            reasoning_content=round_result.reasoning_content,
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

        if is_stuck(agent.config.stuck_detection_threshold, recent_tool_sigs, round_result):
            final_text = (
                "Agent appears stuck — repeating the same tool calls. "
                "Stopping to avoid wasting resources."
            )
            emit_final_text = True
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
        emit_final_text = True
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
    final_text = strip_internal_timestamp_prefixes(final_text)
    stop_decision = verify_stop(contract, final_text, ledger_from_tool_calls(all_tool_calls))
    if not stop_decision.allow:
        final_text = stop_decision.message
        emit_final_text = True
    final_text = strip_internal_timestamp_prefixes(final_text)
    for chunk in reply_chunks(
        final_text,
        pending_final_text=pending_final_text,
        pending_final_chunks=pending_final_chunks,
        force_single_chunk=emit_final_text,
    ):
        yield chunk
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
        usage=Usage(
            tokens_in=total_tokens_in,
            tokens_out=total_tokens_out,
            cost_usd=total_cost_usd,
        ),
        model=final_model,
        iterations=iterations,
    )


def _task_state(agent: Any, conversation_id: str) -> Any:
    if not agent.conversation_manager or not conversation_id:
        return None
    return agent.conversation_manager.get_task_state(conversation_id)


def _route_decision(agent: Any, input_text: str, task_state: Any) -> Any:
    decide_route = getattr(agent.model_gateway, "decide_route", None)
    if not callable(decide_route):
        return None
    tool_names = resolve_route_tool_names(agent, input_text, task_state=task_state)
    return decide_route(RouteRequest(input_text=input_text, tool_names=tool_names))


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
        data = {
            "conversation_id": conversation_id,
            "platform": platform,
            "iterations": iterations,
        }
        await agent.event_bus.publish("harness.completion_verified", data)
    return verified_text
