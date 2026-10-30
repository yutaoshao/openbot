"""Persist interrupted turns without scheduling completed-turn memory work."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.agent.turn_outcome import FailedTurn
from src.memory.message_format import strip_internal_timestamp_prefixes

if TYPE_CHECKING:
    from src.agent.agent import Agent

    from .turn_loop_types import TurnLoopSnapshot
    from .turn_request import TurnRequest


class TurnCancelled(asyncio.CancelledError):
    def __init__(self, partial_text: str) -> None:
        super().__init__("Agent turn cancelled")
        self.partial_text = partial_text


async def persist_interrupted_turn(
    agent: Agent,
    request: TurnRequest,
    *,
    partial_text: str = "",
    snapshot: TurnLoopSnapshot | None = None,
    reason: str = "cancelled",
) -> str:
    # Prompt preparation also uses this terminal writer; import after the runtime
    # modules have loaded to avoid the prompting/stream_context/finalize cycle.
    from .finalize import finalize_agent_run

    content = strip_internal_timestamp_prefixes(partial_text) or (
        "本轮已停止；已经发生的外部操作不会自动撤销。"
        if reason == "cancelled"
        else "本轮执行失败，未作为已完成结果保存。"
    )
    await finalize_agent_run(
        agent,
        conversation_id=request.conversation_id,
        outcome=FailedTurn(content, reason=reason),
        model=snapshot.final_model if snapshot else "",
        tokens_in=snapshot.tokens_in if snapshot else 0,
        tokens_out=snapshot.tokens_out if snapshot else 0,
        latency_ms=0,
        iterations=snapshot.iterations if snapshot else 0,
        all_tool_calls=list(snapshot.tool_calls) if snapshot else [],
    )
    return content
