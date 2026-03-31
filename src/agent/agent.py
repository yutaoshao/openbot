"""Agent core - ReAct reasoning loop.

Implements the Think -> Decide -> Act -> Observe cycle.
Supports both non-streaming (run) and streaming (run_stream) execution.

All log events follow the AgentTrace three-surface taxonomy:
- Cognitive: thought_step, decision_made
- Operational: tool_called, tool_returned, llm_requested, llm_completed, task_finished
- Contextual: task_received (emitted by Application layer)
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.core.logging import get_logger
from src.core.trace import TraceContext
from src.infrastructure.model_gateway import StreamChunk, Usage
from src.tools.runtime import ToolExecutionContext, tool_execution_context

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from src.agent.conversation import ConversationManager
    from src.agent.skill import SkillRegistry
    from src.core.config import AgentConfig
    from src.infrastructure.event_bus import EventBus
    from src.infrastructure.model_gateway import ModelGateway
    from src.tools.registry import ToolRegistry, ToolResult

logger = get_logger(__name__)

DEFAULT_SYSTEM_PROMPT = """You are OpenBot, a helpful personal AI assistant.

Current date: {date}

Guidelines:
- Be concise and accurate
- If you don't know something, say so honestly
- Respond in the same language as the user's message
- Use tools when they would help answer the question
- When the user asks you to do something on a schedule or repeatedly,
  use a scheduling tool if one is available
