"""Conversation routes for REST API."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query, Request

from src.api.schemas import ConversationDetail, ConversationSummary, MessageItem

if TYPE_CHECKING:
    from src.infrastructure.storage import Storage

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


def _get_storage(request: Request) -> Storage:
    """Get Storage from app state or raise 503 when API is not wired."""
    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        raise HTTPException(
            status_code=503,
            detail="Storage is not initialized for API requests.",
        )
    return storage


def _to_conversation_summary(
    row: dict,
    *,
    message_count: int,
) -> ConversationSummary:
    return ConversationSummary(
        id=row["id"],
        title=row.get("title"),
        summary=row.get("summary"),
        platform=row.get("platform", "unknown"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        message_count=message_count,
    )


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    q: str | None = Query(default=None, min_length=1),
) -> list[ConversationSummary]:
    """List recent conversations with optional text search."""
    storage = _get_storage(request)

    if q:
        # Search API has no offset. Fetch larger window then slice locally.
        rows = await storage.conversations.search(q, limit=limit + offset)
        rows = rows[offset : offset + limit]
    else:
        rows = await storage.conversations.list_recent(limit=limit, offset=offset)

    # Batch count to avoid N+1 queries
    conv_ids = [row["id"] for row in rows]
    counts = await storage.messages.count_by_conversations(conv_ids)

    result: list[ConversationSummary] = []
    for row in rows:
        count = counts.get(row["id"], 0)
        result.append(_to_conversation_summary(row, message_count=count))
    return result


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation_detail(
    conversation_id: str,
    request: Request,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> ConversationDetail:
    """Get one conversation and its messages."""
    storage = _get_storage(request)

    conv = await storage.conversations.get(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = await storage.messages.get_by_conversation(
        conversation_id,
        limit=limit,
        offset=offset,
    )
    count = await storage.messages.count_by_conversation(conversation_id)

    return ConversationDetail(
        conversation=_to_conversation_summary(conv, message_count=count),
        messages=[MessageItem(**item) for item in messages],
    )


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    request: Request,
) -> dict[str, str]:
    """Delete a conversation and all its messages."""
    storage = _get_storage(request)

    conv = await storage.conversations.get(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    await storage.conversations.delete(conversation_id)
    return {"status": "deleted", "conversation_id": conversation_id}
