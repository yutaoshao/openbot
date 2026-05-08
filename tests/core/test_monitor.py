from __future__ import annotations

from typing import Any

from src.core.monitor import MetricsCollector


class _FakeMetricsRepo:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events

    async def query(
        self,
        *,
        event_name: str | None = None,
        start: str | None = None,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        return self._events[:limit]


class _FakeStorage:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.metrics = _FakeMetricsRepo(events)


class _FakeEventBus:
    def subscribe(self, pattern: str, handler: object) -> None:
        return None


async def test_tokens_metrics_include_prompt_cache_ratio() -> None:
    collector = MetricsCollector(
        _FakeStorage(
            [
                _event(tokens_in=100, tokens_out=20, cached_tokens=50),
                _event(tokens_in=50, tokens_out=10, cached_tokens=None),
                _event(tokens_in=100, tokens_out=5, cached_tokens=25),
            ]
        ),
        _FakeEventBus(),
    )

    result = await collector.get_tokens(period="7d")

    assert result["tokens_in"] == 250
    assert result["tokens_out"] == 35
    assert result["cached_tokens"] == 75
    assert result["cache_observed_tokens_in"] == 200
    assert result["cache_hit_ratio"] == 0.375
    assert result["daily"] == [
        {
            "date": "2026-04-25",
            "tokens_in": 250,
            "tokens_out": 35,
            "cached_tokens": 75,
            "cache_observed_tokens_in": 200,
            "cache_hit_ratio": 0.375,
        }
    ]


async def test_tokens_metrics_group_by_route_tier() -> None:
    collector = MetricsCollector(
        _FakeStorage(
            [
                _event(
                    tokens_in=100,
                    tokens_out=20,
                    cached_tokens=50,
                    route_tier="simple",
                ),
                _event(
                    tokens_in=80,
                    tokens_out=40,
                    cached_tokens=None,
                    route_tier="complex",
                ),
            ]
        ),
        _FakeEventBus(),
    )

    result = await collector.get_tokens(period="7d")

    assert result["by_route_tier"] == [
        {
            "route_tier": "complex",
            "tokens_in": 80,
            "tokens_out": 40,
            "cached_tokens": 0,
            "cache_observed_tokens_in": 0,
            "cache_hit_ratio": None,
        },
        {
            "route_tier": "simple",
            "tokens_in": 100,
            "tokens_out": 20,
            "cached_tokens": 50,
            "cache_observed_tokens_in": 100,
            "cache_hit_ratio": 0.5,
        },
    ]


async def test_cost_metrics_group_by_route_tier() -> None:
    collector = MetricsCollector(
        _FakeStorage(
            [
                _cost_event(cost_usd=0.1, route_tier="simple"),
                _cost_event(cost_usd=0.3, route_tier="complex"),
                _cost_event(cost_usd=0.2, route_tier="simple"),
            ]
        ),
        _FakeEventBus(),
    )

    result = await collector.get_cost(period="7d")

    assert result["by_route_tier"] == [
        {"route_tier": "complex", "cost_usd": 0.3},
        {"route_tier": "simple", "cost_usd": 0.3},
    ]


def _event(
    *,
    tokens_in: int,
    tokens_out: int,
    cached_tokens: int | None,
    route_tier: str | None = None,
) -> dict[str, Any]:
    data = {
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cached_tokens": cached_tokens,
    }
    if route_tier is not None:
        data["route_tier"] = route_tier
    return {
        "timestamp": "2026-04-25T00:00:00+00:00",
        "data": data,
    }


def _cost_event(*, cost_usd: float, route_tier: str) -> dict[str, Any]:
    return {
        "timestamp": "2026-04-25T00:00:00+00:00",
        "data": {
            "cost_usd": cost_usd,
            "route_tier": route_tier,
        },
    }
