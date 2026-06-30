"""Multi-provider LLM gateway with fallback and retry support.

Abstracts away provider differences behind a unified interface.
Provider implementations live in src/infrastructure/providers/.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.core.logging import get_logger
from src.infrastructure.model_gateway_events import (
    handle_model_retry,
    record_model_completion,
)
from src.infrastructure.model_gateway_requests import (
    GatewayRequestContext,
    run_chat_request,
    run_model_round_request,
    run_stream_request,
)
from src.infrastructure.model_provider_selector import ModelProviderSelector, ProviderAttempt
from src.infrastructure.model_routing import ModelRouter
from src.infrastructure.model_types import (
    ModelProvider,
    ModelResponse,
    StreamChunk,
    ToolCall,
    Usage,
)

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
        from src.infrastructure.providers.openai_responses import OpenAIResponsesProvider

        if config.provider == "anthropic":
            return ClaudeProvider(config)
        if config.provider == "openai_compatible":
            return OpenAICompatibleProvider(config)
        if config.provider == "openai_responses":
            return OpenAIResponsesProvider(config)
        raise ValueError(
            "Unsupported provider: "
            f"'{config.provider}'. Supported: anthropic, openai_compatible, openai_responses"
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Send chat request with retry and fallback."""
        call_kwargs, route_tier, route_reason = _request_options(kwargs)
        return await run_chat_request(
            context=self._request_context(),
            messages=messages,
            tools=tools,
            call_kwargs=call_kwargs,
            route_tier=route_tier,
            route_reason=route_reason,
        )

    async def model_round_chunks(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Yield one model round using streaming only when the provider supports it."""
        call_kwargs, route_tier, route_reason = _request_options(kwargs)
        async for chunk in run_model_round_request(
            context=self._request_context(),
            messages=messages,
            tools=tools,
            call_kwargs=call_kwargs,
            route_tier=route_tier,
            route_reason=route_reason,
        ):
            yield chunk

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
        async for chunk in run_stream_request(
            context=self._request_context(),
            messages=messages,
            tools=tools,
            call_kwargs=call_kwargs,
            route_tier=route_tier,
            route_reason=route_reason,
        ):
            yield chunk

    def _request_context(self) -> GatewayRequestContext:
        return GatewayRequestContext(
            config=self.config,
            attempts=self._provider_selector().attempts,
            providers=self._providers,
            record_completion=self._record_completion,
            handle_retry=self._handle_retry,
        )

    async def _record_completion(
        self,
        provider_attempt: ProviderAttempt,
        *,
        model: str,
        usage: Usage,
        latency_ms: int,
    ) -> None:
        await record_model_completion(
            event_bus=self.event_bus,
            provider_attempt=provider_attempt,
            model=model,
            usage=usage,
            latency_ms=latency_ms,
            cost_usd=self.calculate_usage_cost(provider_attempt.key, usage),
        )

    async def _handle_retry(
        self,
        provider_key: str,
        attempt: int,
        error: Exception,
        status: str,
    ) -> None:
        await handle_model_retry(
            config=self.config,
            provider_key=provider_key,
            attempt=attempt,
            error=error,
            status=status,
        )


def _request_options(kwargs: dict[str, Any]) -> tuple[dict[str, Any], RouteTier | None, str | None]:
    call_kwargs = dict(kwargs)
    route_tier = call_kwargs.pop("route_tier", None)
    route_reason = call_kwargs.pop("route_reason", None)
    call_kwargs.pop("purpose", None)
    return call_kwargs, route_tier, route_reason

