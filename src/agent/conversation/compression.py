"""Shared working-memory compression helpers for conversations."""

from __future__ import annotations

from typing import Any

from src.core.logging import get_logger
from src.core.user_scope import SINGLE_USER_ID

logger = get_logger(__name__)


async def maybe_compress_shared_timeline(
    shared_timeline: Any,
    model_gateway: Any,
    semantic_memory: Any,
    *,
    conversation_id: str,
) -> None:
    """Compress the shared timeline when it exceeds the token budget."""
    if shared_timeline is None or not shared_timeline.needs_compression():
        return
    logger.info(
        "conversation.compression_triggered",
        conversation_id=conversation_id,
        tokens_est=shared_timeline.estimate_tokens(),
    )
    try:
        extracted = await shared_timeline.extract_before_compression(model_gateway)
        for item in extracted:
            await semantic_memory.add_knowledge(
                user_id=SINGLE_USER_ID,
                category=item["category"],
                content=item["content"],
                priority="P1",
            )
    except Exception:
        logger.warning(
            "conversation.pre_compression_flush_failed",
            conversation_id=conversation_id,
            exc_info=True,
        )
    await shared_timeline.compress(model_gateway)
