from __future__ import annotations

from typing import Any

from src.agent.agent import Agent
from src.core.config import AgentConfig
from src.infrastructure.model_gateway import StreamChunk, Usage


class FakeEventBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, event_name: str, data: dict[str, Any]) -> None:
        self.events.append((event_name, data))


class FakeStreamingGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[list[dict[str, Any]], list[dict[str, Any]] | None]] = []

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **_: Any,
    ):
        self.calls.append((messages, tools))
        yield StreamChunk(type="text", text="Hello")
        yield StreamChunk(type="text", text=" streaming")
        yield StreamChunk(
            type="done",
            usage=Usage(tokens_in=12, tokens_out=8),
            model="fake-model",
        )


async def test_run_stream_yields_text_then_done() -> None:
    gateway = FakeStreamingGateway()
    bus = FakeEventBus()
    agent = Agent(
        model_gateway=gateway,
        event_bus=bus,
        config=AgentConfig(max_iterations=3),
        tool_registry=None,
        conversation_manager=None,
    )

    chunks = [chunk async for chunk in agent.run_stream("hello world")]

    assert [chunk.type for chunk in chunks] == ["text", "text", "done"]
    assert "".join(chunk.text for chunk in chunks if chunk.type == "text") == "Hello streaming"
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.tokens_in == 12
    assert chunks[-1].model == "fake-model"
    assert "agent.think.start" in [name for name, _ in bus.events]
    assert "agent.think.complete" in [name for name, _ in bus.events]


async def test_run_consumes_stream_and_returns_aggregated_response() -> None:
    gateway = FakeStreamingGateway()
    bus = FakeEventBus()
    agent = Agent(
        model_gateway=gateway,
        event_bus=bus,
        config=AgentConfig(max_iterations=3),
        tool_registry=None,
        conversation_manager=None,
    )

    result = await agent.run("hello world")

    assert result.content == "Hello streaming"
    assert result.model == "fake-model"
    assert result.tokens_in == 12
    assert result.tokens_out == 8
