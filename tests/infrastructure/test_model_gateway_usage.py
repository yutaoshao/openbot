from __future__ import annotations

from typing import Any

import pytest

from src.core.config import AgentConfig, ModelConfig, ModelProviderConfig
from src.infrastructure.model_gateway import (
    ModelGateway,
    ModelResponse,
    StreamChunk,
    ToolCall,
    Usage,
)
from src.memory.request_budget import InputCount


class _FakeEventBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, event_name: str, data: dict[str, Any]) -> None:
        self.published.append((event_name, data))


class _FakeProvider:
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        return ModelResponse(
            text="ok",
            usage=Usage(tokens_in=100, tokens_out=20, cached_tokens=75),
            model="fake-model",
            latency_ms=12,
        )


def _build_gateway(event_bus: _FakeEventBus) -> ModelGateway:
    gateway = ModelGateway.__new__(ModelGateway)
    gateway.config = ModelConfig(
        primary=ModelProviderConfig(
            provider="openai_compatible",
            model="fake-model",
            pricing_input=1.0,
            pricing_output=2.0,
        ),
        max_retries=1,
    )
    gateway.event_bus = event_bus
    gateway._providers = {"primary": _FakeProvider()}
    return gateway


async def test_unverified_provider_rejects_input_above_safe_limit(monkeypatch: Any) -> None:
    gateway = _build_gateway(_FakeEventBus())
    gateway._agent_config = AgentConfig()
    monkeypatch.setattr(
        "src.infrastructure.model_gateway.estimate_input_tokens",
        lambda messages, tools: InputCount(tokens=125_000, exact=False),
    )
    with pytest.raises(ValueError, match="model context window not configured"):
        await gateway.chat(messages=[{"role": "user", "content": "large request"}])


async def test_chat_publishes_prompt_cache_metrics() -> None:
    event_bus = _FakeEventBus()
    gateway = _build_gateway(event_bus)

    response = await gateway.chat(messages=[])

    assert response.usage.cost_usd == 0.00014
    assert event_bus.published == [
        (
            "model.request",
            {
                "provider": "primary",
                "model": "fake-model",
                "tokens_in": 100,
                "tokens_out": 20,
                "cached_tokens": 75,
                "cache_hit_ratio": 0.75,
                "cost_usd": 0.00014,
                "latency_ms": 12,
            },
        )
    ]


async def test_chat_uses_requested_route_tier_and_publishes_route_metrics(
    monkeypatch: Any,
) -> None:
    providers = {
        "primary-model": _RecordingProvider("primary-model"),
        "simple-model": _RecordingProvider("simple-model"),
        "complex-model": _RecordingProvider("complex-model"),
    }
    monkeypatch.setattr(
        ModelGateway,
        "_create_provider",
        staticmethod(lambda config: providers[config.model]),
    )
    event_bus = _FakeEventBus()
    gateway = ModelGateway(_routing_config(), event_bus)

    response = await gateway.chat(
        messages=[{"role": "user", "content": "hi"}],
        route_tier="simple",
        route_reason="short_prompt",
    )

    assert response.model == "simple-model"
    assert providers["simple-model"].calls == 1
    assert providers["complex-model"].calls == 0
    assert response.usage.cost_usd == 0.00014
    assert event_bus.published[-1] == (
        "model.request",
        {
            "provider": "route:simple",
            "model": "simple-model",
            "tokens_in": 100,
            "tokens_out": 20,
            "cached_tokens": None,
            "cache_hit_ratio": None,
            "cost_usd": 0.00014,
            "latency_ms": 12,
            "route_tier": "simple",
            "route_reason": "short_prompt",
        },
    )


async def test_chat_stream_records_route_usage_on_done(monkeypatch: Any) -> None:
    providers = {
        "primary-model": _StreamingProvider("primary-model"),
        "simple-model": _StreamingProvider("simple-model"),
        "complex-model": _StreamingProvider("complex-model"),
    }
    monkeypatch.setattr(
        ModelGateway,
        "_create_provider",
        staticmethod(lambda config: providers[config.model]),
    )
    event_bus = _FakeEventBus()
    gateway = ModelGateway(_routing_config(), event_bus)

    chunks = [
        chunk
        async for chunk in gateway.chat_stream(
            messages=[{"role": "user", "content": "hi"}],
            route_tier="simple",
            route_reason="simple_keyword",
        )
    ]

    assert [chunk.type for chunk in chunks] == ["text", "done"]
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.cost_usd == 0.00014
    assert chunks[-1].model == "simple-model"
    assert event_bus.published[-1][1]["provider"] == "route:simple"
    assert event_bus.published[-1][1]["route_tier"] == "simple"
    assert event_bus.published[-1][1]["route_reason"] == "simple_keyword"


