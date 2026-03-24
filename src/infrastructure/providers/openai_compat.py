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


class OpenAICompatibleProvider:
    """Provider for any OpenAI-compatible API endpoint."""

    def __init__(self, config: ModelProviderConfig) -> None:
        from openai import AsyncOpenAI

        self.config = config
        self.model = config.model
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )

        logger.info(
            "openai_compat.init",
            model=self.model,
            base_url=config.base_url,
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

        # Usage may not be present in all providers
        tokens_in = response.usage.prompt_tokens if response.usage else 0
        tokens_out = response.usage.completion_tokens if response.usage else 0

        # Cost calculation: use pricing from config, fallback to 0
        cost = (
            tokens_in * self.config.pricing_input + tokens_out * self.config.pricing_output
        ) / 1_000_000

        return ModelResponse(
            text=text,
            tool_calls=tool_calls,
            usage=Usage(tokens_in=tokens_in, tokens_out=tokens_out, cost=cost),
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
        tokens_in = 0
        tokens_out = 0
        accumulated_text = ""

        async for event in stream:
            # Usage chunk (sent at stream end when include_usage=True)
            if event.usage:
                tokens_in = event.usage.prompt_tokens or 0
                tokens_out = event.usage.completion_tokens or 0

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
                            acc["name"] += tc_delta.function.name
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

        # Cost — estimate tokens if the API didn't report usage
        latency_ms = int((time.monotonic() - start) * 1000)

        if tokens_in == 0 and tokens_out == 0:
            # Rough estimate: ~3 chars/token for mixed CJK/Latin
            input_chars = sum(len(str(m.get("content", ""))) for m in messages)
            tokens_in = max(1, input_chars // 3)
            output_chars = len(accumulated_text)
            for acc in tc_accum.values():
                output_chars += len(acc.get("arguments", ""))
            tokens_out = max(1, output_chars // 3)
            logger.debug(
                "openai_compat.usage_estimated",
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )

        cost = (
            tokens_in * self.config.pricing_input
            + tokens_out * self.config.pricing_output
        ) / 1_000_000

        yield StreamChunk(
            type="done",
            usage=Usage(tokens_in=tokens_in, tokens_out=tokens_out, cost=cost),
            model=self.model,
        )

        logger.debug(
            "openai_compat.stream_done",
            model=self.model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
        )
