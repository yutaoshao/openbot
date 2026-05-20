"""Assemble LLM messages for one agent turn."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.memory.message_format import render_llm_message, strip_internal_timestamp_prefixes

if TYPE_CHECKING:
    from datetime import datetime


def assemble_turn_messages(
    system_prompt: str,
    protected_messages: list[dict[str, str]],
    history_messages: list[dict[str, Any]],
    current_user_content: str,
    current_user_timestamp: datetime | None,
) -> list[dict[str, Any]]:
    """Return system, protected context, history, then the current user turn."""
    current_user = _current_user_message(current_user_content, current_user_timestamp)
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    messages.extend(protected_messages)
    messages.extend(history_messages)
    if not _ends_with_same_user_turn(history_messages, current_user_content):
        messages.append(current_user)
    return messages


def _current_user_message(content: str, timestamp: datetime | None) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "user", "content": content}
    if timestamp is None:
        return message
    return render_llm_message({**message, "timestamp": timestamp})


def _ends_with_same_user_turn(messages: list[dict[str, Any]], content: str) -> bool:
    if not messages:
        return False
    last = messages[-1]
    if last.get("role") != "user":
        return False
    return _normal_content(last.get("content")) == _normal_content(content)


def _normal_content(value: object) -> str:
    return strip_internal_timestamp_prefixes(str(value or "")).strip()
