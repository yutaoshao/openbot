"""Helper functions for conversation background memory flows."""

from __future__ import annotations

from typing import Any

from src.core.trace import TraceContext
from src.memory.message_format import render_llm_message
from src.memory.turn_selection import select_memory_batch


async def conversation_platform(storage: Any, conversation_id: str) -> str:
    conversation = await storage.conversations.get(conversation_id)
    if conversation is None:
        return ""
    return str(conversation.get("platform", ""))


async def pending_llm_messages(
    storage: Any,
    conversation_id: str,
    cursor: int,
) -> tuple[list[dict[str, Any]], int]:
    messages = await storage.messages.get_by_conversation(conversation_id)
    memory_batch = select_memory_batch(messages, cursor)
    return llm_messages(list(memory_batch.messages)), memory_batch.next_cursor


async def conversation_llm_messages(
    storage: Any,
    conversation_id: str,
) -> tuple[list[dict[str, Any]], int]:
    messages = await storage.messages.get_by_conversation(conversation_id)
    return llm_messages(messages), len(messages)


def llm_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        render_llm_message(
            {
                "role": item["role"],
                "content": item["content"],
                "timestamp": item["timestamp"],
            }
        )
        for item in messages
        if item.get("content")
    ]


def background_trace_scope(
    conversation_id: str,
    platform: str,
    *,
    trigger: str,
) -> TraceContext:
    return TraceContext(
        interaction_id=conversation_id,
        platform=platform,
        extra={"trigger": trigger},
    )
