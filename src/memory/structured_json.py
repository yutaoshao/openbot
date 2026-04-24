"""Shared helpers for parsing JSON-array LLM responses."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

_CODE_FENCE = "```"
_TOOL_CALL_START = "[TOOL_CALL]"
_TOOL_CALL_END = "[/TOOL_CALL]"


@dataclass(frozen=True)
class JsonArrayParseResult:
    """Normalized result for structured JSON-array parsing."""

    items: list[dict[str, Any]]
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.reason == ""


def parse_json_array_response(text: str) -> JsonArrayParseResult:
    """Parse a JSON-array response from raw LLM text."""
    cleaned = text.strip()
    if not cleaned:
        return JsonArrayParseResult(items=[], reason="empty")
    if _TOOL_CALL_START in cleaned and _TOOL_CALL_END in cleaned:
        return JsonArrayParseResult(items=[], reason="tool_call_wrapper")

    stripped = _strip_code_fences(cleaned)
    parsed = _decode_json_array(stripped)
    if parsed is None:
        return JsonArrayParseResult(items=[], reason=_parse_failure_reason(stripped))
    return JsonArrayParseResult(
        items=[item for item in parsed if isinstance(item, dict)],
    )


def _strip_code_fences(text: str) -> str:
    lines = text.strip().splitlines()
    if len(lines) < 2:
        return text.strip()
    if not lines[0].strip().startswith(_CODE_FENCE):
        return text.strip()
    if lines[-1].strip() != _CODE_FENCE:
        return text.strip()
    return "\n".join(lines[1:-1]).strip()


def _decode_json_array(text: str) -> list[Any] | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return _extract_json_array(text)
    return parsed if isinstance(parsed, list) else None


def _extract_json_array(text: str) -> list[Any] | None:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "[":
            continue
        try:
            parsed, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            return parsed
    return None


def _parse_failure_reason(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return "empty"
    if "[" not in stripped:
        return "no_json_array"
    if stripped.startswith("["):
        return "invalid_json_array"
    return "wrapped_non_json_array"
