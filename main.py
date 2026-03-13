"""OpenBot application entrypoint.

Wires all layers together and starts the agent service.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
from pathlib import Path
from typing import Any

from src.agent.agent import Agent
from src.channels.adapters.telegram import TelegramAdapter
from src.channels.hub import MsgHub
from src.channels.models import MessageContent
from src.infrastructure.event_bus import EventBus
from src.infrastructure.model_gateway import ModelGateway
from src.platform.config import load_config
from src.platform.logging import get_logger, setup_logging

logger = get_logger(__name__)


class Application:
    """Main application orchestrator."""

    def __init__(self) -> None:
        self.config = load_config()
        self._shutdown_event = asyncio.Event()

        # Infrastructure layer
        self.event_bus = EventBus()
        self.model_gateway = ModelGateway(self.config.model, self.event_bus)

        # Core layer
        self.agent = Agent(self.model_gateway, self.event_bus, self.config.agent)

        # Application layer
        self.msg_hub = MsgHub(self.event_bus)
        self.telegram: TelegramAdapter | None = None

        # Wire up events
        self.event_bus.subscribe("msg.receive", self._on_message_receive)

    async def _on_message_receive(self, data: dict[str, Any]) -> None:
        """Handle incoming message: run agent and publish response."""
        message = data["message"]
        input_text = message.content.text

        if not input_text:
            return

        logger.info(
            "app.processing",
            platform=message.platform,
            sender=message.sender_id,
            text_preview=input_text[:50],
        )

        try:
            result = await self.agent.run(
                input_text=input_text,
                conversation_id=message.conversation_id,
            )

            await self.event_bus.publish("agent.response", {
                "platform": message.platform,
                "target_id": message.conversation_id,
                "content": MessageContent(text=result.content),
                "latency_ms": result.latency_ms,
                "tokens_in": result.tokens_in,
                "tokens_out": result.tokens_out,
                "cost": result.cost,
            })

            logger.info(
                "app.response_sent",
                platform=message.platform,
                latency_ms=result.latency_ms,
                tokens=f"{result.tokens_in}/{result.tokens_out}",
                cost=f"${result.cost:.4f}",
            )

        except Exception:
            logger.exception("app.agent_error", conversation_id=message.conversation_id)
            await self.event_bus.publish("agent.response", {
                "platform": message.platform,
                "target_id": message.conversation_id,
                "content": MessageContent(text="Sorry, an error occurred. Please try again."),
            })

    async def start(self) -> None:
        """Start all services."""
        logger.info("app.starting")

        # Ensure data directory exists
        db_dir = Path(self.config.storage.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        # Start Telegram adapter
        if self.config.telegram.bot_token:
            self.telegram = TelegramAdapter(self.config.telegram, self.msg_hub)
            self.msg_hub.register_adapter("telegram", self.telegram)
            await self.telegram.start()
            logger.info("app.telegram_ready")
        else:
            logger.warning("app.telegram_skipped", reason="no bot token configured")

        logger.info("app.started")

    async def stop(self) -> None:
        """Gracefully stop all services."""
        logger.info("app.stopping")

        if self.telegram:
            await self.telegram.stop()

        logger.info("app.stopped")

    async def run_forever(self) -> None:
        """Run until shutdown signal."""
        await self.start()

        # Register signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._shutdown_event.set)

        logger.info("app.running", message="Press Ctrl+C to stop")
        await self._shutdown_event.wait()

        await self.stop()


def main() -> None:
    """Application entrypoint."""
    # Pre-load config for logging setup
    config = load_config()
    setup_logging(level=config.log.level, fmt=config.log.format)

    app = Application()

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(app.run_forever())

    logger.info("app.exit")


if __name__ == "__main__":
    main()
