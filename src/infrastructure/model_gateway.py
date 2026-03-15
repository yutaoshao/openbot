"""Multi-provider LLM gateway with fallback and retry support.

Abstracts away provider differences behind a unified interface.
Provider implementations live in src/infrastructure/providers/.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from src.platform.logging import get_logger

if TYPE_CHECKING:
    from src.infrastructure.event_bus import EventBus
    from src.platform.config import ModelConfig, ModelProviderConfig

logger = get_logger(__name__)


@dataclass
class ToolCall:
    """A tool call requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Usage:
    """Token usage and cost for a single request."""

    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0


@dataclass
class ModelResponse:
    """Unified response from any model provider."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    latency_ms: int = 0

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

    def to_assistant_message(self) -> dict[str, Any]:
        """Convert to message dict for conversation context (OpenAI format)."""
        msg: dict[str, Any] = {"role": "assistant"}
        if self.text:
            msg["content"] = self.text
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in self.tool_calls
            ]
        return msg


@runtime_checkable
class ModelProvider(Protocol):
    """Protocol for LLM provider implementations."""

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse: ...


class ModelGateway:
    """Unified gateway that routes requests, handles retries and fallback."""

    def __init__(self, config: ModelConfig, event_bus: EventBus) -> None:
        self.config = config
        self.event_bus = event_bus
        self._providers: dict[str, ModelProvider] = {}

        self._providers["primary"] = self._create_provider(config.primary)
        if config.fallback:
            self._providers["fallback"] = self._create_provider(config.fallback)

        logger.info(
            "model_gateway.init",
            primary=config.primary.model,
            fallback=config.fallback.model if config.fallback else None,
        )

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
            f"Unsupported provider: '{config.provider}'. "
            f"Supported: anthropic, openai_compatible"
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Send chat request with retry and fallback."""
        providers_to_try = ["primary"]
        if "fallback" in self._providers:
            providers_to_try.append("fallback")

        last_error: Exception | None = None

        for provider_key in providers_to_try:
            provider = self._providers[provider_key]
            for attempt in range(self.config.max_retries):
                try:
                    response = await provider.chat(messages, tools, **kwargs)

                    await self.event_bus.publish("model.request", {
                        "provider": provider_key,
                        "model": response.model,
                        "tokens_in": response.usage.tokens_in,
                        "tokens_out": response.usage.tokens_out,
                        "cost": response.usage.cost,
                        "latency_ms": response.latency_ms,
                    })

                    return response

                except Exception as e:
                    last_error = e
                    delay = self.config.retry_base_delay * (2 ** attempt)
                    logger.warning(
                        "model_gateway.retry",
                        provider=provider_key,
                        attempt=attempt + 1,
                        max_retries=self.config.max_retries,
                        delay=delay,
                        error=str(e),
                    )
                    if attempt < self.config.max_retries - 1:
                        await asyncio.sleep(delay)

            logger.error("model_gateway.provider_exhausted", provider=provider_key)

        raise RuntimeError(f"All model providers failed: {last_error}") from last_error
