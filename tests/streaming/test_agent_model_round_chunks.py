from __future__ import annotations

from typing import Any

from src.agent.agent import Agent
from src.core.config import AgentConfig
from src.infrastructure.model_gateway import StreamChunk, Usage


class FakeEventBus:
    async def publish(self, event_name: str, data: dict[str, Any]) -> None:
        return None


class FakeModelRoundGateway:
    async def model_round_chunks(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **_: Any,
    ):
        yield StreamChunk(type="text", text="Hello from round chunks")
        yield StreamChunk(
            type="done",
            usage=Usage(tokens_in=12, tokens_out=8),
            model="fake-model",
        )

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **_: Any,
    ):
        raise AssertionError("runtime should consume model_round_chunks")


async def test_run_consumes_model_round_chunks() -> None:
    agent = Agent(
        model_gateway=FakeModelRoundGateway(),
        event_bus=FakeEventBus(),
        config=AgentConfig(max_iterations=3),
        tool_registry=None,
        conversation_manager=None,
    )

    result = await agent.run("hello world")

    assert result.content == "Hello from round chunks"
    assert result.model == "fake-model"
    assert result.tokens_in == 12
    assert result.tokens_out == 8
