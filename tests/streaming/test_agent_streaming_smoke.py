from __future__ import annotations

from typing import Any

from src.agent.agent import Agent
from src.core.config import AgentConfig
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

    async def model_round_chunks(
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

    async def model_round_chunks(
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
        yield StreamChunk(type="text", text="Tool result handled.")
        yield StreamChunk(
            type="done",
            usage=Usage(tokens_in=7, tokens_out=3),
            model="simple-model",
        )


class TimestampPrefixedGateway:
    async def model_round_chunks(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **_: Any,
    ):
        yield StreamChunk(type="text", text="[2026-05-11 19:50] ")
        yield StreamChunk(type="text", text="抱歉，你说过了。")
        yield StreamChunk(
            type="done",
            usage=Usage(tokens_in=12, tokens_out=8),
            model="fake-model",
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

    assert result.content == "Tool result handled."
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


async def test_run_removes_internal_timestamp_from_visible_reply() -> None:
    bus = FakeEventBus()
    agent = Agent(
        model_gateway=TimestampPrefixedGateway(),
        event_bus=bus,
        config=AgentConfig(max_iterations=3),
        tool_registry=None,
        conversation_manager=None,
    )

    result = await agent.run("hello world")

    assert result.content == "抱歉，你说过了。"


class FakeCostLimitedGateway:
    async def model_round_chunks(
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
