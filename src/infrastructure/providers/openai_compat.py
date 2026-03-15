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
    from src.platform.config import ModelProviderConfig

from src.infrastructure.model_gateway import ModelResponse, ToolCall, Usage
from src.platform.logging import get_logger

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
