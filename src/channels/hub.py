"""Message Hub - central router for all platform messages.

Routes incoming messages to Agent via Event Bus.
Routes Agent responses back to the originating platform adapter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.channels.models import MessageContent, UnifiedMessage
from src.platform.logging import get_logger

if TYPE_CHECKING:
    from src.infrastructure.event_bus import EventBus

logger = get_logger(__name__)


class MsgHub:
    """Central message router connecting platform adapters to Agent Core."""

    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus
        self._adapters: dict[str, Any] = {}  # platform_name -> adapter instance

        # Subscribe to agent response events
        event_bus.subscribe("agent.response", self._on_agent_response)

    def register_adapter(self, platform: str, adapter: Any) -> None:
        """Register a platform adapter."""
        self._adapters[platform] = adapter
        logger.info("msg_hub.adapter_registered", platform=platform)

    async def handle_incoming(self, message: UnifiedMessage) -> None:
        """Handle an incoming message from any platform.

        Publishes msg.receive event -> Agent Core picks it up.
        """
        await self.event_bus.publish("msg.receive", {
            "message": message,
            "platform": message.platform,
            "sender_id": message.sender_id,
            "conversation_id": message.conversation_id,
        })

    async def _on_agent_response(self, data: dict[str, Any]) -> None:
        """Route agent's response back to the originating platform."""
        platform = data.get("platform", "")
        target_id = data.get("target_id", "")
        content = data.get("content")

        if not platform or not target_id:
            logger.error("msg_hub.missing_routing_info", data=data)
            return

        adapter = self._adapters.get(platform)
        if not adapter:
            logger.error("msg_hub.adapter_not_found", platform=platform)
            return

        if isinstance(content, str):
            content = MessageContent(text=content)
        elif not isinstance(content, MessageContent):
            logger.error("msg_hub.invalid_content_type", type=type(content).__name__)
            return

        try:
            await adapter.send_message(target_id, content)
            logger.info("msg_hub.message_sent", platform=platform, target_id=target_id)
        except Exception:
            logger.exception("msg_hub.send_failed", platform=platform, target_id=target_id)
