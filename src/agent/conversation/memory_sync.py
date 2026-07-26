"""Long-term memory synchronization for completed conversation turns."""

from __future__ import annotations

from typing import Any

from src.core.logging import get_logger
from src.core.user_scope import SINGLE_USER_ID

from .archive_helpers import pending_llm_messages

logger = get_logger(__name__)


async def sync_eligible_long_term_memory(
    *,
    storage: Any,
    semantic_memory: Any,
    procedural_memory: Any,
    conversation_id: str,
    cursor: int,
) -> int:
    """Extract eligible messages and return the durable-message cursor."""
    llm_messages, next_cursor = await pending_llm_messages(
        storage,
        conversation_id,
        cursor,
    )
    if next_cursor == cursor:
        logger.info(
            "conversation.memory_sync_skipped",
            conversation_id=conversation_id,
            reason="no_new_messages",
        )
        return cursor
    if not llm_messages:
        logger.info(
            "conversation.memory_sync_skipped",
            conversation_id=conversation_id,
            reason="failed_turns_only",
        )
        return next_cursor
    await semantic_memory.extract_knowledge(
        llm_messages,
        conversation_id,
        SINGLE_USER_ID,
    )
    await procedural_memory.observe(
        llm_messages,
        conversation_id,
        SINGLE_USER_ID,
    )
    logger.info(
        "conversation.memory_synced",
        conversation_id=conversation_id,
        user_id=SINGLE_USER_ID,
        message_count=next_cursor,
    )
    return next_cursor
