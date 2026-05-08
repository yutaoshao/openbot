"""Multi-provider LLM gateway with fallback and retry support.

Abstracts away provider differences behind a unified interface.
Provider implementations live in src/infrastructure/providers/.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from src.core.logging import get_logger
from src.infrastructure.model_provider_selector import ModelProviderSelector, ProviderAttempt
from src.infrastructure.model_routing import ModelRouter
from src.infrastructure.model_types import (
    ModelProvider,
    ModelResponse,
    StreamChunk,
    ToolCall,
    Usage,
)
from src.infrastructure.model_usage import llm_completed_fields, model_request_payload

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from src.core.config import ModelConfig, ModelProviderConfig
    from src.core.model_config import RouteTier
    from src.infrastructure.event_bus import EventBus
    from src.infrastructure.model_routing import RouteDecision, RouteRequest

logger = get_logger(__name__)

__all__ = ["ModelGateway", "ModelProvider", "ModelResponse", "StreamChunk", "ToolCall", "Usage"]


class ModelGateway:
    """Unified gateway that routes requests, handles retries and fallback."""

    def __init__(self, config: ModelConfig, event_bus: EventBus) -> None:
        self.config = config
        self.event_bus = event_bus
        self._selector = ModelProviderSelector(config)
        self._router = ModelRouter(config.routing)
        self._providers = {
            key: self._create_provider(provider_config)
            for key, provider_config in self._selector.provider_configs().items()
        }

        logger.info(
            "model_gateway.init",
            primary=config.primary.model,
            fallback=config.fallback.model if config.fallback else None,
            routing_enabled=config.routing.enabled,
        )

    def calculate_usage_cost(self, provider_key: str, usage: Usage) -> float:
        """Compute request cost from configured per-million-token pricing."""
        provider_config = self._provider_config(provider_key)
        if provider_config is None:
            return 0.0
        pricing_input = provider_config.pricing_input
        pricing_output = provider_config.pricing_output
        if pricing_input is None or pricing_output is None:
            return 0.0
        total_cost = (
            usage.tokens_in * pricing_input + usage.tokens_out * pricing_output
        ) / 1_000_000
        return round(total_cost, 8)

    def _provider_config(self, provider_key: str) -> ModelProviderConfig | None:
        return self._provider_selector().provider_config(provider_key)

    def _provider_selector(self) -> ModelProviderSelector:
        selector = getattr(self, "_selector", None)
        if selector is None:
            selector = ModelProviderSelector(self.config)
            self._selector = selector
        return selector

    def decide_route(self, request: RouteRequest) -> RouteDecision | None:
        """Return a route decision only when routing is enabled."""
        if not self.config.routing.enabled:
            return None
        router = getattr(self, "_router", None)
        if router is None:
            router = ModelRouter(self.config.routing)
            self._router = router
        return router.decide(request)

    @staticmethod
    def _create_provider(config: ModelProviderConfig) -> ModelProvider:
        """Factory: create provider by config.provider field."""
        from src.infrastructure.providers.anthropic import ClaudeProvider
        from src.infrastructure.providers.openai_compat import OpenAICompatibleProvider

        if config.provider == "anthropic":
            return ClaudeProvider(config)
        if config.provider == "openai_compatible":
            return OpenAICompatibleProvider(config)
        raise ValueError(
            f"Unsupported provider: '{config.provider}'. Supported: anthropic, openai_compatible"
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Send chat request with retry and fallback."""
        call_kwargs, route_tier, route_reason = _request_options(kwargs)
        last_error: Exception | None = None

        for provider_attempt in self._provider_selector().attempts(
            route_tier=route_tier,
            route_reason=route_reason,
        ):
            provider = self._providers[provider_attempt.key]
            for attempt in range(self.config.max_retries):
                try:
                    response = await provider.chat(messages, tools, **call_kwargs)
                    await self._record_completion(
                        provider_attempt,
                        model=response.model,
                        usage=response.usage,
                        latency_ms=response.latency_ms,
                    )
                    return response

                except Exception as e:
                    last_error = e
                    await self._handle_retry(provider_attempt.key, attempt, e, "retry")

            logger.error(
                "llm_requested",
                surface="operational",
                status="exhausted",
                provider=provider_attempt.key,
            )

        raise RuntimeError(f"All model providers failed: {last_error}") from last_error

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Send streaming chat request with retry and fallback.

        Retry/fallback applies only at connection phase.  Once streaming
        begins, errors propagate to the caller (no mid-stream retry).
        """
        call_kwargs, route_tier, route_reason = _request_options(kwargs)
        last_error: Exception | None = None

        for provider_attempt in self._provider_selector().attempts(
            route_tier=route_tier,
            route_reason=route_reason,
        ):
            provider = self._providers[provider_attempt.key]
            for attempt in range(self.config.max_retries):
                try:
                    async for chunk in self._stream_provider(
                        provider_attempt,
                        provider,
                        messages,
                        tools,
                        call_kwargs,
                    ):
                        yield chunk
                    return  # noqa: B012 — stream consumed, done

                except Exception as e:
                    last_error = e
                    await self._handle_retry(
                        provider_attempt.key,
                        attempt,
                        e,
                        "stream_retry",
                    )

            logger.error(
                "llm_requested",
                surface="operational",
                status="stream_exhausted",
                provider=provider_attempt.key,
            )

        raise RuntimeError(
            f"All model providers failed (stream): {last_error}",
        ) from last_error

    async def _stream_provider(
        self,
        provider_attempt: ProviderAttempt,
        provider: ModelProvider,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        call_kwargs: dict[str, Any],
    ) -> AsyncIterator[StreamChunk]:
        stream = provider.chat_stream(messages, tools, **call_kwargs)
        first = True
        stream_start = time.monotonic()
        async for chunk in stream:
            if first:
                first = False
                logger.info(
                    "llm_requested",
                    surface="operational",
                    status="streaming",
                    provider=provider_attempt.key,
                )
            if chunk.type == "done" and chunk.usage is not None:
                latency_ms = int((time.monotonic() - stream_start) * 1000)
                await self._record_completion(
                    provider_attempt,
                    model=chunk.model,
                    usage=chunk.usage,
                    latency_ms=latency_ms,
                )
            yield chunk

    async def _record_completion(
        self,
        provider_attempt: ProviderAttempt,
        *,
        model: str,
        usage: Usage,
        latency_ms: int,
    ) -> None:
        usage.cost_usd = self.calculate_usage_cost(provider_attempt.key, usage)
        route_fields = _route_fields(provider_attempt)
        logger.info(
            "llm_completed",
            **llm_completed_fields(
                provider=provider_attempt.key,
                model=model,
                usage=usage,
                latency_ms=latency_ms,
                **route_fields,
            ),
        )
        await self.event_bus.publish(
            "model.request",
            model_request_payload(
                provider=provider_attempt.key,
                model=model,
                usage=usage,
                latency_ms=latency_ms,
                **route_fields,
            ),
        )

    async def _handle_retry(
        self,
        provider_key: str,
        attempt: int,
        error: Exception,
        status: str,
    ) -> None:
        delay = self.config.retry_base_delay * (2**attempt)
        logger.warning(
            "llm_requested",
            surface="operational",
            status=status,
            provider=provider_key,
            attempt=attempt + 1,
            max_retries=self.config.max_retries,
            delay=delay,
            error=str(error),
        )
        if attempt < self.config.max_retries - 1:
            await asyncio.sleep(delay)


def _request_options(kwargs: dict[str, Any]) -> tuple[dict[str, Any], RouteTier | None, str | None]:
    call_kwargs = dict(kwargs)
    route_tier = call_kwargs.pop("route_tier", None)
    route_reason = call_kwargs.pop("route_reason", None)
    call_kwargs.pop("purpose", None)
    return call_kwargs, route_tier, route_reason


def _route_fields(provider_attempt: ProviderAttempt) -> dict[str, str]:
    fields: dict[str, str] = {}
    if provider_attempt.route_tier is not None:
        fields["route_tier"] = provider_attempt.route_tier
    if provider_attempt.route_reason is not None:
        fields["route_reason"] = provider_attempt.route_reason
    return fields
