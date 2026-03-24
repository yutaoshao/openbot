"""Multi-provider LLM gateway with fallback and retry support.

Abstracts away provider differences behind a unified interface.
Provider implementations live in src/infrastructure/providers/.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from src.core.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from src.core.config import ModelConfig, ModelProviderConfig
    from src.infrastructure.event_bus import EventBus

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


@dataclass
class StreamChunk:
    """A single chunk from a streaming model response."""

    type: Literal["text", "tool_call", "tool_status", "done"]
    text: str = ""
    tool_call: ToolCall | None = None
    tool_name: str = ""           # type="tool_status"
    usage: Usage | None = None    # type="done"
    model: str = ""               # type="done"


@runtime_checkable
class ModelProvider(Protocol):
    """Protocol for LLM provider implementations."""

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse: ...

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]: ...


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

                    logger.info(
                        "llm_completed",
                        surface="operational",
                        provider=provider_key,
                        model=response.model,
                        token_in=response.usage.tokens_in,
                        token_out=response.usage.tokens_out,
                        cost=response.usage.cost,
                        latency_ms=response.latency_ms,
                    )

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
                        "llm_requested",
                        surface="operational",
                        status="retry",
                        provider=provider_key,
                        attempt=attempt + 1,
                        max_retries=self.config.max_retries,
                        delay=delay,
                        error=str(e),
                    )
                    if attempt < self.config.max_retries - 1:
                        await asyncio.sleep(delay)

            logger.error(
                "llm_requested",
                surface="operational",
                status="exhausted",
                provider=provider_key,
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
        providers_to_try = ["primary"]
        if "fallback" in self._providers:
            providers_to_try.append("fallback")

        last_error: Exception | None = None

        for provider_key in providers_to_try:
            provider = self._providers[provider_key]
            for attempt in range(self.config.max_retries):
                try:
                    stream = provider.chat_stream(messages, tools, **kwargs)
                    first = True
                    async for chunk in stream:
                        if first:
                            first = False
                            logger.info(
                                "llm_requested",
                                surface="operational",
                                status="streaming",
                                provider=provider_key,
                            )
                        yield chunk
                    return  # noqa: B012 — stream consumed, done

                except Exception as e:
                    last_error = e
                    delay = self.config.retry_base_delay * (2 ** attempt)
                    logger.warning(
                        "llm_requested",
                        surface="operational",
                        status="stream_retry",
                        provider=provider_key,
                        attempt=attempt + 1,
                        max_retries=self.config.max_retries,
                        delay=delay,
                        error=str(e),
                    )
                    if attempt < self.config.max_retries - 1:
                        await asyncio.sleep(delay)

            logger.error(
                "llm_requested",
                surface="operational",
                status="stream_exhausted",
                provider=provider_key,
            )

        raise RuntimeError(
            f"All model providers failed (stream): {last_error}",
        ) from last_error
