"""Helpers for model usage logging and event payloads."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.infrastructure.model_types import Usage


def model_request_payload(
    *,
    provider: str,
    model: str,
    usage: Usage,
    latency_ms: int,
    route_tier: str | None = None,
    route_reason: str | None = None,
) -> dict[str, Any]:
    payload = {
        "provider": provider,
        "model": model,
        "tokens_in": usage.tokens_in,
        "tokens_out": usage.tokens_out,
        "cached_tokens": usage.cached_tokens,
        "cache_hit_ratio": usage.cache_hit_ratio,
        "cost_usd": usage.cost_usd,
        "latency_ms": latency_ms,
    }
    if route_tier is not None:
        payload["route_tier"] = route_tier
    if route_reason is not None:
        payload["route_reason"] = route_reason
    return payload


def llm_completed_fields(
    *,
    provider: str,
    model: str,
    usage: Usage,
    latency_ms: int,
    route_tier: str | None = None,
    route_reason: str | None = None,
) -> dict[str, Any]:
    fields = {
        "surface": "operational",
        "provider": provider,
        "model": model,
        "token_in": usage.tokens_in,
        "token_out": usage.tokens_out,
        "cached_tokens": usage.cached_tokens,
        "cache_hit_ratio": usage.cache_hit_ratio,
        "cost_usd": usage.cost_usd,
        "latency_ms": latency_ms,
    }
    if route_tier is not None:
        fields["route_tier"] = route_tier
    if route_reason is not None:
        fields["route_reason"] = route_reason
    return fields
