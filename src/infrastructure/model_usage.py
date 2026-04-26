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
) -> dict[str, Any]:
    return {
        "provider": provider,
        "model": model,
        "tokens_in": usage.tokens_in,
        "tokens_out": usage.tokens_out,
        "cached_tokens": usage.cached_tokens,
        "cache_hit_ratio": usage.cache_hit_ratio,
        "cost_usd": usage.cost_usd,
        "latency_ms": latency_ms,
    }


def llm_completed_fields(
    *,
    provider: str,
    model: str,
    usage: Usage,
    latency_ms: int,
) -> dict[str, Any]:
    return {
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
