"""Unified message models for cross-core communication.

All core adapters convert their native message format to/from these models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from src.infrastructure.model_gateway import StreamChunk


@dataclass
class Attachment:
    """A file or media attachment."""

    type: str  # "image" | "file" | "code" | "audio"
    data: bytes | str  # binary data or URL
    filename: str | None = None
    mime_type: str | None = None


@dataclass
class MessageContent:
    """Unified message content supporting text and attachments."""

    text: str | None = None
    attachments: list[Attachment] = field(default_factory=list)


@dataclass
class UnifiedMessage:
    """Platform-agnostic message representation."""

    id: str
    platform: str  # "telegram" | "feishu" | "web"
    sender_id: str
    conversation_id: str
    content: MessageContent
    reply_to: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@runtime_checkable
class StreamingAdapter(Protocol):
    """Protocol for adapters that support streaming output."""

    async def send_streaming(
        self,
        chat_id: str,
        stream: AsyncIterator[StreamChunk],
    ) -> None: ...
