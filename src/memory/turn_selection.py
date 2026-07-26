"""Persistent failure facts and long-term-memory turn selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

TURN_FAILURE_METADATA_KEY = "turn_failure"
TURN_FAILURE_REASON_KEY = "reason"


@dataclass(frozen=True, kw_only=True)
class MemoryBatch:
    """Eligible closed messages and the durable cursor they cover."""

    messages: tuple[dict[str, Any], ...]
    next_cursor: int


def turn_failure_metadata(reason: str) -> dict[str, dict[str, str]]:
    """Build the durable fact attached only to failed assistant messages."""
    if not reason:
        raise ValueError("turn failure reason must not be empty")
    return {TURN_FAILURE_METADATA_KEY: {TURN_FAILURE_REASON_KEY: reason}}


def select_memory_batch(
    messages: list[dict[str, Any]],
    cursor: int,
) -> MemoryBatch:
    """Consume adjacent user/assistant pairs without crossing an open turn."""
    if cursor < 0 or cursor > len(messages):
        raise ValueError(f"memory cursor out of range: {cursor}")
    selected_messages: list[dict[str, Any]] = []
    next_cursor = cursor
    while next_cursor < len(messages):
        user_message = messages[next_cursor]
        if user_message.get("role") != "user":
            raise ValueError(f"expected user message at memory cursor {next_cursor}")
        if next_cursor + 1 == len(messages):
            break
        assistant_message = messages[next_cursor + 1]
        if assistant_message.get("role") == "user":
            next_cursor += 1
            continue
        if assistant_message.get("role") != "assistant":
            raise ValueError(f"expected assistant message after cursor {next_cursor}")
        if not _is_failed_assistant(assistant_message):
            selected_messages.extend((user_message, assistant_message))
        next_cursor += 2
    return MemoryBatch(
        messages=tuple(selected_messages),
        next_cursor=next_cursor,
    )


def select_long_term_memory_prefix(
    messages: list[dict[str, Any]],
    prefix_length: int,
) -> MemoryBatch:
    """Select eligible complete pairs wholly contained in a compression prefix."""
    if prefix_length < 0 or prefix_length > len(messages):
        raise ValueError(f"memory prefix out of range: {prefix_length}")
    selected_messages: list[dict[str, Any]] = []
    cursor = 0
    while cursor < prefix_length:
        user_message = messages[cursor]
        if user_message.get("role") != "user":
            cursor += 1
            continue
        if cursor + 1 >= prefix_length:
            break
        assistant_message = messages[cursor + 1]
        if assistant_message.get("role") == "user":
            cursor += 1
            continue
        if assistant_message.get("role") != "assistant":
            raise ValueError(f"unexpected timeline role at index {cursor + 1}")
        if not _is_failed_assistant(assistant_message):
            selected_messages.extend((user_message, assistant_message))
        cursor += 2
    return MemoryBatch(messages=tuple(selected_messages), next_cursor=cursor)


def _is_failed_assistant(message: dict[str, Any]) -> bool:
    metadata = message.get("metadata")
    if metadata is None:
        return False
    if not isinstance(metadata, dict):
        raise TypeError("message metadata must be a mapping")
    failure = metadata.get(TURN_FAILURE_METADATA_KEY)
    if failure is None:
        return False
    if not isinstance(failure, dict):
        raise TypeError("turn failure metadata must be a mapping")
    reason = failure.get(TURN_FAILURE_REASON_KEY)
    if not isinstance(reason, str) or not reason:
        raise ValueError("turn failure metadata requires a non-empty reason")
    return True
