"""Multi-provider LLM gateway with fallback and retry support.

Abstracts away provider differences (Anthropic/OpenAI) behind a unified interface.
Publishes usage events to Event Bus for monitoring.
"""

from __future__ import annotations

import asyncio
import time
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
        """Convert to message dict for conversation context."""
        msg: dict[str, Any] = {"role": "assistant"}
        if self.text:
            msg["content"] = self.text
        if self.tool_calls:
            msg["tool_calls"] = [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
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


class ClaudeProvider:
    """Anthropic Claude API provider."""

    # Pricing per 1M tokens (as of 2025)
    PRICING = {
        "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
        "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
    }

    def __init__(self, config: ModelProviderConfig) -> None:
        import anthropic

        self.config = config
        self.client = anthropic.AsyncAnthropic(api_key=config.api_key)
        self.model = config.model

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Call Claude API and return unified response."""
        # Separate system message from conversation messages
        system_text = ""
        conversation = []
        for msg in messages:
            if msg["role"] == "system":
                system_text += msg["content"] + "\n"
            else:
                conversation.append(msg)

        call_kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "messages": conversation,
        }
        if system_text.strip():
            call_kwargs["system"] = system_text.strip()
        if self.config.temperature is not None:
            call_kwargs["temperature"] = self.config.temperature

        if tools:
            call_kwargs["tools"] = [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "input_schema": t["parameters"],
                }
                for t in tools
            ]

        start = time.monotonic()
        response = await self.client.messages.create(**call_kwargs)
        latency_ms = int((time.monotonic() - start) * 1000)

        # Parse response
        text_parts = []
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=block.input)
                )

        # Calculate cost
        pricing = self.PRICING.get(self.model, {"input": 3.0, "output": 15.0})
        cost = (
            response.usage.input_tokens * pricing["input"]
            + response.usage.output_tokens * pricing["output"]
        ) / 1_000_000

        return ModelResponse(
            text="\n".join(text_parts),
            tool_calls=tool_calls,
            usage=Usage(
                tokens_in=response.usage.input_tokens,
                tokens_out=response.usage.output_tokens,
                cost=cost,
            ),
            model=self.model,
            latency_ms=latency_ms,
        )


class ModelGateway:
    """Unified gateway that routes requests, handles retries and fallback."""

    def __init__(self, config: ModelConfig, event_bus: EventBus) -> None:
        self.config = config
        self.event_bus = event_bus
        self._providers: dict[str, ModelProvider] = {}

        # Initialize primary provider
        self._providers["primary"] = self._create_provider(config.primary)
        if config.fallback:
            self._providers["fallback"] = self._create_provider(config.fallback)

        logger.info(
            "model_gateway.init",
            primary=config.primary.model,
            fallback=config.fallback.model if config.fallback else None,
        )

    def _create_provider(self, config: ModelProviderConfig) -> ModelProvider:
        """Factory method to create provider by type."""
        if config.provider == "anthropic":
            return ClaudeProvider(config)
        raise ValueError(f"Unsupported provider: {config.provider}")

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Send chat request with retry and fallback.

        Tries primary provider first. On failure, retries with exponential backoff.
        If all retries fail and a fallback provider exists, tries fallback.
        """
        providers_to_try = ["primary"]
        if "fallback" in self._providers:
            providers_to_try.append("fallback")

        last_error: Exception | None = None

        for provider_key in providers_to_try:
            provider = self._providers[provider_key]
            for attempt in range(self.config.max_retries):
                try:
                    response = await provider.chat(messages, tools, **kwargs)

                    # Publish usage event for monitoring
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
