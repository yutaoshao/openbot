"""OpenAI-compatible API provider.

Works with any provider that implements the OpenAI chat completions API:
- Volcengine (doubao)
- DeepSeek
- Moonshot (Kimi)
- Groq
- Together AI
- Local models via Ollama / vLLM / LMStudio
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from src.core.config import ModelProviderConfig

from src.core.logging import get_logger
from src.infrastructure.model_gateway import ModelResponse, StreamChunk, ToolCall
from src.infrastructure.providers.openai_messages import (
    preserves_reasoning_content,
    request_messages,
    tool_schemas,
)
from src.infrastructure.providers.openai_streaming import (
    OpenAIStreamAccumulator,
    usage_from_openai,
)

logger = get_logger(__name__)


class OpenAICompatibleProvider:
    """Provider for any OpenAI-compatible API endpoint."""

    def __init__(self, config: ModelProviderConfig) -> None:
        from openai import AsyncOpenAI

        self.config = config
        self.model = config.model
        self._preserve_reasoning_content = preserves_reasoning_content(self.model)

        import httpx

        timeout = httpx.Timeout(
            connect=config.connect_timeout,
            read=config.read_timeout,
            write=config.connect_timeout,
            pool=config.connect_timeout,
        )
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=timeout,
            max_retries=0,  # We handle retries in ModelGateway
        )

        logger.info(
            "openai_compat.init",
            model=self.model,
            base_url=config.base_url,
            connect_timeout=config.connect_timeout,
            read_timeout=config.read_timeout,
        )

    def _request_kwargs(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        kwargs: dict[str, Any],
        *,
        stream: bool,
    ) -> dict[str, Any]:
        preserve = self._preserve_reasoning_content
        request_kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "messages": request_messages(messages, preserve_reasoning_content=preserve),
        }
        if stream:
            request_kwargs["stream"] = True
            request_kwargs["stream_options"] = {"include_usage": True}
        if self.config.temperature is not None:
            request_kwargs["temperature"] = self.config.temperature
        if tools:
            request_kwargs["tools"] = tool_schemas(tools)
        return request_kwargs

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Call OpenAI-compatible API and return unified response."""
        start = time.monotonic()
        response = await self.client.chat.completions.create(
            **self._request_kwargs(messages, tools, kwargs, stream=False)
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        choice = response.choices[0]
        text = choice.message.content or ""
        reasoning_content = str(getattr(choice.message, "reasoning_content", "") or "")

        tool_calls = []
        if choice.message.tool_calls:
            import json

            for tc in choice.message.tool_calls:
                args = tc.function.arguments
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=json.loads(args) if isinstance(args, str) else args,
                    )
                )

        return ModelResponse(
            text=text,
            reasoning_content=reasoning_content,
            tool_calls=tool_calls,
            usage=usage_from_openai(response.usage),
            model=self.model,
            latency_ms=latency_ms,
        )

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Stream chat completions and yield StreamChunk objects."""
        start = time.monotonic()
        stream = await self.client.chat.completions.create(
            **self._request_kwargs(messages, tools, kwargs, stream=True)
        )
        accumulator = OpenAIStreamAccumulator()

        async for event in stream:
            chunk = accumulator.consume(event)
            if chunk is not None:
                yield chunk
            if not event.choices:
                continue
            if event.choices[0].finish_reason:
                break

        for chunk in accumulator.tool_call_chunks():
            yield chunk

        latency_ms = int((time.monotonic() - start) * 1000)
        usage = accumulator.usage_or_estimate(messages)
        if usage is not accumulator.usage:
            logger.debug(
                "openai_compat.usage_estimated",
                tokens_in=usage.tokens_in,
                tokens_out=usage.tokens_out,
            )

        yield StreamChunk(
            type="done",
            usage=usage,
            model=self.model,
            reasoning_content=accumulator.reasoning_content,
        )

        logger.debug(
            "openai_compat.stream_done",
            model=self.model,
            tokens_in=usage.tokens_in,
            tokens_out=usage.tokens_out,
            cached_tokens=usage.cached_tokens,
            cache_hit_ratio=usage.cache_hit_ratio,
            latency_ms=latency_ms,
        )
