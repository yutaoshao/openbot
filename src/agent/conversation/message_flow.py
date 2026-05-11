"""Message write helpers for conversation timelines."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.core.user_scope import CHAT_MEMORY_PLATFORMS
from src.memory.message_format import strip_internal_timestamp_prefixes

if TYPE_CHECKING:
    from datetime import datetime

    from src.agent.conversation.shared_timeline import SharedTimelineMemory
    from src.agent.conversation.task_state_store import TaskStateStore
    from src.infrastructure.storage import Storage


@dataclass(frozen=True)
class MessageWriteContext:
    storage: Storage
    task_store: TaskStateStore
    shared_timeline: SharedTimelineMemory | None


async def store_user_message(
    context: MessageWriteContext,
    *,
    conversation_id: str,
    content: str,
    timestamp: datetime,
) -> None:
    context.task_store.note_user_input(conversation_id, content)
    await _append_to_shared_timeline(
        context,
        conversation_id=conversation_id,
        message={"role": "user", "content": content, "timestamp": timestamp},
    )
    await context.storage.messages.add(
        id=uuid.uuid4().hex,
        conversation_id=conversation_id,
        role="user",
        content=content,
        timestamp=timestamp,
    )


async def store_assistant_message(
    context: MessageWriteContext,
    *,
    conversation_id: str,
    content: str,
    timestamp: datetime,
    metadata: dict[str, Any],
) -> None:
    clean_content = strip_internal_timestamp_prefixes(content)
    context.task_store.note_assistant_reply(conversation_id, clean_content)
    await _append_to_shared_timeline(
        context,
        conversation_id=conversation_id,
        message={"role": "assistant", "content": clean_content, "timestamp": timestamp},
    )
    await context.storage.messages.add(
        id=uuid.uuid4().hex,
        conversation_id=conversation_id,
        role="assistant",
        content=clean_content,
        timestamp=timestamp,
        **metadata,
    )


async def _append_to_shared_timeline(
    context: MessageWriteContext,
    *,
    conversation_id: str,
    message: dict[str, Any],
) -> None:
    if context.shared_timeline is None:
        return
    conversation = await context.storage.conversations.get(conversation_id)
    platform = str(conversation.get("platform", "")) if conversation else ""
    if platform in CHAT_MEMORY_PLATFORMS:
        context.shared_timeline.add(message)
