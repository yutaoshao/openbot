"""OpenBot application entrypoint.

Wires all layers together and starts the agent service.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
from pathlib import Path
from typing import Any

import uvicorn

from src.agent.agent import Agent
from src.agent.conversation import ConversationManager
from src.agent.deep_research import DeepResearch
from src.agent.scheduler import AgentScheduler
from src.agent.serialization import UserExecutionCoordinator
from src.agent.skill import LoadSkillTool, SkillRegistry
from src.agent.sub_agent import SubAgent
from src.api import create_api_app
from src.channels.adapters.feishu import FeishuAdapter
from src.channels.adapters.feishu_long_connection import FeishuLongConnectionAdapter
from src.channels.adapters.telegram import TelegramAdapter
from src.channels.adapters.web import WebAdapter
from src.channels.hub import MsgHub
from src.channels.types import MessageContent, StreamingAdapter
from src.core.config import load_config
from src.core.logging import disable_db_logging, enable_db_logging, get_logger, setup_logging
from src.core.monitor import MetricsCollector
from src.core.trace import setup_tracing, trace_scope
from src.identity.service import IdentityService
from src.infrastructure.database import Database
from src.infrastructure.embedding import EmbeddingService, NullEmbeddingService
from src.infrastructure.event_bus import EventBus
from src.infrastructure.model_gateway import ModelGateway
from src.infrastructure.reranker import NullRerankerService, RerankerService
from src.infrastructure.storage import Storage
from src.memory.episodic import EpisodicMemory
from src.memory.procedural import ProceduralMemory
from src.memory.semantic import SemanticMemory
from src.tools.builtin import (
    CodeExecutorTool,
    DeepResearchTool,
    FileManagerTool,
    ScheduleManagerTool,
    ToolSearchTool,
    WebFetchTool,
    WebSearchTool,
)
from src.tools.registry import CORE_VISIBILITY, DEFERRED_VISIBILITY, ToolRegistry

logger = get_logger(__name__)


class _UvicornServerNoSignals(uvicorn.Server):
    """Uvicorn server variant that lets the app own signal handling."""

    def install_signal_handlers(self) -> None:  # noqa: D401
        return None


class Application:
    """Main application orchestrator."""

    def __init__(self) -> None:
        self.config = load_config()
        self._shutdown_event = asyncio.Event()

        # Infrastructure layer
        self.event_bus = EventBus()
        self.model_gateway = ModelGateway(self.config.model, self.event_bus)
        self.database = Database(
            self.config.storage,
            embedding_dimensions=self.config.embedding.dimensions,
        )
        self.storage = Storage(self.database)
        self.identity_service = IdentityService(self.storage)

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

        # Deep research engine (needed by DeepResearchTool)
        self.deep_research = DeepResearch(
            model_gateway=self.model_gateway,
            event_bus=self.event_bus,
        )

        # Skill system (scans ~/.claude/skills, .claude/skills, .agents/skills, data/skills)
        self.skill_registry = SkillRegistry()

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
            skill_registry=self.skill_registry,
        )

        # Sub-agent delegator (shared gateway, scoped tools)
        self.sub_agent = SubAgent(
            model_gateway=self.model_gateway,
            event_bus=self.event_bus,
            config=self.config.agent,
            tool_registry=self.tool_registry,
        )

        # Application layer
        self.msg_hub = MsgHub(self.event_bus)
        self.telegram: TelegramAdapter | None = None
        self.feishu: FeishuAdapter | None = None
        self.web_adapter = WebAdapter()
        self.scheduler: AgentScheduler | None = None
        self.monitor = MetricsCollector(self.storage, self.event_bus)
        self.api_server: _UvicornServerNoSignals | None = None
        self.api_app: Any | None = None
        self.api_task: asyncio.Task[None] | None = None
        self.execution_coordinator = UserExecutionCoordinator()

        self.msg_hub.register_adapter("web", self.web_adapter)

        # Wire up events
        self.event_bus.subscribe("msg.receive", self._on_message_receive)

    def _register_builtin_tools(self) -> None:
        """Register all built-in tools."""
        self.tool_registry.register(
            ToolSearchTool(self.tool_registry),
            visibility=CORE_VISIBILITY,
        )
        self.tool_registry.register(
            WebSearchTool(),
            visibility=CORE_VISIBILITY,
            keywords=["search", "news", "最新", "查一下"],
        )
        self.tool_registry.register(
            WebFetchTool(),
            visibility=CORE_VISIBILITY,
            keywords=["read url", "fetch page", "网页", "文档"],
        )
        self.tool_registry.register(
            CodeExecutorTool(),
            visibility=CORE_VISIBILITY,
            keywords=["run code", "python", "calculate", "计算"],
        )
        self.tool_registry.register(
            FileManagerTool(workspace=Path(self.config.storage.workspace_path)),
            visibility=CORE_VISIBILITY,
            keywords=["file", "workspace", "read file", "write file", "文件"],
        )
        self.tool_registry.register(
            ScheduleManagerTool(lambda: self.scheduler),
            visibility=CORE_VISIBILITY,
            keywords=["schedule", "cron", "later", "提醒", "定时"],
        )
        self.tool_registry.register(
            DeepResearchTool(self.deep_research),
            visibility=DEFERRED_VISIBILITY,
            keywords=["deep research", "investigate deeply", "调研", "深度研究"],
        )
        self.tool_registry.register(
            LoadSkillTool(self.skill_registry),
            visibility=DEFERRED_VISIBILITY,
            keywords=["skill", "workflow", "规范", "技能"],
        )

    async def _on_message_receive(self, data: dict[str, Any]) -> None:
        """Handle incoming message: run agent and publish response."""
        message = data["message"]
        input_text = message.content.text

        if not input_text:
            return

        message.user_id = await self.identity_service.resolve_user_id(
            platform=message.platform,
            platform_user_id=message.sender_id,
            conversation_id=message.conversation_id,
            user_id=message.user_id,
        )

        with trace_scope(
            interaction_id=message.conversation_id,
            platform=message.platform,
        ):
            logger.info(
                "task_received",
                surface="contextual",
                sender=message.sender_id,
                text_length=len(input_text),
            )

            adapter = self.msg_hub.get_adapter(message.platform)

            try:
                async with self.execution_coordinator.serialize(
                    message.user_id or message.conversation_id,
                ) as queue_wait_ms:
                    await self.event_bus.publish("harness.queue_wait", {
                        "conversation_id": message.conversation_id,
                        "platform": message.platform,
                        "user_id": message.user_id or "",
                        "queue_wait_ms": int(queue_wait_ms),
                    })

                    use_streaming = isinstance(adapter, StreamingAdapter) and (
                        message.platform != "telegram"
                        or self.config.telegram.enable_streaming
                    )

                    if use_streaming:
                        await self._handle_streaming(message, adapter)
                    else:
                        await self._handle_non_streaming(message)

            except Exception:
                logger.exception(
                    "task_failed",
                    surface="operational",
                    reason="unhandled_exception",
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
            user_id=message.user_id or "",
        )

        await adapter.send_streaming(message.conversation_id, stream)

        latency_ms = int((time.monotonic() - start) * 1000)

        await self.event_bus.publish("agent.metrics", {
            "platform": message.platform,
            "conversation_id": message.conversation_id,
            "latency_ms": latency_ms,
        })

        logger.info(
            "task_finished",
            surface="operational",
            latency_ms=latency_ms,
            mode="streaming",
        )

    async def _handle_non_streaming(self, message: Any) -> None:
        """Non-streaming path: Agent.run() -> event bus -> MsgHub."""
        result = await self.agent.run(
            input_text=message.content.text,
            conversation_id=message.conversation_id,
            platform=message.platform,
            user_id=message.user_id or "",
        )

        await self.event_bus.publish("agent.response", {
            "platform": message.platform,
            "target_id": message.conversation_id,
            "content": MessageContent(text=result.content),
            "latency_ms": result.latency_ms,
            "tokens_in": result.tokens_in,
            "tokens_out": result.tokens_out,
        })

        logger.info(
            "task_finished",
            surface="operational",
            latency_ms=result.latency_ms,
            token_in=result.tokens_in,
            token_out=result.tokens_out,
            mode="non_streaming",
        )

    async def start(self) -> None:
        """Start all services."""
        logger.info("app.starting")

        # Initialize database (creates dir, schema, vec extension)
        await self.database.initialize()

        # Start DB log persistence
        enable_db_logging(self.storage.logs)

        if self.config.api.enabled:
            self.api_app = create_api_app(
                agent=self.agent,
                storage=self.storage,
                config=self.config,
                scheduler=self.scheduler,
                msg_hub=self.msg_hub,
                web_adapter=self.web_adapter,
                tool_registry=self.tool_registry,
                monitor=self.monitor,
                identity_service=self.identity_service,
            )
            uvicorn_config = uvicorn.Config(
                app=self.api_app,
                host=self.config.api.host,
                port=self.config.api.port,
                log_level=self.config.log.level.lower(),
                access_log=False,
            )
            self.api_server = _UvicornServerNoSignals(uvicorn_config)
            self.api_task = asyncio.create_task(self.api_server.serve())
            await self._wait_for_api_ready()

        # Start Telegram adapter
        if not self.config.telegram.enabled:
            logger.info("app.telegram_disabled")
        else:
            missing_envs = self.config.telegram.missing_required_env_vars()
            if missing_envs:
                logger.warning(
                    "app.telegram_incomplete",
                    missing_env_vars=missing_envs,
                )
            else:
                try:
                    self.telegram = TelegramAdapter(self.config.telegram, self.msg_hub)
                    self.msg_hub.register_adapter("telegram", self.telegram)
                    await self.telegram.start()
                    # Inject into API state for webhook route
                    if self.api_app:
                        self.api_app.state.telegram = self.telegram
                    logger.info("app.telegram_ready", mode=self.config.telegram.mode)
                except Exception:
                    self.telegram = None
                    logger.exception("app.telegram_failed")

        # Start Feishu adapter
        if not self.config.feishu.enabled:
            logger.info("app.feishu_disabled")
        else:
            missing_envs = self.config.feishu.missing_required_env_vars()
            if missing_envs:
                logger.warning(
                    "app.feishu_incomplete",
                    missing_env_vars=missing_envs,
                )
            else:
                try:
                    if self.config.feishu.mode == "long_connection":
                        self.feishu = FeishuLongConnectionAdapter(
                            self.config.feishu,
                            self.msg_hub,
                        )
                    else:
                        self.feishu = FeishuAdapter(self.config.feishu, self.msg_hub)
                    self.msg_hub.register_adapter("feishu", self.feishu)
                    await self.feishu.start()
                    if self.api_app and self.config.feishu.mode == "webhook":
                        self.api_app.state.feishu = self.feishu
                    logger.info(
                        "app.feishu_ready",
                        mode=self.config.feishu.mode,
                        webhook_path="/webhook/feishu"
                        if self.config.feishu.mode == "webhook"
                        else None,
                    )
                except Exception:
                    self.feishu = None
                    logger.exception("app.feishu_failed")

        # Start scheduler
        self.scheduler = AgentScheduler(
            self.storage, self.agent, self.event_bus, self.msg_hub,
            config=self.config.scheduler,
        )
        await self.scheduler.start()
        if self.api_app:
            self.api_app.state.scheduler = self.scheduler

        logger.info("app.started")

    async def stop(self) -> None:
        """Gracefully stop all services."""
        logger.info("app.stopping")

        if self.api_server:
            self.api_server.should_exit = True

        if self.api_task:
            with contextlib.suppress(asyncio.CancelledError):
                await self.api_task
            self.api_task = None
            self.api_server = None

        if self.scheduler:
            await self.scheduler.stop()

        if self.feishu:
            await self.feishu.stop()

        if self.telegram:
            await self.telegram.stop()

        disable_db_logging()
        await self.database.close()

        logger.info("app.stopped")

    async def _wait_for_api_ready(self, timeout: float = 5.0) -> None:
        """Wait for Uvicorn startup and fail fast on startup errors."""
        if not self.api_server:
            return

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout

        while not self.api_server.started:
            if self.api_task and self.api_task.done():
                exc = self.api_task.exception()
                if exc is not None:
                    raise RuntimeError("API server failed to start") from exc
                raise RuntimeError("API server exited before becoming ready")
            if loop.time() >= deadline:
                logger.warning(
                    "app.api_start_timeout",
                    host=self.config.api.host,
                    port=self.config.api.port,
                )
                return
            await asyncio.sleep(0.05)

        logger.info(
            "app.api_ready",
            host=self.config.api.host,
            port=self.config.api.port,
        )

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
    setup_logging(
        level=config.log.level,
        fmt=config.log.format,
        log_file=config.log.file,
        max_bytes=config.log.max_bytes,
        backup_count=config.log.backup_count,
    )

    # Initialize OTel tracing (optional, requires otlp_endpoint in config)
    if config.log.otlp_endpoint:
        setup_tracing(
            service_name="openbot",
            otlp_endpoint=config.log.otlp_endpoint,
        )

    app = Application()

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(app.run_forever())

    logger.info("app.exit")


if __name__ == "__main__":
    main()
