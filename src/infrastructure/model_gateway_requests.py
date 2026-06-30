"""Retry and fallback request loops for the model gateway."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.core.logging import get_logger
from src.infrastructure.model_round_chunks import (
    model_round_chunks_for_provider,
    streaming_chunks_for_provider,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from src.core.config import ModelConfig
    from src.core.model_config import RouteTier
    from src.infrastructure.model_provider_selector import ProviderAttempt
    from src.infrastructure.model_types import ModelProvider, ModelResponse, StreamChunk

logger = get_logger(__name__)


@dataclass(frozen=True)
class GatewayRequestContext:
    config: ModelConfig
    attempts: Callable[..., list[ProviderAttempt]]
    providers: dict[str, ModelProvider]
    record_completion: Callable[..., Awaitable[None]]
    handle_retry: Callable[..., Awaitable[None]]


async def run_chat_request(
    *,
    context: GatewayRequestContext,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    call_kwargs: dict[str, Any],
    route_tier: RouteTier | None,
    route_reason: str | None,
) -> ModelResponse:
    last_error: Exception | None = None
    for provider_attempt in context.attempts(
        route_tier=route_tier,
        route_reason=route_reason,
    ):
        provider = context.providers[provider_attempt.key]
        for attempt in range(context.config.max_retries):
            try:
                response = await provider.chat(messages, tools, **call_kwargs)
                await context.record_completion(
                    provider_attempt,
                    model=response.model,
                    usage=response.usage,
                    latency_ms=response.latency_ms,
                )
                return response
            except Exception as error:
                last_error = error
                await context.handle_retry(provider_attempt.key, attempt, error, "retry")

        _log_exhausted(provider_attempt.key, "exhausted")
    raise RuntimeError(f"All model providers failed: {last_error}") from last_error


async def run_model_round_request(
    *,
    context: GatewayRequestContext,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    call_kwargs: dict[str, Any],
    route_tier: RouteTier | None,
    route_reason: str | None,
) -> AsyncIterator[StreamChunk]:
    last_error: Exception | None = None
    for provider_attempt in context.attempts(
        route_tier=route_tier,
        route_reason=route_reason,
    ):
        provider = context.providers[provider_attempt.key]
        for attempt in range(context.config.max_retries):
            try:
                async for chunk in model_round_chunks_for_provider(
                    provider_attempt=provider_attempt,
                    provider=provider,
                    messages=messages,
                    tools=tools,
                    call_kwargs=call_kwargs,
                    record_completion=context.record_completion,
                ):
                    yield chunk
                return
            except Exception as error:
                last_error = error
                await context.handle_retry(
                    provider_attempt.key,
                    attempt,
                    error,
                    _retry_status(provider),
                )

        _log_exhausted(provider_attempt.key, _exhausted_status(provider))

    raise RuntimeError(
        f"All model providers failed (round): {last_error}",
    ) from last_error


async def run_stream_request(
    *,
    context: GatewayRequestContext,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    call_kwargs: dict[str, Any],
    route_tier: RouteTier | None,
    route_reason: str | None,
) -> AsyncIterator[StreamChunk]:
    last_error: Exception | None = None
    for provider_attempt in context.attempts(
        route_tier=route_tier,
        route_reason=route_reason,
    ):
        provider = context.providers[provider_attempt.key]
        for attempt in range(context.config.max_retries):
            try:
                async for chunk in streaming_chunks_for_provider(
                    provider_attempt=provider_attempt,
                    provider=provider,
                    messages=messages,
                    tools=tools,
                    call_kwargs=call_kwargs,
                    record_completion=context.record_completion,
                ):
                    yield chunk
                return
            except Exception as error:
                last_error = error
                await context.handle_retry(
                    provider_attempt.key,
                    attempt,
                    error,
                    "stream_retry",
                )

        _log_exhausted(provider_attempt.key, "stream_exhausted")

    raise RuntimeError(
        f"All model providers failed (stream): {last_error}",
    ) from last_error


def _retry_status(provider: ModelProvider) -> str:
    return "stream_retry" if provider.supports_streaming else "retry"


def _exhausted_status(provider: ModelProvider) -> str:
    return "stream_exhausted" if provider.supports_streaming else "exhausted"


def _log_exhausted(provider_key: str, status: str) -> None:
    logger.error(
        "llm_requested",
        surface="operational",
        status=status,
        provider=provider_key,
    )
