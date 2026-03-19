"""Chat routes for REST API."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request

from src.api.schemas import ChatRequest, ChatResponse

if TYPE_CHECKING:
    from src.agent.agent import Agent

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _get_agent(request: Request) -> Agent:
    """Get Agent from app state or raise 503 when API is not wired."""
    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        raise HTTPException(
            status_code=503,
            detail="Agent is not initialized for API requests.",
        )
    return agent


@router.post("", response_model=ChatResponse)
async def post_chat(payload: ChatRequest, request: Request) -> ChatResponse:
    """Run a single agent turn and return response payload."""
    agent = _get_agent(request)
    conversation_id = payload.conversation_id or uuid.uuid4().hex

    result = await agent.run(
        input_text=payload.message,
        conversation_id=conversation_id,
        platform=payload.platform,
    )

    return ChatResponse(
        reply=result.content,
        conversation_id=conversation_id,
        model=result.model,
        latency_ms=result.latency_ms,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        cost=result.cost,
    )
