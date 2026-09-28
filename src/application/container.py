"""Application composition root for OpenBot."""

from __future__ import annotations

import asyncio
import signal
from pathlib import Path
from typing import TYPE_CHECKING

from src.agent.agent import Agent
from src.agent.conversation import ConversationManager
from src.agent.conversation.journal import ConversationJournal
from src.agent.conversation.post_turn import PostTurnMemory
from src.agent.coordination import UserExecutionCoordinator
from src.agent.research import DeepResearch
from src.agent.skills import SkillRegistry
from src.channels.adapters.web import WebAdapter
from src.channels.hub import MsgHub
from src.core.config import load_config
from src.core.logging import get_logger
from src.core.monitor import MetricsCollector
from src.identity.service import IdentityService
from src.infrastructure.database import Database
from src.infrastructure.embedding import EmbeddingService, NullEmbeddingService
from src.infrastructure.event_bus import EventBus
from src.infrastructure.model_gateway import ModelGateway
from src.infrastructure.reranker import NullRerankerService, RerankerService
from src.infrastructure.storage import Storage
from src.memory.episodic import EpisodicMemory
from src.memory.personal_followups import PersonalFollowups
from src.memory.personal_history import PersonalHistory
from src.memory.personal_profile import PersonalProfile
from src.memory.personal_retrieval import PersonalRetrieval
from src.memory.procedural import ProceduralMemory
from src.memory.semantic import SemanticMemory
from src.tools.registry import ToolRegistry

from .bootstrap import register_builtin_tools
from .lifecycle import start_application, stop_application, wait_for_api_ready
from .message_dispatch import on_message_receive
from .settings import SettingsService

logger = get_logger(__name__)

if TYPE_CHECKING:
    import uvicorn
    from fastapi import FastAPI

    from src.agent.scheduling import AgentScheduler
    from src.channels.adapters.feishu import FeishuAdapter
    from src.channels.adapters.feishu_long_connection import FeishuLongConnectionAdapter
    from src.channels.adapters.telegram import TelegramAdapter
    from src.channels.adapters.wechat import WeChatAdapter


class Application:
    """Main application orchestrator."""

    def __init__(self) -> None:
        self.config_path = "config.yaml"
        self.config = load_config(self.config_path)
        self._shutdown_event = asyncio.Event()
        self._restart_requested = False
        self._restart_task: asyncio.Task[None] | None = None
        self.event_bus = EventBus()
        self.model_gateway = ModelGateway(self.config.model, self.event_bus, self.config.agent)
        self.database = Database(
            self.config.storage,
            embedding_dimensions=self.config.embedding.dimensions,
        )
        self.storage = Storage(self.database)
        self.identity_service = IdentityService(self.storage)
        self.settings_service = SettingsService(self.config_path)
        self.tool_registry = ToolRegistry()
        self.embedding_service = (
            EmbeddingService(self.config.embedding)
            if self.config.embedding.enabled
            else NullEmbeddingService()
        )
        self.reranker_service = (
            RerankerService(self.config.reranker)
            if self.config.reranker.enabled
            else NullRerankerService()
        )
        self.deep_research = DeepResearch(
            model_gateway=self.model_gateway, event_bus=self.event_bus
        )
        self.skill_registry = SkillRegistry()
        self.msg_hub = MsgHub(self.event_bus)
        self.telegram: TelegramAdapter | None = None
        self.feishu: FeishuAdapter | FeishuLongConnectionAdapter | None = None
        self.wechat: WeChatAdapter | None = None
        self.web_adapter = WebAdapter()
        self.scheduler: AgentScheduler | None = None
        self.monitor = MetricsCollector(self.storage, self.event_bus)
        self.api_server: uvicorn.Server | None = None
        self.api_app: FastAPI | None = None
        self.api_task: asyncio.Task[None] | None = None
        self.housekeeping_task: asyncio.Task[None] | None = None
        self.execution_coordinator = UserExecutionCoordinator()
        self.msg_hub.register_adapter("web", self.web_adapter)
        register_builtin_tools(
            self.tool_registry,
            self.deep_research,
            self.skill_registry,
            lambda: self.scheduler,
        )
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
        self.personal_profile = PersonalProfile()
        self.procedural_memory = ProceduralMemory(
            self.storage, self.model_gateway, profile=self.personal_profile
        )
        self.personal_history = PersonalHistory(db_path=Path(self.config.storage.db_path))
        self.personal_retrieval = PersonalRetrieval(
            self.personal_profile,
            index=self.storage.personal_index,
            embedding=self.embedding_service,
            reranker=self.reranker_service,
        )
        self.personal_followups = PersonalFollowups(
            profile=self.personal_profile,
            repository=self.storage.followups,
            gateway=self.model_gateway,
        )
        self.conversation_manager = ConversationManager(
            self.storage,
            self.model_gateway,
            self.semantic_memory,
            self.episodic_memory,
            self.procedural_memory,
            conversation_journal=ConversationJournal(),
            personal_profile=self.personal_profile,
            personal_history=self.personal_history,
            personal_retrieval=self.personal_retrieval,
            followups=self.personal_followups,
        )
        self.post_turn_memory = PostTurnMemory(self.conversation_manager)
        self.agent = Agent(
            model_gateway=self.model_gateway,
            event_bus=self.event_bus,
            config=self.config.agent,
            tool_registry=self.tool_registry,
            conversation_manager=self.conversation_manager,
            skill_registry=self.skill_registry,
            post_turn_memory=self.post_turn_memory,
        )
        self.event_bus.subscribe("msg.receive", self._on_message_receive)

    async def _on_message_receive(self, data: dict[str, object]) -> None:
        await on_message_receive(self, data)

    async def start(self) -> None:
        await start_application(self)

    async def stop(self) -> None:
        await stop_application(self)

    async def _wait_for_api_ready(self, timeout: float = 5.0) -> None:
        await wait_for_api_ready(self, timeout=timeout)

    async def run_forever(self) -> None:
        await self.start()
        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, self._shutdown_event.set)
            logger.info("app.running", message="Press Ctrl+C to stop")
            await self._shutdown_event.wait()
        finally:
            await self.stop()

    @property
    def restart_requested(self) -> bool:
        """Return ``True`` when a local restart has been requested."""
        return self._restart_requested

    async def request_restart(self, delay: float = 0.2) -> None:
        """Schedule a graceful local process restart."""
        if self._restart_requested:
            return
        self._restart_requested = True
        self._restart_task = asyncio.create_task(
            self._trigger_restart(delay),
            name="openbot-restart",
        )
        logger.info("app.restart_requested", delay_s=delay)

    async def _trigger_restart(self, delay: float) -> None:
        await asyncio.sleep(max(0.0, delay))
        self._shutdown_event.set()
