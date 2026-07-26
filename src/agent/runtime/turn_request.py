"""Immutable input for one agent runtime turn."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True, kw_only=True)
class TurnRequest:
    """All transport-owned fields needed to execute one turn."""

    input_text: str
    conversation_id: str
    platform: str
    user_id: str
    message_timestamp: datetime
    source_message_id: str = ""
    platform_user_id: str = ""
