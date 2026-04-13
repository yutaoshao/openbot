"""WebSocket platform adapter for browser clients."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from src.core.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from starlette.websockets import WebSocket

    from src.channels.types import MessageContent
    from src.infrastructure.model_gateway import StreamChunk

logger = get_logger(__name__)


class WebAdapter:
    """WebSocket adapter registered under platform ``web``."""

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()

    async def register(self, conversation_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections[conversation_id] = websocket
        logger.info("web.adapter_connected", conversation_id=conversation_id)

    async def unregister(self, conversation_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            current = self._connections.get(conversation_id)
            if current is websocket:
                self._connections.pop(conversation_id, None)
        logger.info("web.adapter_disconnected", conversation_id=conversation_id)

    async def send_message(self, chat_id: str, content: MessageContent) -> None:
        websocket = await self._get(chat_id)
        if websocket is None:
            logger.warning("web.adapter_send_no_client", conversation_id=chat_id)
            return
        await websocket.send_json(
            {
                "type": "message",
                "conversation_id": chat_id,
                "text": content.text or "",
                "attachments": [
                    {
                        "type": item.type,
                        "filename": item.filename,
                        "mime_type": item.mime_type,
                    }
                    for item in content.attachments
                ],
            }
        )

    async def send_streaming(
        self,
        chat_id: str,
        stream: AsyncIterator[StreamChunk],
    ) -> None:
        websocket = await self._get(chat_id)
        if websocket is None:
            logger.warning("web.adapter_stream_no_client", conversation_id=chat_id)
            # Drain stream to allow agent to complete
            async for _ in stream:
                pass
            return

        try:
            async for chunk in stream:
                payload: dict[str, Any] = {
                    "conversation_id": chat_id,
                    "chunk_type": chunk.type,
                }
                if chunk.type == "text":
                    payload["text"] = chunk.text
                elif chunk.type == "tool_status":
                    payload["tool_name"] = chunk.tool_name
                elif chunk.type == "done":
                    payload["usage"] = (
                        {
                            "tokens_in": chunk.usage.tokens_in,
                            "tokens_out": chunk.usage.tokens_out,
                        }
                        if chunk.usage
                        else None
                    )
                    payload["model"] = chunk.model
                await websocket.send_json(payload)
        except Exception:
            logger.warning(
                "web.adapter_stream_interrupted",
                conversation_id=chat_id,
            )
            # Drain remaining stream so agent loop completes gracefully
            async for _ in stream:
                pass

    async def _get(self, conversation_id: str) -> WebSocket | None:
        async with self._lock:
            return self._connections.get(conversation_id)
