from __future__ import annotations

from src.infrastructure.providers.openai_messages import (
    preserves_reasoning_content,
    request_messages,
)


def test_request_messages_strips_reasoning_content_for_plain_models() -> None:
    messages = [{"role": "assistant", "reasoning_content": "private", "tool_calls": []}]

    sanitized = request_messages(messages, preserve_reasoning_content=False)

    assert "reasoning_content" not in sanitized[0]
    assert messages[0]["reasoning_content"] == "private"


def test_request_messages_preserves_reasoning_content_for_mimo_models() -> None:
    messages = [{"role": "assistant", "reasoning_content": "private", "tool_calls": []}]

    sanitized = request_messages(
        messages,
        preserve_reasoning_content=preserves_reasoning_content("mimo-v2.5-pro"),
    )

    assert sanitized[0]["reasoning_content"] == "private"
