from __future__ import annotations

from typing import Any

from src.agent.agent import Agent
from src.core.config import AgentConfig
from src.infrastructure.model_gateway import StreamChunk, ToolCall, Usage
from src.tools.registry import CORE_VISIBILITY, ToolRegistry, ToolResult


class FakeEventBus:
    async def publish(self, event_name: str, data: dict[str, Any]) -> None:
        return None


class EchoTool:
    @property
    def name(self) -> str:
        return "echo_tool"

    @property
    def description(self) -> str:
        return "Echo a value"

    @property
    def parameters(self) -> dict[str, object]:
        return {"type": "object", "properties": {"value": {"type": "string"}}}

    @property
    def category(self) -> str:
        return "test"

    async def execute(self, args: dict[str, object]) -> ToolResult:
        return ToolResult(content=str(args.get("value", "")))


class ReasoningGateway:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, Any]]] = []

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ):
        self.calls.append(messages)
        if len(self.calls) == 1:
            yield StreamChunk(
                type="tool_call",
                tool_call=ToolCall(
                    id="tc-1",
                    name="echo_tool",
                    arguments={"value": "hello"},
                ),
            )
            yield StreamChunk(
                type="done",
                usage=Usage(tokens_in=10, tokens_out=4),
                model="mimo-v2.5",
                reasoning_content="I should echo the value.",
            )
            return
        yield StreamChunk(type="text", text="The echo tool returned hello.")
        yield StreamChunk(
            type="done",
            usage=Usage(tokens_in=7, tokens_out=2),
            model="mimo-v2.5",
        )


async def test_agent_preserves_reasoning_content_on_tool_call_messages() -> None:
    gateway = ReasoningGateway()
    registry = ToolRegistry()
    registry.register(EchoTool(), visibility=CORE_VISIBILITY)
    agent = Agent(
        model_gateway=gateway,
        event_bus=FakeEventBus(),
        config=AgentConfig(max_iterations=3),
        tool_registry=registry,
        conversation_manager=None,
    )

    result = await agent.run("echo hello")

    assert result.content == "The echo tool returned hello."
    assistant_messages = [msg for msg in gateway.calls[1] if msg["role"] == "assistant"]
    assert assistant_messages[-1]["reasoning_content"] == "I should echo the value."