async def test_model_round_chunks_use_chat_when_provider_cannot_stream(monkeypatch: Any) -> None:
    providers = {
        "primary-model": _NonStreamingProvider("primary-model"),
        "simple-model": _NonStreamingProvider("simple-model"),
        "complex-model": _NonStreamingProvider("complex-model"),
    }
    monkeypatch.setattr(
        ModelGateway,
        "_create_provider",
        staticmethod(lambda config: providers[config.model]),
    )
    event_bus = _FakeEventBus()
    gateway = ModelGateway(_routing_config(), event_bus)

    chunks = [
        chunk
        async for chunk in gateway.model_round_chunks(
            messages=[{"role": "user", "content": "hi"}],
            route_tier="simple",
            route_reason="simple_keyword",
        )
    ]

    assert [chunk.type for chunk in chunks] == ["text", "tool_call", "done"]
    assert chunks[0].text == "ok"
    assert chunks[1].tool_call is not None
    assert chunks[1].tool_call.name == "echo_tool"
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.cost_usd == 0.00014
    assert chunks[-1].model == "simple-model"
    assert providers["simple-model"].chat_calls == 1
    assert event_bus.published[-1][1]["provider"] == "route:simple"
    assert event_bus.published[-1][1]["route_tier"] == "simple"
    assert event_bus.published[-1][1]["route_reason"] == "simple_keyword"


class _RecordingProvider:
    def __init__(self, model: str) -> None:
        self.model = model
        self.calls = 0

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        self.calls += 1
        return ModelResponse(
            text="ok",
            usage=Usage(tokens_in=100, tokens_out=20),
            model=self.model,
            latency_ms=12,
        )

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ):
        raise AssertionError("chat_stream should not be called")


class _NonStreamingProvider:
    supports_streaming = False

    def __init__(self, model: str) -> None:
        self.model = model
        self.chat_calls = 0

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        self.chat_calls += 1
        return ModelResponse(
            text="ok",
            tool_calls=[ToolCall(id="tc-1", name="echo_tool", arguments={"value": "hi"})],
            usage=Usage(tokens_in=100, tokens_out=20),
            model=self.model,
            latency_ms=12,
        )

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ):
        raise AssertionError("chat_stream should not be called")


class _StreamingProvider:
    def __init__(self, model: str) -> None:
        self.model = model

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        raise AssertionError("chat should not be called")

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ):
        yield StreamChunk(type="text", text="ok")
        yield StreamChunk(
            type="done",
            usage=Usage(tokens_in=100, tokens_out=20),
            model=self.model,
        )


def _routing_config() -> ModelConfig:
    return ModelConfig(
        primary=ModelProviderConfig(
            provider="openai_compatible",
            model="primary-model",
        ),
        routing={
            "enabled": True,
            "default_tier": "complex",
            "tiers": {
                "simple": {
                    "provider": "openai_compatible",
                    "model": "simple-model",
                    "pricing_input": 1.0,
                    "pricing_output": 2.0,
                },
                "complex": {
                    "provider": "openai_compatible",
                    "model": "complex-model",
                    "pricing_input": 10.0,
                    "pricing_output": 20.0,
                },
            },
        },
        max_retries=1,
    )


@pytest.mark.parametrize("exact", [False, True])
async def test_configured_window_allows_large_input_without_requiring_exact_count(
    monkeypatch, exact
):
    gateway = _build_gateway(_FakeEventBus())
    gateway._agent_config = AgentConfig()
    gateway.config.primary.context_window = 272_000
    gateway.config.primary.max_tokens = 16_384
    if exact:

        async def count(*args):
            return 200_000

        gateway._providers["primary"].count_input_tokens = count
    monkeypatch.setattr(
        "src.infrastructure.model_gateway.estimate_input_tokens",
        lambda messages, tools: InputCount(tokens=200_000, exact=False),
    )
    counted = await gateway.count_input([{"role": "user", "content": "large"}])
    assert counted.model_window == 272_000
    assert counted.output_budget == 16_384
    assert counted.exact is exact
    assert (await gateway.chat(messages=[{"role": "user", "content": "large"}])).text == "ok"


async def test_configured_window_still_enforces_input_and_output_limits(monkeypatch):
    gateway = _build_gateway(_FakeEventBus())
    gateway._agent_config = AgentConfig(input_token_budget=272_000)
    gateway.config.primary.context_window = 272_000
    gateway.config.primary.max_tokens = 16_384
    monkeypatch.setattr(
        "src.infrastructure.model_gateway.estimate_input_tokens",
        lambda messages, tools: InputCount(tokens=252_000, exact=False),
    )
    with pytest.raises(ValueError, match="256096 > 255616"):
        await gateway.chat(messages=[{"role": "user", "content": "too large"}])
    monkeypatch.setattr(
        "src.infrastructure.model_gateway.estimate_input_tokens",
        lambda messages, tools: InputCount(tokens=240_000, exact=False),
    )
    with pytest.raises(ValueError, match="244096 > 240000"):
        await gateway.chat(
            messages=[{"role": "user", "content": "larger output"}], max_tokens=32_000
        )
