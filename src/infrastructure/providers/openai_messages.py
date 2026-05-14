"""OpenAI-compatible message helpers."""

from __future__ import annotations

from typing import Any

_REASONING_CONTENT_MODELS = frozenset(
    {
        "mimo-v2.5-pro",
        "mimo-v2.5",
        "mimo-v2-pro",
        "mimo-v2-omni",
        "mimo-v2-flash",
    }
)


def preserves_reasoning_content(model: str) -> bool:
    """Return true when the provider requires reasoning history in messages."""
    normalized = model.lower()
    return normalized in _REASONING_CONTENT_MODELS or normalized.startswith("mimo-")


def request_messages(
    messages: list[dict[str, Any]],
    *,
    preserve_reasoning_content: bool,
) -> list[dict[str, Any]]:
    """Strip provider-specific reasoning fields unless this model needs them."""
    if preserve_reasoning_content or not _contains_reasoning_content(messages):
        return messages
    return [_without_reasoning_content(message) for message in messages]


def _contains_reasoning_content(messages: list[dict[str, Any]]) -> bool:
    return any("reasoning_content" in message for message in messages)


def _without_reasoning_content(message: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in message.items() if key != "reasoning_content"}


def tool_schemas(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert internal tool schemas to OpenAI-compatible function tools."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["parameters"],
            },
        }
        for tool in tools
    ]
