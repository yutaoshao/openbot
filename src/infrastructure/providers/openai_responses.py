"""OpenAI Responses API provider."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from src.core.config import ModelProviderConfig

from src.core.logging import get_logger
from src.infrastructure.model_types import ModelResponse, StreamChunk, ToolCall, Usage

logger = get_logger(__name__)


class OpenAIResponsesProvider:
    """Provider for OpenAI-compatible Responses API endpoints."""

    supports_streaming = False

    def __init__(self, config: ModelProviderConfig) -> None:
        from openai import AsyncOpenAI

        if not config.api_key:
            raise ValueError(
                f"Missing API key env {config.api_key_env} for openai_responses provider"
            )

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
            max_retries=0,
        )

        logger.info(
            "openai_responses.init",
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
        start = time.monotonic()
        response = await self.client.responses.create(
            **self._request_kwargs(messages, tools, kwargs)
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        return _response_from_openai(response, model=self.model, latency_ms=latency_ms)

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        raise NotImplementedError("openai_responses provider does not support streaming yet")
        yield

    def _request_kwargs(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        request_kwargs: dict[str, Any] = {
            "model": self.model,
            "input": messages,
            "max_output_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "reasoning": {"effort": self.config.reasoning_effort},
            "text": {"verbosity": self.config.verbosity},
        }
        if tools:
            request_kwargs["tools"] = [_responses_function_tool(tool) for tool in tools]
        return request_kwargs


def _response_from_openai(response: Any, *, model: str, latency_ms: int) -> ModelResponse:
    texts: list[str] = []
    tool_calls: list[ToolCall] = []
    reasoning_content = ""

    for output_item in getattr(response, "output", []) or []:
        output_type = _field(output_item, "type", "")
        if output_type == "message":
            texts.append(_message_text(output_item))
            continue
        if output_type == "function_call":
            tool_calls.append(_tool_call(output_item))
            continue
        if output_type == "reasoning":
            reasoning_content += _reasoning_text(output_item)
            continue
        raise ValueError(f"Unsupported Responses output type: {output_type}")

    return ModelResponse(
        text="\n".join(text for text in texts if text),
        reasoning_content=reasoning_content,
        tool_calls=tool_calls,
        usage=_usage_from_responses(getattr(response, "usage", None)),
        model=model,
        latency_ms=latency_ms,
    )


def _responses_function_tool(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "name": tool["name"],
        "description": tool["description"],
        "parameters": tool["parameters"],
    }


def _message_text(output_item: Any) -> str:
    parts: list[str] = []
    for content_item in _field(output_item, "content", []) or []:
        content_type = _field(content_item, "type", "")
        if content_type == "output_text":
            parts.append(str(_field(content_item, "text", "")))
            continue
        raise ValueError(f"Unsupported Responses message content type: {content_type}")
    return "".join(parts)


def _tool_call(output_item: Any) -> ToolCall:
    tool_name = str(_field(output_item, "name", ""))
    raw_arguments = str(_field(output_item, "arguments", "") or "{}")
    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON arguments for tool '{tool_name}': {raw_arguments[:200]}"
        ) from exc
    return ToolCall(
        id=str(_field(output_item, "call_id", "") or _field(output_item, "id", "")),
        name=tool_name,
        arguments=arguments,
    )


def _reasoning_text(output_item: Any) -> str:
    summary = _field(output_item, "summary", None)
    if not summary:
        return ""
    parts: list[str] = []
    for summary_item in summary:
        text = _field(summary_item, "text", "")
        if text:
            parts.append(str(text))
    return "".join(parts)


def _usage_from_responses(raw_usage: Any | None) -> Usage:
    if raw_usage is None:
        return Usage()
    return Usage(
        tokens_in=int(_field(raw_usage, "input_tokens", 0) or 0),
        tokens_out=int(_field(raw_usage, "output_tokens", 0) or 0),
        cached_tokens=_cached_tokens_from_responses(raw_usage),
    )


def _cached_tokens_from_responses(raw_usage: Any) -> int | None:
    details = _field(raw_usage, "input_tokens_details", None)
    if details is None:
        return None
    value = _field(details, "cached_tokens", None)
    return int(value) if value is not None else None


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)
