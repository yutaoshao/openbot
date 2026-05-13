"""Conversation history file reference helpers."""

from __future__ import annotations

from datetime import UTC, datetime, tzinfo
from typing import Any


def history_file_references(messages: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for message in messages:
        timestamp = message.get("timestamp")
        if timestamp in (None, ""):
            continue
        ref = _reference_for_timestamp(timestamp)
        if ref not in seen:
            refs.append(ref)
            seen.add(ref)
    return refs


def _reference_for_timestamp(value: datetime | str) -> str:
    ts = _parse_timestamp(value).astimezone(_local_timezone())
    return f"完整历史见 data/conversations/{ts:%Y}/{ts:%m}/{ts:%d}.jsonl"


def _parse_timestamp(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("message timestamp must be timezone-aware")
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError("message timestamp is required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("message timestamp must be timezone-aware")
    return parsed


def _local_timezone() -> tzinfo:
    return datetime.now().astimezone().tzinfo or UTC
