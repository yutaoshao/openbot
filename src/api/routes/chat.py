"""Chat routes for REST API."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request

from src.api.schemas import ChatRequest, ChatResponse
from src.core.user_scope import SINGLE_USER_ID

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

    async with request.app.state.execution_coordinator.serialize(SINGLE_USER_ID):
        agent_response = await agent.run(
            input_text=payload.message,
            conversation_id=conversation_id,
            platform=payload.platform,
        )

    return ChatResponse(
        reply=agent_response.content,
        conversation_id=conversation_id,
        model=agent_response.model,
        latency_ms=agent_response.latency_ms,
        tokens_in=agent_response.tokens_in,
        tokens_out=agent_response.tokens_out,
    )
