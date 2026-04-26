from __future__ import annotations

from typing import Any

from src.core.config import ModelConfig, ModelProviderConfig
from src.infrastructure.model_gateway import ModelGateway, ModelResponse, Usage


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
