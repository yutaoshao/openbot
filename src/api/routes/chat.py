"""Chat routes for REST API."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.background import BackgroundTask

from src.api.schemas import MAX_CHAT_MESSAGE_CHARS, ChatRequest, ChatResponse
from src.application.chat_runs import ChatRunConflictError, ChatRunManager
from src.core.user_scope import SINGLE_USER_ID

if TYPE_CHECKING:
    from src.agent.agent import Agent

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=MAX_CHAT_MESSAGE_CHARS)
    conversation_id: str | None = Field(default=None, max_length=200)
    request_id: uuid.UUID

    @field_validator("message")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value.strip()


def _get_runs(request: Request) -> ChatRunManager:
    manager = getattr(request.app.state, "chat_runs", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Chat execution is not initialized")
    return manager


def _run_response(manager: ChatRunManager, content: dict | list[dict]) -> JSONResponse:
    snapshots = content if isinstance(content, list) else [content]
    background = BackgroundTasks()
    for snapshot in snapshots:
        if snapshot["status"] == "completed" and snapshot["text"]:
            background.add_task(manager.confirm_delivery, snapshot["run_id"])
    return JSONResponse(content=content, background=background)


@router.post("/runs")
async def start_chat_run(payload: ChatRunRequest, request: Request) -> Response:
    manager = _get_runs(request)
    try:
        snapshot = manager.start(
            message=payload.message,
            conversation_id=payload.conversation_id or "",
            request_id=str(payload.request_id),
        )
        return _run_response(manager, snapshot)
    except ChatRunConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/runs")
async def list_chat_runs(
    request: Request, conversation_id: str | None = None, request_id: uuid.UUID | None = None
) -> Response:
    manager = _get_runs(request)
    return _run_response(
        manager,
        manager.list(conversation_id, str(request_id) if request_id is not None else None),
    )


@router.get("/runs/{run_id}")
async def get_chat_run(run_id: str, request: Request) -> Response:
    manager = _get_runs(request)
    try:
        snapshot = manager.get(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Chat run not found") from exc
    return _run_response(manager, snapshot)


@router.post("/runs/{run_id}/stop")
async def stop_chat_run(run_id: str, request: Request) -> Response:
    manager = _get_runs(request)
    try:
        return _run_response(manager, manager.stop(run_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Chat run not found") from exc


def _get_agent(request: Request) -> Agent:
    """Get Agent from app state or raise 503 when API is not wired."""
    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        raise HTTPException(
            status_code=503,
            detail="Agent is not initialized for API requests.",
        )
    return agent


@router.post("/requests/{request_id}/stop")
async def stop_chat_request(request_id: uuid.UUID, request: Request) -> Response:
    manager = _get_runs(request)
    return _run_response(manager, manager.stop_request(str(request_id)))


@router.post("", response_model=ChatResponse)
async def post_chat(
    payload: ChatRequest,
    request: Request,
    response: Response = None,
) -> ChatResponse | Response:
    """Run a single agent turn and return response payload."""
    agent = _get_agent(request)
    conversation_id = payload.conversation_id or uuid.uuid4().hex
    if not request.app.state.execution_coordinator.accepting:
        raise HTTPException(status_code=409, detail="The service is restarting")

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
