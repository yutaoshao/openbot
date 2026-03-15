"""Agent core - ReAct reasoning loop.

Implements the Think -> Decide -> Act -> Observe cycle.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.platform.logging import get_logger

if TYPE_CHECKING:
    from src.infrastructure.event_bus import EventBus
    from src.infrastructure.model_gateway import ModelGateway
    from src.platform.config import AgentConfig
    from src.tools.registry import ToolRegistry, ToolResult

logger = get_logger(__name__)

DEFAULT_SYSTEM_PROMPT = """You are OpenBot, a helpful personal AI assistant.

Current date: {date}

Guidelines:
- Be concise and accurate
- If you don't know something, say so honestly
- Respond in the same language as the user's message
- Use tools when they would help answer the question
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
    ) -> None:
        self.model_gateway = model_gateway
        self.event_bus = event_bus
        self.config = config
        self.max_iterations = config.max_iterations
        self.tool_registry = tool_registry

    def _build_system_prompt(self) -> str:
        """Build system prompt with current context."""
        template = self.config.system_prompt or DEFAULT_SYSTEM_PROMPT
        return template.format(
            date=datetime.now(UTC).strftime("%Y-%m-%d"),
        )

    async def run(self, input_text: str, conversation_id: str = "") -> AgentResponse:
        """Execute the agent ReAct loop.

        Loop: model response -> check tool calls -> execute tools -> feed results back -> repeat.
        Terminates when model returns text without tool calls, or max iterations reached.
        """
        start = time.monotonic()

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user", "content": input_text},
        ]

        # Prepare tool schemas if registry is available
        tools = self.tool_registry.get_schemas() if self.tool_registry else None

        await self.event_bus.publish("agent.think.start", {
            "conversation_id": conversation_id,
            "input_length": len(input_text),
        })

        iterations = 0
        total_tokens_in = 0
        total_tokens_out = 0
        total_cost = 0.0
        all_tool_calls: list[dict[str, Any]] = []

        while iterations < self.max_iterations:
            iterations += 1

            response = await self.model_gateway.chat(messages=messages, tools=tools)

            total_tokens_in += response.usage.tokens_in
            total_tokens_out += response.usage.tokens_out
            total_cost += response.usage.cost

            # No tool calls: final response
            if not response.has_tool_calls:
                total_latency = int((time.monotonic() - start) * 1000)

                result = AgentResponse(
                    content=response.text,
                    model=response.model,
                    tokens_in=total_tokens_in,
                    tokens_out=total_tokens_out,
                    cost=total_cost,
                    latency_ms=total_latency,
                    iterations=iterations,
                    tool_calls_made=all_tool_calls,
                )

                await self.event_bus.publish("agent.think.complete", {
                    "conversation_id": conversation_id,
                    "iterations": iterations,
                    "latency_ms": total_latency,
                    "tokens_in": total_tokens_in,
                    "tokens_out": total_tokens_out,
                    "cost": total_cost,
                    "tool_calls": len(all_tool_calls),
                })

                return result

            # Has tool calls: execute and continue loop
            # Append assistant message with tool calls to context
            messages.append(response.to_assistant_message())

            for tc in response.tool_calls:
                tool_result = await self._execute_tool(tc.name, tc.arguments)

                all_tool_calls.append({
                    "name": tc.name,
                    "arguments": tc.arguments,
                    "result_preview": tool_result.content[:200],
                    "is_error": tool_result.is_error,
                })

                # Append tool result to messages for model context
                messages.append(tool_result.to_message(tc.id))

                await self.event_bus.publish("agent.tool.executed", {
                    "conversation_id": conversation_id,
                    "tool": tc.name,
                    "is_error": tool_result.is_error,
                    "iteration": iterations,
                })

                logger.info(
                    "agent.tool_executed",
                    tool=tc.name,
                    is_error=tool_result.is_error,
                    result_length=len(tool_result.content),
                )

        # Max iterations reached
        total_latency = int((time.monotonic() - start) * 1000)
        return AgentResponse(
            content="Task exceeded maximum iterations.",
            latency_ms=total_latency,
            iterations=iterations,
            tool_calls_made=all_tool_calls,
        )

    async def _execute_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a single tool call by name."""
        from src.tools.registry import ToolResult

        if not self.tool_registry:
            return ToolResult(content="No tools available", is_error=True)

        tool = self.tool_registry.get(name)
        if not tool:
            return ToolResult(content=f"Unknown tool: {name}", is_error=True)

        try:
            return await tool.execute(arguments)
        except Exception as e:
            logger.exception("agent.tool_error", tool=name)
            return ToolResult(content=f"Tool error: {e}", is_error=True)
