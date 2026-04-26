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
from src.infrastructure.model_gateway import ModelResponse, StreamChunk, ToolCall, Usage

logger = get_logger(__name__)


def _merge_tool_name(existing: str, delta: str) -> str:
    """Merge streaming tool-name fragments without duplicating full names."""
    if not existing:
        return delta
    if not delta or delta == existing or existing.endswith(delta):
        return existing
    if delta.startswith(existing):
        return delta
    overlap = min(len(existing), len(delta))
    while overlap > 0:
        if existing[-overlap:] == delta[:overlap]:
            return existing + delta[overlap:]
        overlap -= 1
    return existing + delta


def _usage_from_openai(raw_usage: Any | None) -> Usage:
    """Convert OpenAI-compatible usage metadata into OpenBot usage fields."""
    if raw_usage is None:
        return Usage()
    tokens_in = int(getattr(raw_usage, "prompt_tokens", 0) or 0)
    tokens_out = int(getattr(raw_usage, "completion_tokens", 0) or 0)
    return Usage(
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cached_tokens=_cached_tokens_from_usage(raw_usage),
    )


def _cached_tokens_from_usage(raw_usage: Any) -> int | None:
    details = getattr(raw_usage, "prompt_tokens_details", None)
    if details is None:
        return None
    if isinstance(details, dict):
        value = details.get("cached_tokens")
    else:
        value = getattr(details, "cached_tokens", None)
    return int(value) if value is not None else None


class OpenAICompatibleProvider:
    """Provider for any OpenAI-compatible API endpoint."""

    def __init__(self, config: ModelProviderConfig) -> None:
        from openai import AsyncOpenAI

        self.config = config
        self.model = config.model

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

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Call OpenAI-compatible API and return unified response."""
        call_kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "messages": messages,  # OpenAI format accepts system in messages directly
        }
        if self.config.temperature is not None:
            call_kwargs["temperature"] = self.config.temperature

        if tools:
            call_kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["parameters"],
                    },
                }
                for t in tools
            ]

        start = time.monotonic()
        response = await self.client.chat.completions.create(**call_kwargs)
        latency_ms = int((time.monotonic() - start) * 1000)

        choice = response.choices[0]
        text = choice.message.content or ""

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
            tool_calls=tool_calls,
            usage=_usage_from_openai(response.usage),
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
        import json

        call_kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if self.config.temperature is not None:
            call_kwargs["temperature"] = self.config.temperature

        if tools:
            call_kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["parameters"],
                    },
                }
                for t in tools
            ]

        start = time.monotonic()

        stream = await self.client.chat.completions.create(**call_kwargs)

        # Accumulate tool call deltas (index -> {id, name, arguments_str})
        tc_accum: dict[int, dict[str, str]] = {}
        usage = Usage()
        accumulated_text = ""

        async for event in stream:
            # Usage chunk (sent at stream end when include_usage=True)
            if event.usage:
                usage = _usage_from_openai(event.usage)

            if not event.choices:
                continue

            delta = event.choices[0].delta

            # Text delta
            if delta.content:
                accumulated_text += delta.content
                yield StreamChunk(type="text", text=delta.content)

            # Tool call delta
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tc_accum:
                        tc_accum[idx] = {
                            "id": tc_delta.id or "",
                            "name": "",
                            "arguments": "",
                        }
                    acc = tc_accum[idx]
                    if tc_delta.id:
                        acc["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            acc["name"] = _merge_tool_name(
                                acc["name"],
                                tc_delta.function.name,
                            )
                        if tc_delta.function.arguments:
                            acc["arguments"] += tc_delta.function.arguments

            # Finish reason
            if event.choices[0].finish_reason:
                break

        # Yield accumulated tool calls
        for _idx in sorted(tc_accum):
            acc = tc_accum[_idx]
            args_str = acc["arguments"]
            try:
                args = json.loads(args_str) if args_str else {}
            except json.JSONDecodeError:
                args = {"_raw": args_str}
            yield StreamChunk(
                type="tool_call",
                tool_call=ToolCall(id=acc["id"], name=acc["name"], arguments=args),
            )

        # Estimate tokens if the API didn't report usage
        latency_ms = int((time.monotonic() - start) * 1000)

        if usage.tokens_in == 0 and usage.tokens_out == 0:
            # Rough estimate: ~3 chars/token for mixed CJK/Latin
            input_chars = sum(len(str(m.get("content", ""))) for m in messages)
            output_chars = len(accumulated_text)
            for acc in tc_accum.values():
                output_chars += len(acc.get("arguments", ""))
            usage = Usage(
                tokens_in=max(1, input_chars // 3),
                tokens_out=max(1, output_chars // 3),
            )
            logger.debug(
                "openai_compat.usage_estimated",
                tokens_in=usage.tokens_in,
                tokens_out=usage.tokens_out,
            )

        yield StreamChunk(
            type="done",
            usage=usage,
            model=self.model,
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
