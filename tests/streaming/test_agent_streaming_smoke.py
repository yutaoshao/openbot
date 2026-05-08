from __future__ import annotations

import asyncio
from typing import Any

from src.agent.agent import Agent
from src.core.config import AgentConfig
from src.core.trace import current_trace, trace_scope
from src.infrastructure.model_gateway import StreamChunk, ToolCall, Usage
from src.infrastructure.model_routing import RouteDecision, RouteRequest
from src.tools.registry import CORE_VISIBILITY, ToolRegistry, ToolResult


class FakeEventBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, event_name: str, data: dict[str, Any]) -> None:
        self.events.append((event_name, data))


class FakeStreamingGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[list[dict[str, Any]], list[dict[str, Any]] | None]] = []
        self.trace_ids: list[str] = []

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **_: Any,
    ):
        self.calls.append((messages, tools))
        trace = current_trace()
        self.trace_ids.append(trace.trace_id if trace else "")
        yield StreamChunk(type="text", text="Hello")
        yield StreamChunk(type="text", text=" streaming")
        yield StreamChunk(
            type="done",
            usage=Usage(tokens_in=12, tokens_out=8),
            model="fake-model",
        )


class FakeRoutingGateway:
    def __init__(self) -> None:
        self.route_requests: list[RouteRequest] = []
        self.route_kwargs: list[dict[str, Any]] = []

    def decide_route(self, request: RouteRequest) -> RouteDecision:
        self.route_requests.append(request)
        return RouteDecision(
            tier="simple",
            reason="short_prompt",
            matched_rules=("short_prompt",),
        )

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ):
        self.route_kwargs.append(kwargs)
        if len(self.route_kwargs) == 1:
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
                model="simple-model",
            )
            return
        yield StreamChunk(type="text", text="done")
        yield StreamChunk(
            type="done",
            usage=Usage(tokens_in=7, tokens_out=3),
            model="simple-model",
        )


class EchoTool:
    @property
    def name(self) -> str:
        return "echo_tool"

    @property
    def description(self) -> str:
        return "Echo a value"

    @property
    def parameters(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"value": {"type": "string"}},
        }

    @property
    def category(self) -> str:
        return "test"

    async def execute(self, args: dict[str, object]) -> ToolResult:
        return ToolResult(content=str(args.get("value", "")))


class FakeConversationManager:
    def __init__(self) -> None:
        self.compress_started = asyncio.Event()
        self.release_background = asyncio.Event()
        self.compress_calls: list[str] = []
        self.sync_calls: list[str] = []
        self.sync_trace_ids: list[str] = []
        self.sync_interaction_ids: list[str] = []
        self.sync_triggers: list[str] = []

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
        self.compress_started.set()
        await self.release_background.wait()
        self.compress_calls.append(conversation_id)

    async def sync_memory_after_turn(
        self,
        conversation_id: str,
    ) -> None:
        trace = current_trace()
        self.sync_calls.append(conversation_id)
        self.sync_trace_ids.append(trace.trace_id if trace else "")
        self.sync_interaction_ids.append(trace.interaction_id if trace else "")
        self.sync_triggers.append(trace.extra.get("trigger", "") if trace else "")

    async def end_conversation(
        self,
        conversation_id: str,
        *,
        clear_working_memory: bool = True,
    ) -> None:
        raise AssertionError("end_conversation should not be used for post-reply sync")


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


async def test_run_reuses_one_route_decision_across_model_rounds() -> None:
    gateway = FakeRoutingGateway()
    bus = FakeEventBus()
    registry = ToolRegistry()
    registry.register(EchoTool(), visibility=CORE_VISIBILITY)
    agent = Agent(
        model_gateway=gateway,
        event_bus=bus,
        config=AgentConfig(max_iterations=3),
        tool_registry=registry,
        conversation_manager=None,
    )

    result = await agent.run("hello world")

    assert result.content == "done"
    assert len(gateway.route_requests) == 1
    assert gateway.route_requests[0].input_text == "hello world"
    assert [call["route_tier"] for call in gateway.route_kwargs] == ["simple", "simple"]
    assert [call["route_reason"] for call in gateway.route_kwargs] == [
        "short_prompt",
        "short_prompt",
    ]


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
    assert conversation_manager.compress_started.is_set()
    assert conversation_manager.compress_calls == []
    assert conversation_manager.sync_calls == []

    background_task = agent._memory_finalize_tasks["conv-1"]
    conversation_manager.release_background.set()
    await asyncio.wait_for(background_task, timeout=0.5)

    assert conversation_manager.compress_calls == ["conv-1"]
    assert conversation_manager.sync_calls == ["conv-1"]


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


async def test_run_reuses_active_trace_context() -> None:
    gateway = FakeStreamingGateway()
    bus = FakeEventBus()
    agent = Agent(
        model_gateway=gateway,
        event_bus=bus,
        config=AgentConfig(max_iterations=3),
        tool_registry=None,
        conversation_manager=None,
    )

    with trace_scope(interaction_id="conv-1", platform="wechat") as trace:
        result = await agent.run("hello world", conversation_id="conv-1", platform="wechat")

    assert result.content == "Hello streaming"
    assert gateway.trace_ids == [trace.trace_id]


async def test_background_memory_sync_uses_child_trace_context() -> None:
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

    with trace_scope(interaction_id="conv-1", platform="wechat") as trace:
        result = await agent.run("hello world", conversation_id="conv-1", platform="wechat")

    assert result.content == "Hello streaming"
    background_task = agent._memory_finalize_tasks["conv-1"]
    conversation_manager.release_background.set()
    await asyncio.wait_for(background_task, timeout=0.5)

    assert len(conversation_manager.sync_trace_ids) == 1
    assert conversation_manager.sync_trace_ids[0] != trace.trace_id
    assert conversation_manager.sync_interaction_ids == ["conv-1"]
    assert conversation_manager.sync_triggers == ["post_reply_sync"]
