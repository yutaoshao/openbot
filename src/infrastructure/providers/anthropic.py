"""Anthropic Claude provider."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from src.core.config import ModelProviderConfig

from src.infrastructure.model_gateway import ModelResponse, StreamChunk, ToolCall, Usage


def _usage_from_anthropic(raw_usage: Any | None) -> Usage:
    if raw_usage is None:
        return Usage()
    return Usage(
        tokens_in=int(getattr(raw_usage, "input_tokens", 0) or 0),
        tokens_out=int(getattr(raw_usage, "output_tokens", 0) or 0),
        cached_tokens=_anthropic_cache_read_tokens(raw_usage),
    )


def _anthropic_cache_read_tokens(raw_usage: Any) -> int | None:
    value = getattr(raw_usage, "cache_read_input_tokens", None)
    return int(value) if value is not None else None


class ClaudeProvider:
    """Anthropic Claude API provider."""

    # Pricing per 1M tokens
    PRICING = {
        "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
        "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
    }

    def __init__(self, config: ModelProviderConfig) -> None:
        import anthropic
        import httpx

        self.config = config
        timeout = httpx.Timeout(
            connect=config.connect_timeout,
            read=config.read_timeout,
            write=config.connect_timeout,
            pool=config.connect_timeout,
        )
        self.client = anthropic.AsyncAnthropic(
            api_key=config.api_key,
            timeout=timeout,
            max_retries=0,  # We handle retries in ModelGateway
        )
        self.model = config.model

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Call Claude API and return unified response."""
        system_text = ""
        conversation = []
        for msg in messages:
            if msg["role"] == "system":
                system_text += msg["content"] + "\n"
            elif msg["role"] == "assistant" and "tool_calls" in msg:
                # Convert OpenAI-format assistant+tool_calls to Anthropic format
                content: list[dict[str, Any]] = []
                if msg.get("content"):
                    content.append({"type": "text", "text": msg["content"]})
                for tc in msg["tool_calls"]:
                    import json as _json

                    args = tc["function"]["arguments"]
                    content.append(
                        {
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": tc["function"]["name"],
                            "input": _json.loads(args) if isinstance(args, str) else args,
                        }
                    )
                conversation.append({"role": "assistant", "content": content})
            elif msg["role"] == "tool":
                # Convert OpenAI-format tool result to Anthropic format
                conversation.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.get("tool_call_id", ""),
                                "content": msg.get("content", ""),
                            }
                        ],
                    }
                )
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

        text_parts = []
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=block.input))

        return ModelResponse(
            text="\n".join(text_parts),
            tool_calls=tool_calls,
            usage=_usage_from_anthropic(response.usage),
            model=self.model,
            latency_ms=latency_ms,
        )

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Stream Claude messages and yield StreamChunk objects."""
        system_text = ""
        conversation = []
        for msg in messages:
            if msg["role"] == "system":
                system_text += msg["content"] + "\n"
            elif msg["role"] == "assistant" and "tool_calls" in msg:
                import json as _json

                content: list[dict[str, Any]] = []
                if msg.get("content"):
                    content.append({"type": "text", "text": msg["content"]})
                for tc in msg["tool_calls"]:
                    args = tc["function"]["arguments"]
                    content.append(
                        {
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": tc["function"]["name"],
                            "input": _json.loads(args) if isinstance(args, str) else args,
                        }
                    )
                conversation.append({"role": "assistant", "content": content})
            elif msg["role"] == "tool":
                conversation.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.get("tool_call_id", ""),
                                "content": msg.get("content", ""),
                            }
                        ],
                    }
                )
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

        # Accumulate tool use blocks: block_index -> {id, name, input_json_str}
        tc_accum: dict[int, dict[str, str]] = {}
        current_block_idx = -1
        usage = Usage()

        async with self.client.messages.stream(**call_kwargs) as stream:
            async for event in stream:
                event_type = event.type

                if event_type == "content_block_start":
                    current_block_idx += 1
                    block = event.content_block
                    if block.type == "tool_use":
                        tc_accum[current_block_idx] = {
                            "id": block.id,
                            "name": block.name,
                            "input_json": "",
                        }

                elif event_type == "content_block_delta":
                    delta = event.delta
                    if delta.type == "text_delta":
                        yield StreamChunk(type="text", text=delta.text)
                    elif delta.type == "input_json_delta" and current_block_idx in tc_accum:
                        tc_accum[current_block_idx]["input_json"] += delta.partial_json

                elif event_type == "message_delta":
                    if hasattr(event, "usage") and event.usage:
                        usage.tokens_out = event.usage.output_tokens

                elif event_type == "message_start":
                    if hasattr(event, "message") and event.message.usage:
                        start_usage = _usage_from_anthropic(event.message.usage)
                        usage.tokens_in = start_usage.tokens_in
                        usage.cached_tokens = start_usage.cached_tokens

        # Yield accumulated tool calls
        import json

        for _idx in sorted(tc_accum):
            acc = tc_accum[_idx]
            try:
                args = json.loads(acc["input_json"]) if acc["input_json"] else {}
            except json.JSONDecodeError:
                args = {"_raw": acc["input_json"]}
            yield StreamChunk(
                type="tool_call",
                tool_call=ToolCall(id=acc["id"], name=acc["name"], arguments=args),
            )

        yield StreamChunk(
            type="done",
            usage=usage,
            model=self.model,
        )
