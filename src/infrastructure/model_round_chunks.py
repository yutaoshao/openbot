"""Provider-capability aware model round chunk generation."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from src.core.logging import get_logger
from src.infrastructure.model_types import ModelResponse, StreamChunk

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from src.infrastructure.model_provider_selector import ProviderAttempt
    from src.infrastructure.model_types import ModelProvider

logger = get_logger(__name__)


async def model_round_chunks_for_provider(
    *,
    provider_attempt: ProviderAttempt,
    provider: ModelProvider,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    call_kwargs: dict[str, Any],
    record_completion: Callable[..., Awaitable[None]],
) -> AsyncIterator[StreamChunk]:
    if provider.supports_streaming:
        async for chunk in _streaming_chunks(
            provider_attempt=provider_attempt,
            provider=provider,
            messages=messages,
            tools=tools,
            call_kwargs=call_kwargs,
            record_completion=record_completion,
        ):
            yield chunk
        return

    logger.info(
        "model_streaming_unavailable",
        provider=provider_attempt.key,
        surface="operational",
    )
    response = await provider.chat(messages, tools, **call_kwargs)
    await record_completion(
        provider_attempt,
        model=response.model,
        usage=response.usage,
        latency_ms=response.latency_ms,
    )
    for chunk in response_to_chunks(response):
        yield chunk


async def streaming_chunks_for_provider(
    *,
    provider_attempt: ProviderAttempt,
    provider: ModelProvider,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    call_kwargs: dict[str, Any],
    record_completion: Callable[..., Awaitable[None]],
) -> AsyncIterator[StreamChunk]:
    async for chunk in _streaming_chunks(
        provider_attempt=provider_attempt,
        provider=provider,
        messages=messages,
        tools=tools,
        call_kwargs=call_kwargs,
        record_completion=record_completion,
    ):
        yield chunk


async def _streaming_chunks(
    *,
    provider_attempt: ProviderAttempt,
    provider: ModelProvider,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    call_kwargs: dict[str, Any],
    record_completion: Callable[..., Awaitable[None]],
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
            await record_completion(
                provider_attempt,
                model=chunk.model,
                usage=chunk.usage,
                latency_ms=latency_ms,
            )
        yield chunk


def response_to_chunks(response: ModelResponse) -> list[StreamChunk]:
    chunks: list[StreamChunk] = []
    if response.text:
        chunks.append(StreamChunk(type="text", text=response.text))
    for tool_call in response.tool_calls:
        chunks.append(StreamChunk(type="tool_call", tool_call=tool_call))
    chunks.append(
        StreamChunk(
            type="done",
            reasoning_content=response.reasoning_content,
            usage=response.usage,
            model=response.model,
        ),
    )
    return chunks
