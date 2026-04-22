"""WebSocket handlers for API streaming chat."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.api.local_access import websocket_requires_local_access
from src.channels.types import MessageContent, UnifiedMessage
from src.core.logging import get_logger

if TYPE_CHECKING:
    from src.channels.adapters.web import WebAdapter
    from src.channels.hub import MsgHub

logger = get_logger(__name__)

router = APIRouter(prefix="/api/ws", tags=["ws"])


def _state_or_none(websocket: WebSocket, name: str):
    return getattr(websocket.app.state, name, None)


@router.websocket("/chat")
async def ws_chat(
    websocket: WebSocket,
    conversation_id: str | None = None,
    sender_id: str = "web-user",
) -> None:
    """WebSocket chat endpoint.

    Client sends JSON payload:
    ``{"message": "..."}``

    Server streams back JSON chunks via ``WebAdapter.send_streaming()``.
    """
    if websocket_requires_local_access(websocket):
        await websocket.close(code=1008, reason="local-only")
        return

    await websocket.accept()

    msg_hub: MsgHub | None = _state_or_none(websocket, "msg_hub")
    web_adapter: WebAdapter | None = _state_or_none(websocket, "web_adapter")

    if msg_hub is None or web_adapter is None:
        await websocket.send_json({"type": "error", "detail": "WebSocket chat is not initialized."})
        await websocket.close(code=1011)
        return

    conv_id = conversation_id or uuid.uuid4().hex
    await web_adapter.register(conv_id, websocket)

    await websocket.send_json(
        {
            "type": "connected",
            "conversation_id": conv_id,
        }
    )

    try:
        while True:
            payload = await websocket.receive_json()
            text = (payload.get("message") or "").strip()
            if not text:
                await websocket.send_json(
                    {
                        "type": "error",
                        "conversation_id": conv_id,
                        "detail": "message is required",
                    }
                )
                continue

            msg = UnifiedMessage(
                id=uuid.uuid4().hex,
                platform="web",
                sender_id=str(payload.get("sender_id") or sender_id),
                conversation_id=conv_id,
                content=MessageContent(text=text),
            )
            await msg_hub.handle_incoming(msg)

    except WebSocketDisconnect:
        logger.info("ws.chat_disconnected", conversation_id=conv_id)
    finally:
        await web_adapter.unregister(conv_id, websocket)
