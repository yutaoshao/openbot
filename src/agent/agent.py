"""Agent core - ReAct reasoning loop.

Implements the Think -> Decide -> Act -> Observe cycle.
Phase 1: single-turn text response (no tools, no memory).
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

logger = get_logger(__name__)

DEFAULT_SYSTEM_PROMPT = """You are OpenBot, a helpful personal AI assistant.

Current date: {date}

Guidelines:
- Be concise and accurate
- If you don't know something, say so honestly
- Respond in the same language as the user's message
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
    ) -> None:
        self.model_gateway = model_gateway
        self.event_bus = event_bus
        self.config = config
        self.max_iterations = config.max_iterations

    def _build_system_prompt(self) -> str:
        """Build system prompt with current context."""
        template = self.config.system_prompt or DEFAULT_SYSTEM_PROMPT
        return template.format(
            date=datetime.now(UTC).strftime("%Y-%m-%d"),
        )

    async def run(self, input_text: str, conversation_id: str = "") -> AgentResponse:
        """Execute the agent loop for a user input.

        Phase 1: single-turn, no tools, no memory.
        Phase 2 will extend this with tool calling loop.
        """
        start = time.monotonic()

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user", "content": input_text},
        ]

        await self.event_bus.publish("agent.think.start", {
            "conversation_id": conversation_id,
            "input_length": len(input_text),
        })

        iterations = 0

        while iterations < self.max_iterations:
            iterations += 1

            response = await self.model_gateway.chat(messages=messages)

            # Phase 1: no tool support, just return text
            # Phase 2 will add: if response.has_tool_calls -> execute -> continue loop
            if not response.has_tool_calls:
                total_latency = int((time.monotonic() - start) * 1000)

                result = AgentResponse(
                    content=response.text,
                    model=response.model,
                    tokens_in=response.usage.tokens_in,
                    tokens_out=response.usage.tokens_out,
                    cost=response.usage.cost,
                    latency_ms=total_latency,
                    iterations=iterations,
                )

                await self.event_bus.publish("agent.think.complete", {
                    "conversation_id": conversation_id,
                    "iterations": iterations,
                    "latency_ms": total_latency,
                    "tokens_in": response.usage.tokens_in,
                    "tokens_out": response.usage.tokens_out,
                    "cost": response.usage.cost,
                })

                return result

            # Tool calling will be handled in Phase 2
            break

        total_latency = int((time.monotonic() - start) * 1000)
        return AgentResponse(
            content="Task exceeded maximum iterations.",
            latency_ms=total_latency,
            iterations=iterations,
        )
