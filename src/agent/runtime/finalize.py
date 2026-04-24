"""Finalize helpers for post-response agent work."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from src.core.logging import get_logger
from src.core.trace import TraceContext, current_trace

logger = get_logger(__name__)


@dataclass(frozen=True)
class _BackgroundTraceInfo:
    interaction_id: str
    platform: str
    parent_trace_id: str


async def finalize_agent_run(
    agent: Any,
    *,
    conversation_id: str,
    user_id: str,
    content: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    latency_ms: int,
    iterations: int,
    all_tool_calls: list[dict[str, Any]],
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
        },
    )

    if agent.conversation_manager and conversation_id:
        await agent.conversation_manager.add_assistant_message(
            conversation_id,
            content=content,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            tool_calls=all_tool_calls or None,
        )
        schedule_memory_finalize(agent, conversation_id)


def schedule_memory_finalize(agent: Any, conversation_id: str) -> None:
    """Run heavy memory extraction after the user-facing reply is ready."""
    previous = agent._memory_finalize_tasks.get(conversation_id)  # noqa: SLF001
    trace_info = _capture_background_trace(conversation_id)
    task = asyncio.create_task(
        run_memory_finalize(
            agent,
            conversation_id,
            wait_for=previous,
            trace_info=trace_info,
        ),
        name=f"memory-finalize:{conversation_id}",
    )
    agent._memory_finalize_tasks[conversation_id] = task  # noqa: SLF001


async def run_memory_finalize(
    agent: Any,
    conversation_id: str,
    *,
    wait_for: asyncio.Task[None] | None,
    trace_info: _BackgroundTraceInfo,
) -> None:
    """Serialize post-response memory work per conversation."""
    if wait_for is not None:
        try:
            await wait_for
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "conversation.background_finalize_prior_failed",
                conversation_id=conversation_id,
                exc_info=True,
            )

    if agent.conversation_manager is None:
        return

    try:
        with TraceContext(
            interaction_id=trace_info.interaction_id,
            platform=trace_info.platform,
            parent_action_id=trace_info.parent_trace_id,
            extra={"trigger": "post_reply_sync"},
        ):
            await _run_background_step(
                agent.conversation_manager.maybe_compress,
                conversation_id,
                "conversation.background_compress_failed",
            )
            await _run_background_step(
                agent.conversation_manager.sync_memory_after_turn,
                conversation_id,
                "conversation.background_sync_failed",
            )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception(
            "conversation.background_finalize_failed",
            conversation_id=conversation_id,
        )
    finally:
        current_task = asyncio.current_task()
        if agent._memory_finalize_tasks.get(conversation_id) is current_task:  # noqa: SLF001
            agent._memory_finalize_tasks.pop(conversation_id, None)  # noqa: SLF001


def _capture_background_trace(conversation_id: str) -> _BackgroundTraceInfo:
    trace = current_trace()
    if trace is None:
        return _BackgroundTraceInfo(
            interaction_id=conversation_id,
            platform="",
            parent_trace_id="",
        )
    return _BackgroundTraceInfo(
        interaction_id=trace.interaction_id or conversation_id,
        platform=trace.platform,
        parent_trace_id=trace.trace_id,
    )


async def _run_background_step(
    action: Any,
    conversation_id: str,
    error_event: str,
) -> None:
    try:
        await action(conversation_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception(error_event, conversation_id=conversation_id)
