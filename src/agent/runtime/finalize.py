"""Finalize helpers for post-response agent work."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.agent.turn_outcome import (
    CompletedTurn,
    FailedTurn,
    TurnOutcome,
    replace_turn_content,
)
from src.agent.verification import verify_final_response
from src.core.logging import get_logger

from .stream_context import current_task_state

logger = get_logger(__name__)

if TYPE_CHECKING:
    from src.agent.agent import Agent


async def verify_and_publish_final_response(
    agent: Agent,
    *,
    conversation_id: str,
    platform: str,
    outcome: TurnOutcome,
    iterations: int,
    all_tool_calls: list[dict[str, Any]],
) -> TurnOutcome:
    """Turn vague post-tool responses into explicit failed outcomes."""
    task_state = current_task_state(agent.conversation_manager, conversation_id)
    verified_text, rewritten = verify_final_response(
        outcome.content,
        tool_calls_made=all_tool_calls,
        task_state=task_state,
    )
    if rewritten:
        event_payload = {
            "conversation_id": conversation_id,
            "platform": platform,
            "iterations": iterations,
        }
        await agent.event_bus.publish("harness.completion_verified", event_payload)
        return FailedTurn(verified_text, reason="response_verification")
    return replace_turn_content(outcome, verified_text)


async def finalize_agent_run(
    agent: Agent,
    *,
    conversation_id: str,
    outcome: TurnOutcome,
    model: str,
    tokens_in: int,
    tokens_out: int,
    latency_ms: int,
    iterations: int,
    all_tool_calls: list[dict[str, Any]],
    assistant_timestamp: datetime | None = None,
) -> None:
    """Persist the assistant reply and kick off deferred memory work."""
    await agent.event_bus.publish(
        "agent.think.complete",
        {
            "conversation_id": conversation_id,
            "iterations": iterations,
            "latency_ms": latency_ms,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "tool_calls": len(all_tool_calls),
            "turn_outcome": _outcome_name(outcome),
            "failure_reason": _failure_reason(outcome),
        },
    )

    if agent.conversation_manager and conversation_id:
        timestamp = assistant_timestamp or datetime.now(UTC)
        await _persist_turn(
            agent,
            conversation_id=conversation_id,
            outcome=outcome,
            timestamp=timestamp,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            tool_calls=all_tool_calls or None,
        )


async def _persist_turn(
    agent: Agent,
    *,
    conversation_id: str,
    outcome: TurnOutcome,
    timestamp: datetime,
    model: str,
    tokens_in: int,
    tokens_out: int,
    latency_ms: int,
    tool_calls: list[dict[str, Any]] | None,
) -> None:
    message_fields = {
        "timestamp": timestamp,
        "model": model,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "latency_ms": latency_ms,
        "tool_calls": tool_calls,
    }
    if isinstance(outcome, FailedTurn):
        await agent.conversation_manager.add_failed_assistant_message(
            conversation_id,
            failed_turn=outcome,
            **message_fields,
        )
        return
    await agent.conversation_manager.add_assistant_message(
        conversation_id,
        content=outcome.content,
        **message_fields,
    )
    agent.post_turn_memory.schedule(conversation_id)


def _outcome_name(outcome: TurnOutcome) -> str:
    return "completed" if isinstance(outcome, CompletedTurn) else "failed"


def _failure_reason(outcome: TurnOutcome) -> str:
    return outcome.reason if isinstance(outcome, FailedTurn) else ""
