"""Message write helpers for conversation timelines."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.agent.conversation.journal import ConversationJournalEntry
from src.core.trace import current_trace
from src.core.user_scope import CHAT_MEMORY_PLATFORMS
from src.memory.message_format import strip_internal_timestamp_prefixes

if TYPE_CHECKING:
    from datetime import datetime

    from src.agent.conversation.journal import ConversationJournal
    from src.agent.conversation.shared_timeline import SharedTimelineMemory
    from src.agent.conversation.task_state_store import TaskStateStore
    from src.infrastructure.storage import Storage


@dataclass(frozen=True)
class UserMessageArchiveMetadata:
    source_message_id: str = ""
    platform_user_id: str = ""
    user_id: str = ""


@dataclass(frozen=True)
class MessageWriteContext:
    storage: Storage
    task_store: TaskStateStore
    shared_timeline: SharedTimelineMemory | None
    journal: ConversationJournal | None = None


async def store_user_message(
    context: MessageWriteContext,
    *,
    conversation_id: str,
    content: str,
    timestamp: datetime,
    archive_metadata: UserMessageArchiveMetadata | None = None,
) -> None:
    metadata = archive_metadata or UserMessageArchiveMetadata()
    storage_message_id = uuid.uuid4().hex
    context.task_store.note_user_input(conversation_id, content)
    await _append_to_shared_timeline(
        context,
        conversation_id=conversation_id,
        message={"role": "user", "content": content, "timestamp": timestamp},
    )
    await context.storage.messages.add(
        id=storage_message_id,
        conversation_id=conversation_id,
        role="user",
        content=content,
        timestamp=timestamp,
    )
    await _append_user_journal(
        context,
        conversation_id=conversation_id,
        content=content,
        timestamp=timestamp,
        storage_message_id=storage_message_id,
        metadata=metadata,
    )


async def store_assistant_message(
    context: MessageWriteContext,
    *,
    conversation_id: str,
    content: str,
    timestamp: datetime,
    metadata: dict[str, Any],
) -> None:
    storage_message_id = uuid.uuid4().hex
    clean_content = strip_internal_timestamp_prefixes(content)
    context.task_store.note_assistant_reply(conversation_id, clean_content)
    await _append_to_shared_timeline(
        context,
        conversation_id=conversation_id,
        message={"role": "assistant", "content": clean_content, "timestamp": timestamp},
    )
    await context.storage.messages.add(
        id=storage_message_id,
        conversation_id=conversation_id,
        role="assistant",
        content=clean_content,
        timestamp=timestamp,
        **metadata,
    )
    await _append_assistant_journal(
        context,
        conversation_id=conversation_id,
        content=clean_content,
        timestamp=timestamp,
        storage_message_id=storage_message_id,
        metadata=metadata,
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


async def _append_user_journal(
    context: MessageWriteContext,
    *,
    conversation_id: str,
    content: str,
    timestamp: datetime,
    storage_message_id: str,
    metadata: UserMessageArchiveMetadata,
) -> None:
    if context.journal is None:
        return
    conversation = await context.storage.conversations.get(conversation_id)
    channel, conversation_user_id = _conversation_fields(conversation)
    context.journal.append(
        ConversationJournalEntry(
            ts=timestamp,
            role="user",
            content=content,
            channel=channel,
            conversation_id=conversation_id,
            message_id=metadata.source_message_id or storage_message_id,
            stored_message_id=storage_message_id,
            user_id=metadata.user_id or conversation_user_id,
            platform_user_id=metadata.platform_user_id,
        )
    )


async def _append_assistant_journal(
    context: MessageWriteContext,
    *,
    conversation_id: str,
    content: str,
    timestamp: datetime,
    storage_message_id: str,
    metadata: dict[str, Any],
) -> None:
    if context.journal is None:
        return
    conversation = await context.storage.conversations.get(conversation_id)
    channel, conversation_user_id = _conversation_fields(conversation)
    trace = current_trace()
    context.journal.append(
        ConversationJournalEntry(
            ts=timestamp,
            role="assistant",
            content=content,
            channel=channel,
            conversation_id=conversation_id,
            message_id=storage_message_id,
            user_id=conversation_user_id,
            model=str(metadata.get("model") or ""),
            trace_id=trace.trace_id if trace else "",
            tokens_in=metadata.get("tokens_in"),
            tokens_out=metadata.get("tokens_out"),
            latency_ms=metadata.get("latency_ms"),
            tool_calls=metadata.get("tool_calls"),
        )
    )


def _conversation_fields(conversation: dict[str, Any] | None) -> tuple[str, str]:
    if conversation is None:
        return "", ""
    return str(conversation.get("platform", "")), str(conversation.get("user_id", ""))
