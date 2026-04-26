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


def _event(
    *,
    tokens_in: int,
    tokens_out: int,
    cached_tokens: int | None,
) -> dict[str, Any]:
    return {
        "timestamp": "2026-04-25T00:00:00+00:00",
        "data": {
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cached_tokens": cached_tokens,
        },
    }
