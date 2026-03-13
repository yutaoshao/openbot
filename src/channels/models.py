"""Unified message models for cross-platform communication.

All platform adapters convert their native message format to/from these models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


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
