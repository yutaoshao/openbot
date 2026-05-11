"""Formatting helpers for LLM-visible chat messages."""

from __future__ import annotations

from datetime import UTC, datetime, tzinfo
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

_TIMESTAMPED_ROLES = {"user", "assistant"}


def render_llm_message(message: Mapping[str, Any]) -> dict[str, Any]:
    """Return a provider-safe message with timestamp rendered into content."""
    role = str(message.get("role", ""))
    rendered = {key: value for key, value in message.items() if key != "timestamp"}
    if role in _TIMESTAMPED_ROLES:
        rendered["content"] = timestamped_content(message)
    return rendered


def timestamped_content(message: Mapping[str, Any]) -> str:
    """Render chat content with its message event timestamp."""
    content = str(message.get("content") or "")
    timestamp = message.get("timestamp")
    if timestamp is None or timestamp == "":
        raise ValueError("message timestamp is required")
    return f"[{format_message_timestamp(timestamp)}] {content}"


def format_message_timestamp(value: datetime | str) -> str:
    """Format a timestamp for compact display in LLM-visible context."""
    parsed = _parse_timestamp(value)
    return parsed.astimezone(_local_timezone()).strftime("%Y-%m-%d %H:%M")


def _parse_timestamp(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("message timestamp must be timezone-aware")
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError("message timestamp is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid message timestamp: {value}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("message timestamp must be timezone-aware")
    return parsed


def _local_timezone() -> tzinfo:
    return datetime.now().astimezone().tzinfo or UTC
