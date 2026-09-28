"""Thin façade for the main Agent runtime."""

from __future__ import annotations

import time
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.agent.conversation.post_turn import PostTurnMemory
from src.agent.runtime import TurnRequest, run_stream_inner
from src.core.trace import TraceContext, current_trace
from src.tools.hooks import ToolHookManager, ToolSearchActivationHook

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from src.agent.conversation import ConversationManager
    from src.agent.skills import SkillRegistry
    from src.core.config import AgentConfig
    from src.infrastructure.event_bus import EventBus
    from src.infrastructure.model_gateway import ModelGateway, StreamChunk
    from src.tools.registry import ToolRegistry


@dataclass
class AgentResponse:
    """Response from the agent loop."""

    content: str
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    iterations: int = 0
    tool_calls_made: list[dict[str, Any]] = field(default_factory=list)


class Agent:
    """Main agent façade delegating to smaller runtime helpers."""

    def __init__(
        self,
        model_gateway: ModelGateway,
        event_bus: EventBus,
        config: AgentConfig,
        tool_registry: ToolRegistry | None = None,
        conversation_manager: ConversationManager | None = None,
        skill_registry: SkillRegistry | None = None,
        post_turn_memory: PostTurnMemory | None = None,
    ) -> None:
        self.model_gateway = model_gateway
        self.event_bus = event_bus
        self.config = config
        self.max_iterations = config.max_iterations
        self.tool_registry = tool_registry
        self.conversation_manager = conversation_manager
        self.skill_registry = skill_registry
        self.tool_hooks = ToolHookManager([ToolSearchActivationHook()])
        self.post_turn_memory = post_turn_memory or PostTurnMemory(conversation_manager)

    async def confirm_delivery(self, conversation_id: str, content: str, delivery_id: str) -> None:
        """Called only after the channel acknowledges the final reply's transport."""
        if self.conversation_manager and self.conversation_manager.followups:
            await self.conversation_manager.followups.confirm_delivery(
                conversation_id, content, delivery_id
            )

    async def run(
        self,
        input_text: str,
        conversation_id: str = "",
        platform: str = "unknown",
        user_id: str = "",
        *,
        message_timestamp: datetime | None = None,
        source_message_id: str = "",
        platform_user_id: str = "",
    ) -> AgentResponse:
        """Execute the agent ReAct loop (non-streaming)."""
        start = time.monotonic()
        content = ""
        model = ""
        total_tokens_in = 0
        total_tokens_out = 0
        tool_calls_made: list[dict[str, Any]] = []
        iterations = 0

        async for chunk in self.run_stream(
            input_text,
            conversation_id=conversation_id,
            platform=platform,
            user_id=user_id,
            message_timestamp=message_timestamp,
            source_message_id=source_message_id,
            platform_user_id=platform_user_id,
        ):
            if chunk.type == "text":
                content += chunk.text
            elif chunk.type == "tool_status":
                tool_calls_made.append({"name": chunk.tool_name})
            elif chunk.type == "done":
                model = chunk.model
                iterations = chunk.iterations
                if chunk.usage:
                    total_tokens_in = chunk.usage.tokens_in
                    total_tokens_out = chunk.usage.tokens_out

        return AgentResponse(
            content=content,
            model=model,
            tokens_in=total_tokens_in,
            tokens_out=total_tokens_out,
            latency_ms=int((time.monotonic() - start) * 1000),
            iterations=iterations,
            tool_calls_made=tool_calls_made,
        )

    async def run_stream(
        self,
        input_text: str,
        conversation_id: str = "",
        platform: str = "unknown",
        user_id: str = "",
        *,
        message_timestamp: datetime | None = None,
        source_message_id: str = "",
        platform_user_id: str = "",
    ) -> AsyncIterator[StreamChunk]:
        """Execute the agent ReAct loop, yielding StreamChunks."""
        resolved_timestamp = _resolve_message_timestamp(message_timestamp)
        active_trace = current_trace()
        ctx = active_trace or TraceContext(
            interaction_id=conversation_id,
            platform=platform,
        )
        previous_iteration = ctx.iteration
        scope = nullcontext() if active_trace is not None else ctx
        with scope:
            try:
                async for chunk in run_stream_inner(
                    self,
                    TurnRequest(
                        input_text=input_text,
                        conversation_id=conversation_id,
                        platform=platform,
                        user_id=user_id,
                        message_timestamp=resolved_timestamp,
                        source_message_id=source_message_id,
                        platform_user_id=platform_user_id,
                    ),
                    ctx,
                ):
                    yield chunk
            finally:
                ctx.iteration = previous_iteration


def _resolve_message_timestamp(message_timestamp: datetime | None) -> datetime:
    if message_timestamp is None:
        return datetime.now(UTC)
    if message_timestamp.tzinfo is None or message_timestamp.utcoffset() is None:
        raise ValueError("message timestamp must be timezone-aware")
    return message_timestamp
