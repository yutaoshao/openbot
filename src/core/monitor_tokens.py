"""Token and prompt-cache metric aggregation helpers."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

_CACHE_RATIO_PRECISION = 4


def aggregate_token_events(events: list[dict[str, Any]], period: str) -> dict[str, Any]:
    total_in = 0
    total_out = 0
    cached_total = 0
    cache_observed_total = 0
    daily: dict[str, dict[str, int]] = defaultdict(_token_bucket)
    by_route_tier: dict[str, dict[str, int]] = defaultdict(_token_bucket)

    for item in events:
        data = item.get("data") or {}
        tokens_in = int(data.get("tokens_in") or 0)
        tokens_out = int(data.get("tokens_out") or 0)
        total_in += tokens_in
        total_out += tokens_out
        day = _event_day(item.get("timestamp"))
        daily[day]["tokens_in"] += tokens_in
        daily[day]["tokens_out"] += tokens_out
        route_tier = data.get("route_tier")
        if isinstance(route_tier, str) and route_tier:
            by_route_tier[route_tier]["tokens_in"] += tokens_in
            by_route_tier[route_tier]["tokens_out"] += tokens_out
        cached_raw = data.get("cached_tokens")
        if cached_raw is not None:
            cached_tokens = _add_cache_observation(daily[day], tokens_in, cached_raw)
            cached_total += cached_tokens
            cache_observed_total += tokens_in
            if isinstance(route_tier, str) and route_tier:
                _add_cache_observation(by_route_tier[route_tier], tokens_in, cached_raw)

    return {
        "period": period,
        "tokens_in": total_in,
        "tokens_out": total_out,
        "cached_tokens": cached_total,
        "cache_observed_tokens_in": cache_observed_total,
        "cache_hit_ratio": _cache_hit_ratio(cached_total, cache_observed_total),
        "avg_tokens_in_per_request": (total_in / len(events)) if events else 0.0,
        "avg_tokens_out_per_request": (total_out / len(events)) if events else 0.0,
        "daily": _daily_token_rows(daily),
        "by_route_tier": _route_token_rows(by_route_tier),
    }


def _add_cache_observation(
    bucket: dict[str, int],
    tokens_in: int,
    cached_raw: Any,
) -> int:
    cached_tokens = int(cached_raw or 0)
    bucket["cached_tokens"] += cached_tokens
    bucket["cache_observed_tokens_in"] += tokens_in
    return cached_tokens


def _token_bucket() -> dict[str, int]:
    return {
        "tokens_in": 0,
        "tokens_out": 0,
        "cached_tokens": 0,
        "cache_observed_tokens_in": 0,
    }


def _event_day(timestamp: str | None) -> str:
    parsed = _parse_iso(timestamp)
    return parsed.date().isoformat() if parsed else "unknown"


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _cache_hit_ratio(cached_tokens: int, observed_tokens_in: int) -> float | None:
    if observed_tokens_in <= 0:
        return None
    return round(cached_tokens / observed_tokens_in, _CACHE_RATIO_PRECISION)


def _daily_token_rows(daily: dict[str, dict[str, int]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for date, value in sorted(daily.items(), key=lambda x: x[0]):
        rows.append(
            {
                "date": date,
                **value,
                "cache_hit_ratio": _cache_hit_ratio(
                    value["cached_tokens"],
                    value["cache_observed_tokens_in"],
                ),
            }
        )
    return rows


def _route_token_rows(by_route_tier: dict[str, dict[str, int]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for route_tier, value in sorted(by_route_tier.items(), key=lambda x: x[0]):
        rows.append(
            {
                "route_tier": route_tier,
                **value,
                "cache_hit_ratio": _cache_hit_ratio(
                    value["cached_tokens"],
                    value["cache_observed_tokens_in"],
                ),
            }
        )
    return rows
