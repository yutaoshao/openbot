"""Knowledge routes for REST API."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query, Request

from src.api.schemas import (
    KnowledgeCreateRequest,
    KnowledgeItem,
    KnowledgeUpdateRequest,
)
from src.core.user_scope import SINGLE_USER_ID

if TYPE_CHECKING:
    from src.infrastructure.storage import Storage

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


def _get_storage(request: Request) -> Storage:
    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        raise HTTPException(
            status_code=503,
            detail="Storage is not initialized for API requests.",
        )
    return storage


@router.get("", response_model=list[KnowledgeItem])
async def list_knowledge(
    request: Request,
    category: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[KnowledgeItem]:
    storage = _get_storage(request)
    items = await storage.knowledge.list_all(
        category=category,
        priority=priority,
        limit=limit,
        offset=offset,
    )
    return [KnowledgeItem(**item) for item in items]


@router.get("/search", response_model=list[KnowledgeItem])
async def search_knowledge(
    request: Request,
    q: str = Query(min_length=1),
    limit: int = Query(default=10, ge=1, le=100),
) -> list[KnowledgeItem]:
    storage = _get_storage(request)
    items = await storage.knowledge.search(q, limit=limit)
    return [KnowledgeItem(**item) for item in items]


@router.post("", response_model=KnowledgeItem, status_code=201)
async def create_knowledge(
    payload: KnowledgeCreateRequest,
    request: Request,
) -> KnowledgeItem:
    storage = _get_storage(request)
    knowledge_id = uuid.uuid4().hex

    await storage.knowledge.add(
        id=knowledge_id,
        user_id=SINGLE_USER_ID,
        category=payload.category,
        content=payload.content,
        tags=payload.tags,
        priority=payload.priority,
        confidence=payload.confidence,
        source_conversation_id=payload.source_conversation_id,
        expires_at=payload.expires_at,
    )
    created = await storage.knowledge.get(knowledge_id)
    if created is None:
        raise HTTPException(status_code=500, detail="Failed to create knowledge")
    return KnowledgeItem(**created)


@router.put("/{knowledge_id}", response_model=KnowledgeItem)
async def update_knowledge(
    knowledge_id: str,
    payload: KnowledgeUpdateRequest,
    request: Request,
) -> KnowledgeItem:
    storage = _get_storage(request)
    existing = await storage.knowledge.get(knowledge_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Knowledge item not found")

    update_fields = payload.model_dump(exclude_none=True)
    await storage.knowledge.update(knowledge_id, **update_fields)
    updated = await storage.knowledge.get(knowledge_id)
    if updated is None:
        raise HTTPException(status_code=500, detail="Failed to update knowledge")
    return KnowledgeItem(**updated)


@router.delete("/{knowledge_id}")
async def delete_knowledge(
    knowledge_id: str,
    request: Request,
) -> dict[str, str]:
    storage = _get_storage(request)
    existing = await storage.knowledge.get(knowledge_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Knowledge item not found")
    await storage.knowledge.delete(knowledge_id)
    return {"status": "deleted", "knowledge_id": knowledge_id}