- Always explain what you found after using a tool
"""


@dataclass
class AgentResponse:
    """Response from the agent loop."""

    content: str
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    latency_ms: int = 0
    iterations: int = 0
    tool_calls_made: list[dict[str, Any]] = field(default_factory=list)


class Agent:
    """Main agent with ReAct reasoning loop."""

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


    async def run(
        self,
        input_text: str,
        conversation_id: str = "",
        platform: str = "unknown",
    ) -> AgentResponse:
        """Execute the agent ReAct loop (non-streaming).

        Internally consumes ``run_stream()`` and assembles the final
        ``AgentResponse``.  Behaviour and return type are unchanged.
        """
        start = time.monotonic()
        content = ""
        model = ""
        total_tokens_in = 0
        total_tokens_out = 0
        total_cost = 0.0
        tool_calls_made: list[dict[str, Any]] = []
        iterations = 0

        async for chunk in self.run_stream(input_text, conversation_id, platform):
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
                    total_cost = chunk.usage.cost

        total_latency = int((time.monotonic() - start) * 1000)

        return AgentResponse(
            content=content,
            model=model,
            tokens_in=total_tokens_in,
            tokens_out=total_tokens_out,
            cost=total_cost,
            latency_ms=total_latency,
            iterations=iterations,
            tool_calls_made=tool_calls_made,
        )

    async def run_stream(
        self,
        input_text: str,
        conversation_id: str = "",
        platform: str = "unknown",
    ) -> AsyncIterator[StreamChunk]:
        """Execute the agent ReAct loop, yielding StreamChunks."""
        # Create trace context for this request
        ctx = TraceContext(
            interaction_id=conversation_id,
            platform=platform,
        )
        with ctx:
            async for chunk in self._run_stream_inner(
                input_text, conversation_id, platform, ctx,
            ):
                yield chunk

    async def _run_stream_inner(
        self,
        input_text: str,
        conversation_id: str,
        platform: str,
        ctx: TraceContext,
    ) -> AsyncIterator[StreamChunk]:
        """Inner streaming loop with trace context active."""
        messages, tools = await self._prepare(
            input_text, conversation_id, platform,
        )

        await self.event_bus.publish("agent.think.start", {
            "conversation_id": conversation_id,
            "input_length": len(input_text),
        })

        iterations = 0
        total_tokens_in = 0
        total_tokens_out = 0
        total_cost = 0.0
        all_tool_calls: list[dict[str, Any]] = []
        final_text = ""
        final_model = ""
        task_start = time.monotonic()
        task_timeout = self.config.task_timeout  # 0 = no limit
        max_task_cost = self.config.max_task_cost  # 0 = no limit
        stuck_threshold = self.config.stuck_detection_threshold  # 0 = disable
        # Track recent tool call signatures for stuck detection
        _recent_tool_sigs: list[str] = []

        while iterations < self.max_iterations:
            # Check task-level timeout
            if task_timeout > 0:
                elapsed = time.monotonic() - task_start
                if elapsed >= task_timeout:
                    final_text = (
                        f"Task exceeded time limit ({task_timeout}s). "
                        f"Completed {iterations} iterations."
                    )
                    logger.warning(
                        "task_failed",
                        surface="operational",
                        reason="task_timeout",
                        elapsed_s=int(elapsed),
                        iterations=iterations,
                    )
                    break

            # Check cost cap
            if max_task_cost > 0 and total_cost >= max_task_cost:
                final_text = (
                    f"Task exceeded cost limit (${max_task_cost:.2f}). "
                    f"Spent ${total_cost:.4f} over {iterations} iterations."
                )
                logger.warning(
                    "task_failed",
                    surface="operational",
                    reason="cost_limit",
                    cost=total_cost,
                    limit=max_task_cost,
                    iterations=iterations,
                )
                break

            iterations += 1
            ctx.iteration = iterations

            # Cognitive: thought step
            logger.info(
                "thought_step",
                surface="cognitive",
                iteration=iterations,
                max_iterations=self.max_iterations,
            )

            accumulated_text = ""
            collected_tool_calls: list[Any] = []
            iter_usage: Usage | None = None

            async for chunk in self.model_gateway.chat_stream(
                messages=messages, tools=tools,
            ):
                if chunk.type == "text":
                    accumulated_text += chunk.text
                    yield chunk
                elif chunk.type == "tool_call":
                    collected_tool_calls.append(chunk.tool_call)
                elif chunk.type == "done":
                    iter_usage = chunk.usage
                    final_model = chunk.model

            # Accumulate usage
            if iter_usage:
                total_tokens_in += iter_usage.tokens_in
                total_tokens_out += iter_usage.tokens_out
                total_cost += iter_usage.cost

            # Cognitive: decision — tools or final reply
            if not collected_tool_calls:
                logger.info(
                    "decision_made",
                    surface="cognitive",
                    decision="final_reply",
                    iteration=iterations,
                )
                final_text = accumulated_text
                break

            logger.info(
                "decision_made",
                surface="cognitive",
                decision="tool_calls",
                tool_count=len(collected_tool_calls),
                tools=[tc.name for tc in collected_tool_calls],
                iteration=iterations,
            )

            # Build assistant message for context
            assistant_msg: dict[str, Any] = {"role": "assistant"}
            if accumulated_text:
                assistant_msg["content"] = accumulated_text
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(
                            tc.arguments, ensure_ascii=False,
                        ),
                    },
                }
                for tc in collected_tool_calls
            ]
            messages.append(assistant_msg)

            for tc in collected_tool_calls:
                yield StreamChunk(type="tool_status", tool_name=tc.name)

                tool_start = time.monotonic()
                tool_result = await self._execute_tool(
                    tc.name,
                    tc.arguments,
                    conversation_id=conversation_id,
                    platform=platform,
                    timeout_override=(
                        max(0.001, task_timeout - (time.monotonic() - task_start))
                        if task_timeout > 0
                        else None
                    ),
                )
                tool_latency = int((time.monotonic() - tool_start) * 1000)

                # Operational: tool_called + tool_returned
                logger.info(
                    "tool_called",
                    surface="operational",
                    tool=tc.name,
                    status="error" if tool_result.is_error else "success",
                    latency_ms=tool_latency,
                    result_length=len(tool_result.content),
                )

                all_tool_calls.append({
                    "name": tc.name,
                    "arguments": tc.arguments,
                    "result_preview": tool_result.content[:200],
                    "is_error": tool_result.is_error,
                })

                messages.append(tool_result.to_message(tc.id))

                await self.event_bus.publish("agent.tool.executed", {
                    "conversation_id": conversation_id,
                    "tool": tc.name,
                    "is_error": tool_result.is_error,
                    "iteration": iterations,
                })

            # Stuck detection: check if the same tool calls repeat consecutively
            if stuck_threshold > 0:
                # Build a signature from this iteration's tool calls
                sig = "|".join(
                    f"{tc.name}:{json.dumps(tc.arguments, sort_keys=True)}"
                    for tc in collected_tool_calls
                )
                _recent_tool_sigs.append(sig)
                # Only keep the last N signatures
                if len(_recent_tool_sigs) > stuck_threshold:
                    _recent_tool_sigs.pop(0)
                # If last N are identical, agent is stuck
                if (
                    len(_recent_tool_sigs) >= stuck_threshold
                    and len(set(_recent_tool_sigs)) == 1
                ):
                    final_text = (
                        "Agent appears stuck — repeating the same tool calls. "
                        "Stopping to avoid wasting resources."
                    )
                    logger.warning(
                        "task_failed",
                        surface="operational",
                        reason="stuck_loop",
                        repeated_sig=sig[:200],
                        iterations=iterations,
                    )
                    break

        else:
            # Max iterations reached
            final_text = "Task exceeded maximum iterations."
            logger.warning(
                "task_failed",
                surface="operational",
                reason="max_iterations",
                iterations=iterations,
            )

        # Post-loop: persist and compress
        await self._finalize(
            conversation_id=conversation_id,
            content=final_text,
            model=final_model,
            tokens_in=total_tokens_in,
            tokens_out=total_tokens_out,
            cost=total_cost,
            latency_ms=0,
            iterations=iterations,
            all_tool_calls=all_tool_calls,
        )


        yield StreamChunk(
            type="done",
            usage=Usage(
                tokens_in=total_tokens_in,
                tokens_out=total_tokens_out,
                cost=total_cost,
            ),
            model=final_model,
            iterations=iterations,
        )


    def _build_system_prompt(self) -> str:
        """Build system prompt with current context and skill metadata."""
        template = self.config.system_prompt or DEFAULT_SYSTEM_PROMPT
        prompt = template.format(
            date=datetime.now(UTC).strftime("%Y-%m-%d"),
        )

        # Inject skill metadata (Layer 1: progressive disclosure)
        if self.skill_registry:
            skills_block = self.skill_registry.get_metadata_prompt()
            if skills_block:
                prompt += "\n\n" + skills_block

        return prompt

    async def _prepare(
        self,
        input_text: str,
        conversation_id: str,
        platform: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
        """Build messages and tools for the ReAct loop."""
        if self.conversation_manager and conversation_id:
            await self.conversation_manager.get_or_create_conversation(
                conversation_id, platform, self.config.token_budget,
            )
            await self.conversation_manager.add_user_message(
                conversation_id, input_text,
            )
            messages = await self.conversation_manager.build_messages(
                conversation_id,
                self._build_system_prompt(),
                input_text,
            )
        else:
            messages = [
                {"role": "system", "content": self._build_system_prompt()},
                {"role": "user", "content": input_text},
            ]

        tools = self.tool_registry.get_schemas() if self.tool_registry else None
        return messages, tools

    async def _finalize(
        self,
        *,
        conversation_id: str,
        content: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        cost: float,
        latency_ms: int,
        iterations: int,
        all_tool_calls: list[dict[str, Any]],
    ) -> None:
        """Post-loop: publish events, persist messages, check compression."""
        await self.event_bus.publish("agent.think.complete", {
            "conversation_id": conversation_id,
            "iterations": iterations,
            "latency_ms": latency_ms,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost": cost,
            "tool_calls": len(all_tool_calls),
        })

        if self.conversation_manager and conversation_id:
            await self.conversation_manager.add_assistant_message(
                conversation_id,
                content=content,
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost=cost,
                latency_ms=latency_ms,
                tool_calls=all_tool_calls or None,
            )
            await self.conversation_manager.maybe_compress(conversation_id)

    async def _execute_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        conversation_id: str,
        platform: str,
        timeout_override: float | None = None,
    ) -> ToolResult:
        """Execute a single tool call by name."""
        from src.tools.registry import ToolResult

        if not self.tool_registry:
            return ToolResult(content="No tools available", is_error=True)

        tool = self.tool_registry.get(name)
        if not tool:
            return ToolResult(content=f"Unknown tool: {name}", is_error=True)

        configured_timeout = self.config.tool_timeout if self.config.tool_timeout > 0 else None
        timeout_candidates = [
            timeout
            for timeout in (configured_timeout, timeout_override)
            if timeout is not None and timeout > 0
        ]
        effective_timeout = min(timeout_candidates) if timeout_candidates else None

        try:
            with tool_execution_context(
                ToolExecutionContext(
                    conversation_id=conversation_id,
                    platform=platform,
                )
            ):
                if effective_timeout is None:
                    return await tool.execute(arguments)
                return await asyncio.wait_for(
                    tool.execute(arguments),
                    timeout=effective_timeout,
                )
        except asyncio.TimeoutError:
            logger.warning(
                "tool_timeout",
                surface="operational",
                tool=name,
                timeout_s=round(effective_timeout or 0.0, 3),
            )
            return ToolResult(
                content=f"Tool '{name}' timed out after {effective_timeout:.2f}s",
                is_error=True,
            )
        except Exception as e:
            logger.exception(
                "tool_called",
                surface="operational",
                tool=name,
                status="exception",
                error=str(e),
            )
            return ToolResult(content=f"Tool error: {e}", is_error=True)
