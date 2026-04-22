from __future__ import annotations

import asyncio
from typing import Any

from src.agent.agent import Agent
from src.core.config import AgentConfig
from src.infrastructure.model_gateway import StreamChunk, ToolCall, Usage


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


class FakeConversationManager:
    def __init__(self) -> None:
        self.end_started = asyncio.Event()
        self.release_end = asyncio.Event()
        self.end_calls: list[tuple[str, bool]] = []

    async def get_or_create_conversation(
        self,
        conversation_id: str,
        platform: str,
        user_id: str,
        token_budget: int,
    ) -> None:
        return None

    async def add_user_message(
        self,
        conversation_id: str,
        content: str,
    ) -> None:
        return None

    async def build_messages(
        self,
        conversation_id: str,
        system_prompt: str,
        user_input: str,
        user_id: str,
    ) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ]

    def get_task_state(self, conversation_id: str) -> None:
        return None

    async def add_assistant_message(self, conversation_id: str, **_: Any) -> None:
        return None

    async def maybe_compress(self, conversation_id: str) -> None:
        return None

    async def end_conversation(
        self,
        conversation_id: str,
        *,
        clear_working_memory: bool = True,
    ) -> None:
        self.end_started.set()
        await self.release_end.wait()
        self.end_calls.append((conversation_id, clear_working_memory))


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


async def test_run_returns_before_background_memory_finalize_completes() -> None:
    gateway = FakeStreamingGateway()
    bus = FakeEventBus()
    conversation_manager = FakeConversationManager()
    agent = Agent(
        model_gateway=gateway,
        event_bus=bus,
        config=AgentConfig(max_iterations=3),
        tool_registry=None,
        conversation_manager=conversation_manager,
    )

    result = await asyncio.wait_for(
        agent.run(
            "hello world",
            conversation_id="conv-1",
            platform="telegram",
        ),
        timeout=0.5,
    )

    assert result.content == "Hello streaming"

    await asyncio.sleep(0)
    assert conversation_manager.end_started.is_set()
    assert conversation_manager.end_calls == []

    background_task = agent._memory_finalize_tasks["conv-1"]
    conversation_manager.release_end.set()
    await asyncio.wait_for(background_task, timeout=0.5)

    assert conversation_manager.end_calls == [("conv-1", False)]


class FakeCostLimitedGateway:
    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **_: Any,
    ):
        yield StreamChunk(
            type="tool_call",
            tool_call=ToolCall(id="tc-1", name="web_search", arguments={"query": "hello"}),
        )
        yield StreamChunk(
            type="done",
            usage=Usage(tokens_in=12, tokens_out=8, cost_usd=0.25),
            model="fake-model",
        )


async def test_run_stops_before_tool_execution_when_cost_limit_is_reached() -> None:
    gateway = FakeCostLimitedGateway()
    bus = FakeEventBus()
    agent = Agent(
        model_gateway=gateway,
        event_bus=bus,
        config=AgentConfig(max_iterations=3, max_task_cost=0.20),
        tool_registry=None,
        conversation_manager=None,
    )

    result = await agent.run("hello world")

    assert "Task exceeded cost limit" in result.content
