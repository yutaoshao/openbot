"""Thin façade for the main Agent runtime."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.agent.runtime import execute_tool_call, run_stream_inner
from src.core.trace import TraceContext
from src.tools.hooks import ToolHookManager, ToolSearchActivationHook

if TYPE_CHECKING:
    import asyncio
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
    ) -> None:
        self.model_gateway = model_gateway
        self.event_bus = event_bus
        self.config = config
        self.max_iterations = config.max_iterations
        self.tool_registry = tool_registry
        self.conversation_manager = conversation_manager
        self.skill_registry = skill_registry
        self._tool_hooks = ToolHookManager([ToolSearchActivationHook()])
        self._memory_finalize_tasks: dict[str, asyncio.Task[None]] = {}

    async def run(
        self,
        input_text: str,
        conversation_id: str = "",
        platform: str = "unknown",
        user_id: str = "",
    ) -> AgentResponse:
        """Execute the agent ReAct loop (non-streaming)."""
        start = time.monotonic()
        content = ""
        model = ""
        total_tokens_in = 0
        total_tokens_out = 0
        tool_calls_made: list[dict[str, Any]] = []
        iterations = 0

        async for chunk in self.run_stream(input_text, conversation_id, platform, user_id):
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
    ) -> AsyncIterator[StreamChunk]:
        """Execute the agent ReAct loop, yielding StreamChunks."""
        ctx = TraceContext(interaction_id=conversation_id, platform=platform)
        with ctx:
            async for chunk in run_stream_inner(
                self,
                input_text,
                conversation_id,
                platform,
                user_id,
                ctx,
            ):
                yield chunk

    async def _execute_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        conversation_id: str,
        platform: str,
        task_state: Any = None,
        timeout_override: float | None = None,
    ):
        """Compatibility wrapper for tests and legacy call sites."""
        return await execute_tool_call(
            self,
            name,
            arguments,
            conversation_id=conversation_id,
            platform=platform,
            task_state=task_state,
            timeout_override=timeout_override,
        )
