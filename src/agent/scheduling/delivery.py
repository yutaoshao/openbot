"""Delivery helpers for scheduled task results."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.agent.scheduling.delivery_policy import assert_supported_schedule_target
from src.channels.types import MessageContent

if TYPE_CHECKING:
    from src.channels.hub import MsgHub


async def deliver_schedule_result(
    msg_hub: MsgHub,
    *,
    schedule_id: str,
    target_platform: str | None,
    target_id: str | None,
    content: str,
) -> None:
    """Deliver scheduled task output to its configured target when present."""
    if not target_platform or not target_id:
        return

    assert_supported_schedule_target(target_platform, target_id=target_id)
    adapter = msg_hub.get_adapter(target_platform)
    if adapter:
        await adapter.send_message(target_id, MessageContent(text=content))
