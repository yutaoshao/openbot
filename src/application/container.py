"""Application composition root for OpenBot."""

from __future__ import annotations

from src.agent.agent import Agent
from src.agent.conversation import ConversationManager
from src.core.config import load_config
from src.core.logging import get_logger
from src.identity.service import IdentityService
from src.infrastructure.database import Database
from src.infrastructure.event_bus import EventBus
from src.infrastructure.model_gateway import ModelGateway
from src.infrastructure.storage import Storage
from src.memory.episodic import EpisodicMemory
from src.memory.procedural import ProceduralMemory
from src.memory.semantic import SemanticMemory
from src.tools.registry import ToolRegistry

from .bootstrap import init_runtime_services, register_builtin_tools
from .lifecycle import start_application, stop_application, wait_for_api_ready
from .message_dispatch import on_message_receive
from .settings import SettingsService

logger = get_logger(__name__)


class Application:
    """Main application orchestrator."""

    def __init__(self) -> None:
        import asyncio

        self.config_path = "config.yaml"
        self.config = load_config(self.config_path)
        self._shutdown_event = asyncio.Event()
        self._restart_requested = False
        self._restart_task: asyncio.Task[None] | None = None
        self.event_bus = EventBus()
        self.model_gateway = ModelGateway(self.config.model, self.event_bus)
        self.database = Database(
            self.config.storage,
            embedding_dimensions=self.config.embedding.dimensions,
        )
        self.storage = Storage(self.database)
        self.identity_service = IdentityService(self.storage)
        self.settings_service = SettingsService(self.config_path)
        self.tool_registry = ToolRegistry()
        init_runtime_services(self)
        register_builtin_tools(self)
        self.semantic_memory = SemanticMemory(
            self.storage,
            self.model_gateway,
            self.embedding_service,
            self.database,
            self.reranker_service,
        )
        self.episodic_memory = EpisodicMemory(
            self.storage,
            self.model_gateway,
            self.embedding_service,
            self.database,
            self.reranker_service,
        )
        self.procedural_memory = ProceduralMemory(self.storage, self.model_gateway)
        self.conversation_manager = ConversationManager(
            self.storage,
            self.model_gateway,
            self.semantic_memory,
            self.episodic_memory,
            self.procedural_memory,
        )
        self.agent = Agent(
            model_gateway=self.model_gateway,
            event_bus=self.event_bus,
            config=self.config.agent,
            tool_registry=self.tool_registry,
            conversation_manager=self.conversation_manager,
            skill_registry=self.skill_registry,
        )
        self.event_bus.subscribe("msg.receive", self._on_message_receive)

    def _register_builtin_tools(self) -> None:
        register_builtin_tools(self)

    async def _on_message_receive(self, data: dict[str, object]) -> None:
        await on_message_receive(self, data)

    async def start(self) -> None:
        await start_application(self)

    async def stop(self) -> None:
        await stop_application(self)

    async def _wait_for_api_ready(self, timeout: float = 5.0) -> None:
        await wait_for_api_ready(self, timeout=timeout)

    async def run_forever(self) -> None:
        import asyncio
        import signal

        await self.start()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._shutdown_event.set)
        logger.info("app.running", message="Press Ctrl+C to stop")
        await self._shutdown_event.wait()
        await self.stop()

    @property
    def restart_requested(self) -> bool:
        """Return ``True`` when a local restart has been requested."""
        return self._restart_requested

    async def request_restart(self, delay: float = 0.2) -> None:
        """Schedule a graceful local process restart."""
        import asyncio

        if self._restart_requested:
            return
        self._restart_requested = True
        self._restart_task = asyncio.create_task(
            self._trigger_restart(delay),
            name="openbot-restart",
        )
        logger.info("app.restart_requested", delay_s=delay)

    async def _trigger_restart(self, delay: float) -> None:
        import asyncio

        await asyncio.sleep(max(0.0, delay))
        self._shutdown_event.set()
