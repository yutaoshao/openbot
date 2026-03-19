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
from src.agent.conversation import ConversationManager
from src.channels.adapters.telegram import TelegramAdapter
from src.channels.hub import MsgHub
from src.channels.types import MessageContent, StreamingAdapter
from src.core.config import load_config
from src.core.logging import get_logger, setup_logging
from src.infrastructure.database import Database
from src.infrastructure.embedding import EmbeddingService, NullEmbeddingService
from src.infrastructure.event_bus import EventBus
from src.infrastructure.model_gateway import ModelGateway
from src.infrastructure.reranker import NullRerankerService, RerankerService
from src.infrastructure.storage import Storage
from src.memory.episodic import EpisodicMemory
from src.memory.procedural import ProceduralMemory
from src.memory.semantic import SemanticMemory
from src.tools.builtin import CodeExecutorTool, FileManagerTool, WebFetchTool, WebSearchTool
from src.tools.registry import ToolRegistry

logger = get_logger(__name__)


class Application:
    """Main application orchestrator."""

    def __init__(self) -> None:
        self.config = load_config()
        self._shutdown_event = asyncio.Event()

        # Infrastructure layer
        self.event_bus = EventBus()
        self.model_gateway = ModelGateway(self.config.model, self.event_bus)
        self.database = Database(self.config.storage)
        self.storage = Storage(self.database)

        # Embedding service
        if self.config.embedding.enabled:
            self.embedding_service = EmbeddingService(self.config.embedding)
        else:
            self.embedding_service = NullEmbeddingService()

        # Reranker service
        if self.config.reranker.enabled:
            self.reranker_service = RerankerService(self.config.reranker)
        else:
            self.reranker_service = NullRerankerService()

        # Tool layer
        self.tool_registry = ToolRegistry()
        self._register_builtin_tools()

        # Memory layer
        self.semantic_memory = SemanticMemory(
            self.storage, self.model_gateway,
            self.embedding_service, self.database,
            self.reranker_service,
        )
        self.episodic_memory = EpisodicMemory(
            self.storage, self.model_gateway,
            self.embedding_service, self.database,
            self.reranker_service,
        )
        self.procedural_memory = ProceduralMemory(
            self.storage, self.model_gateway,
        )
        self.conversation_manager = ConversationManager(
            self.storage, self.model_gateway,
            self.semantic_memory, self.episodic_memory,
            self.procedural_memory,
        )

        # Core layer
        self.agent = Agent(
            model_gateway=self.model_gateway,
            event_bus=self.event_bus,
            config=self.config.agent,
            tool_registry=self.tool_registry,
            conversation_manager=self.conversation_manager,
        )

        # Application layer
        self.msg_hub = MsgHub(self.event_bus)
        self.telegram: TelegramAdapter | None = None

        # Wire up events
        self.event_bus.subscribe("msg.receive", self._on_message_receive)

    def _register_builtin_tools(self) -> None:
        """Register all built-in tools."""
        self.tool_registry.register(WebSearchTool())
        self.tool_registry.register(WebFetchTool())
        self.tool_registry.register(CodeExecutorTool())
        self.tool_registry.register(FileManagerTool(workspace=Path("/Users/yutaoshao/Project/openbot")))

    async def _on_message_receive(self, data: dict[str, Any]) -> None:
        """Handle incoming message: run agent and publish response.

        Uses streaming path when the adapter supports it, otherwise
        falls back to the non-streaming ``Agent.run()`` path.
        """
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

        adapter = self.msg_hub.get_adapter(message.platform)

        try:
            if self.config.telegram.enable_streaming and isinstance(adapter, StreamingAdapter):
                await self._handle_streaming(message, adapter)
            else:
                await self._handle_non_streaming(message)

        except Exception:
            logger.exception(
                "app.agent_error",
                conversation_id=message.conversation_id,
            )
            await self.event_bus.publish("agent.response", {
                "platform": message.platform,
                "target_id": message.conversation_id,
                "content": MessageContent(
                    text="Sorry, an error occurred. Please try again.",
                ),
            })

    async def _handle_streaming(
        self, message: Any, adapter: StreamingAdapter,
    ) -> None:
        """Streaming path: Agent.run_stream() -> adapter.send_streaming()."""
        import time

        start = time.monotonic()

        stream = self.agent.run_stream(
            input_text=message.content.text,
            conversation_id=message.conversation_id,
            platform=message.platform,
        )

        await adapter.send_streaming(message.conversation_id, stream)

        latency_ms = int((time.monotonic() - start) * 1000)

        # Publish metrics-only event (NOT "agent.response"
        # to avoid MsgHub double-delivery).
        await self.event_bus.publish("agent.metrics", {
            "platform": message.platform,
            "conversation_id": message.conversation_id,
            "latency_ms": latency_ms,
        })

        logger.info(
            "app.streaming_complete",
            platform=message.platform,
            latency_ms=latency_ms,
        )

    async def _handle_non_streaming(self, message: Any) -> None:
        """Non-streaming path: Agent.run() -> event bus -> MsgHub."""
        result = await self.agent.run(
            input_text=message.content.text,
            conversation_id=message.conversation_id,
            platform=message.platform,
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

    async def start(self) -> None:
        """Start all services."""
        logger.info("app.starting")

        # Initialize database (creates dir, schema, vec extension)
        await self.database.initialize()

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

        await self.database.close()

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
