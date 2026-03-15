"""Anthropic Claude provider."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.platform.config import ModelProviderConfig

from src.infrastructure.model_gateway import ModelResponse, ToolCall, Usage


class ClaudeProvider:
    """Anthropic Claude API provider."""

    # Pricing per 1M tokens
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

        text_parts = []
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=block.input)
                )

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
