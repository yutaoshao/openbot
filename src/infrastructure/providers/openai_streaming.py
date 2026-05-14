"""Streaming response parsing for OpenAI-compatible providers."""

from __future__ import annotations

import json
from typing import Any

from src.infrastructure.model_types import StreamChunk, ToolCall, Usage

CHARS_PER_TOKEN_ESTIMATE = 3
MIN_ESTIMATED_TOKENS = 1


class OpenAIStreamAccumulator:
    """Accumulate OpenAI-compatible stream deltas into OpenBot chunks."""

    def __init__(self) -> None:
        self.tool_calls: dict[int, dict[str, str]] = {}
        self.usage = Usage()
        self.text = ""
        self.reasoning_content = ""

    def consume(self, event: Any) -> StreamChunk | None:
        """Consume one stream event and return a visible text chunk when present."""
        if event.usage:
            self.usage = usage_from_openai(event.usage)
        if not event.choices:
            return None

        delta = event.choices[0].delta
        delta_reasoning = getattr(delta, "reasoning_content", None)
        if delta_reasoning:
            self.reasoning_content += delta_reasoning
        if delta.content:
            self.text += delta.content
            return StreamChunk(type="text", text=delta.content)
        if delta.tool_calls:
            self._accumulate_tool_calls(delta.tool_calls)
        return None

    def tool_call_chunks(self) -> list[StreamChunk]:
        """Render accumulated function-call deltas after stream completion."""
        chunks = []
        for idx in sorted(self.tool_calls):
            acc = self.tool_calls[idx]
            args_str = acc["arguments"]
            try:
                args = json.loads(args_str) if args_str else {}
            except json.JSONDecodeError:
                args = {"_raw": args_str}
            chunks.append(
                StreamChunk(
                    type="tool_call",
                    tool_call=ToolCall(id=acc["id"], name=acc["name"], arguments=args),
                )
            )
        return chunks

    def usage_or_estimate(self, messages: list[dict[str, Any]]) -> Usage:
        """Return API usage, or a rough estimate when providers omit it."""
        if self.usage.tokens_in != 0 or self.usage.tokens_out != 0:
            return self.usage
        input_chars = sum(len(str(message.get("content", ""))) for message in messages)
        output_chars = len(self.text)
        for acc in self.tool_calls.values():
            output_chars += len(acc.get("arguments", ""))
        return Usage(
            tokens_in=max(MIN_ESTIMATED_TOKENS, input_chars // CHARS_PER_TOKEN_ESTIMATE),
            tokens_out=max(MIN_ESTIMATED_TOKENS, output_chars // CHARS_PER_TOKEN_ESTIMATE),
        )

    def _accumulate_tool_calls(self, tool_call_deltas: list[Any]) -> None:
        for tc_delta in tool_call_deltas:
            idx = tc_delta.index
            if idx not in self.tool_calls:
                self.tool_calls[idx] = {"id": tc_delta.id or "", "name": "", "arguments": ""}
            acc = self.tool_calls[idx]
            if tc_delta.id:
                acc["id"] = tc_delta.id
            if tc_delta.function:
                _accumulate_tool_function(acc, tc_delta.function)


def usage_from_openai(raw_usage: Any | None) -> Usage:
    """Convert OpenAI-compatible usage metadata into OpenBot usage fields."""
    if raw_usage is None:
        return Usage()
    return Usage(
        tokens_in=int(getattr(raw_usage, "prompt_tokens", 0) or 0),
        tokens_out=int(getattr(raw_usage, "completion_tokens", 0) or 0),
        cached_tokens=_cached_tokens_from_usage(raw_usage),
    )


def _accumulate_tool_function(acc: dict[str, str], function: Any) -> None:
    if function.name:
        acc["name"] = _merge_tool_name(acc["name"], function.name)
    if function.arguments:
        acc["arguments"] += function.arguments


def _cached_tokens_from_usage(raw_usage: Any) -> int | None:
    details = getattr(raw_usage, "prompt_tokens_details", None)
    if details is None:
        return None
    if isinstance(details, dict):
        value = details.get("cached_tokens")
    else:
        value = getattr(details, "cached_tokens", None)
    return int(value) if value is not None else None


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
