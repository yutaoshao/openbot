"""Chat routes for REST API."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask

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
async def post_chat(
    payload: ChatRequest,
    request: Request,
    response: Response = None,
) -> ChatResponse | Response:
    """Run a single agent turn and return response payload."""
    agent = _get_agent(request)
    conversation_id = payload.conversation_id or uuid.uuid4().hex

    async with request.app.state.execution_coordinator.serialize(SINGLE_USER_ID):
        agent_response = await agent.run(
            input_text=payload.message,
            conversation_id=conversation_id,
            platform=payload.platform,
        )

    result = ChatResponse(
        reply=agent_response.content,
        conversation_id=conversation_id,
        model=agent_response.model,
        latency_ms=agent_response.latency_ms,
        tokens_in=agent_response.tokens_in,
        tokens_out=agent_response.tokens_out,
    )
    confirm = getattr(agent, "confirm_delivery", None)
    if response is not None and confirm is not None and agent_response.content:
        # Starlette runs this task after ASGI has sent the response body.
        return JSONResponse(
            content=result.model_dump(),
            background=BackgroundTask(
                confirm,
                conversation_id,
                agent_response.content,
                uuid.uuid4().hex,
            ),
        )
    return result
