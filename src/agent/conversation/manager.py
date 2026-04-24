"""Conversation manager with single-user shared recent timeline memory."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from src.core.logging import get_logger
from src.core.user_scope import CHAT_MEMORY_PLATFORMS, SINGLE_USER_ID

from .archive_helpers import (
    background_trace_scope,
    conversation_llm_messages,
    conversation_platform,
    pending_llm_messages,
)
from .compression import maybe_compress_shared_timeline
from .prompt_builder import PromptBuilder
from .shared_timeline import SharedTimelineMemory
from .task_state_store import TaskStateStore

if TYPE_CHECKING:
    from src.agent.state import TaskState
    from src.infrastructure.model_gateway import ModelGateway
    from src.infrastructure.storage import Storage
    from src.memory.episodic import EpisodicMemory
    from src.memory.procedural import ProceduralMemory
    from src.memory.semantic import SemanticMemory

logger = get_logger(__name__)

_WORKING_MEMORY_IDLE_TTL_SECONDS = 30 * 60


class ConversationManager:
    """Manage conversation lifecycle with a shared cross-IM timeline."""

    def __init__(
        self,
        storage: Storage,
        model_gateway: ModelGateway,
        semantic_memory: SemanticMemory,
        episodic_memory: EpisodicMemory,
        procedural_memory: ProceduralMemory,
    ) -> None:
        self._storage = storage
        self._gateway = model_gateway
        self._semantic = semantic_memory
        self._episodic = episodic_memory
        self._procedural = procedural_memory
        self._task_store = TaskStateStore()
        self._shared_timeline: SharedTimelineMemory | None = None
        self._last_memory_sync_count: dict[str, int] = {}
        self._last_archive_count: dict[str, int] = {}
        self._prompt_builder = PromptBuilder(
            semantic_memory,
            episodic_memory,
            procedural_memory,
        )

    async def get_or_create_conversation(
        self,
        conversation_id: str,
        platform: str,
        user_id: str,
        token_budget: int = 8000,
    ) -> SharedTimelineMemory:
        await self._ensure_conversation_record(conversation_id, platform, user_id)
        if self._shared_timeline is None:
            self._shared_timeline = SharedTimelineMemory(token_budget=token_budget)
        await self._shared_timeline.ensure_loaded(self._storage.messages)
        self._task_store.ensure(conversation_id)
        return self._shared_timeline

    async def build_messages(
        self,
        conversation_id: str,
        system_prompt: str,
        user_input: str,
        user_id: str,
    ) -> list[dict[str, Any]]:
        if self._shared_timeline is None:
            return [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ]

        enriched_prompt = await self._prompt_builder.enrich(system_prompt, user_input, user_id)
        messages: list[dict[str, Any]] = [{"role": "system", "content": enriched_prompt}]
        messages.extend(self._task_store.get_protected_messages(conversation_id))
        messages.extend(self._shared_timeline.get_messages())
        return messages

    async def add_user_message(self, conversation_id: str, content: str) -> None:
        message_id = uuid.uuid4().hex
        self._task_store.note_user_input(conversation_id, content)
        await self._append_to_shared_timeline(conversation_id, {"role": "user", "content": content})
        await self._storage.messages.add(
            id=message_id,
            conversation_id=conversation_id,
            role="user",
            content=content,
        )

    async def add_assistant_message(
        self,
        conversation_id: str,
        content: str,
        model: str = "",
        tokens_in: int = 0,
        tokens_out: int = 0,
        latency_ms: int = 0,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        message_id = uuid.uuid4().hex
        self._task_store.note_assistant_reply(conversation_id, content)
        await self._append_to_shared_timeline(
            conversation_id,
            {"role": "assistant", "content": content},
        )
        await self._storage.messages.add(
            id=message_id,
            conversation_id=conversation_id,
            role="assistant",
            content=content,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            tool_calls=tool_calls,
        )

    async def maybe_compress(self, conversation_id: str) -> None:
        await maybe_compress_shared_timeline(
            self._shared_timeline,
            self._gateway,
            self._semantic,
            conversation_id=conversation_id,
        )

    async def prune_idle_conversations(self, *, now: float | None = None) -> None:
        stale_ids = self._task_store.stale_conversations(
            _WORKING_MEMORY_IDLE_TTL_SECONDS,
            now=now,
        )
        for conversation_id in stale_ids:
            platform = await conversation_platform(self._storage, conversation_id)
            with background_trace_scope(
                conversation_id,
                platform,
                trigger="idle_prune",
            ):
                await self.archive_idle_conversation(
                    conversation_id,
                    clear_working_memory=True,
                )
            logger.debug("conversation.evicted_idle", conversation_id=conversation_id)

    async def sync_memory_after_turn(self, conversation_id: str) -> None:
        llm_messages, total_count = await pending_llm_messages(
            self._storage,
            conversation_id,
            self._last_memory_sync_count.get(conversation_id, 0),
        )
        if total_count == self._last_memory_sync_count.get(conversation_id, 0):
            logger.info(
                "conversation.memory_sync_skipped",
                conversation_id=conversation_id,
                reason="no_new_messages",
            )
            return

        await self._semantic.extract_knowledge(
            llm_messages,
            conversation_id,
            SINGLE_USER_ID,
        )
        await self._procedural.observe(
            llm_messages,
            conversation_id,
            SINGLE_USER_ID,
        )
        self._last_memory_sync_count[conversation_id] = total_count
        logger.info(
            "conversation.memory_synced",
            conversation_id=conversation_id,
            user_id=SINGLE_USER_ID,
            message_count=total_count,
        )

    async def archive_idle_conversation(
        self,
        conversation_id: str,
        *,
        clear_working_memory: bool,
    ) -> None:
        llm_messages, total_count = await conversation_llm_messages(
            self._storage,
            conversation_id,
        )
        if total_count == 0:
            self._clear_task_state(conversation_id, clear_working_memory)
            return
        if total_count <= self._last_archive_count.get(conversation_id, 0):
            self._clear_task_state(conversation_id, clear_working_memory)
            logger.info(
                "conversation.idle_archive_skipped",
                conversation_id=conversation_id,
                reason="no_new_messages",
            )
            return

        await self.sync_memory_after_turn(conversation_id)
        await self._episodic.on_conversation_end(conversation_id, SINGLE_USER_ID)
        self._last_archive_count[conversation_id] = total_count
        self._clear_task_state(conversation_id, clear_working_memory)
        logger.info(
            "conversation.idle_archived",
            conversation_id=conversation_id,
            user_id=SINGLE_USER_ID,
            message_count=len(llm_messages),
        )

    async def end_conversation(
        self,
        conversation_id: str,
        *,
        clear_working_memory: bool = True,
    ) -> None:
        await self.archive_idle_conversation(
            conversation_id,
            clear_working_memory=clear_working_memory,
        )

    def get_task_state(self, conversation_id: str) -> TaskState | None:
        return self._task_store.get(conversation_id)

    def record_tool_event(
        self,
        conversation_id: str,
        tool_name: str,
        summary: str,
        *,
        is_error: bool,
        activated_tools: list[str] | None = None,
    ) -> None:
        self._task_store.record_tool_event(
            conversation_id,
            tool_name,
            summary,
            is_error=is_error,
            activated_tools=activated_tools,
        )

    def protect_context(
        self,
        conversation_id: str,
        key: str,
        content: str,
    ) -> None:
        self._task_store.set_protected(conversation_id, key, content)

    async def _append_to_shared_timeline(
        self,
        conversation_id: str,
        message: dict[str, Any],
    ) -> None:
        if self._shared_timeline is None:
            return
        conversation = await self._storage.conversations.get(conversation_id)
        platform = str(conversation.get("platform", "")) if conversation else ""
        if platform in CHAT_MEMORY_PLATFORMS:
            self._shared_timeline.add(message)

    async def _ensure_conversation_record(
        self,
        conversation_id: str,
        platform: str,
        user_id: str,
    ) -> None:
        existing = await self._storage.conversations.get(conversation_id)
        if existing is None:
            await self._storage.conversations.create(
                id=conversation_id,
                platform=platform,
                user_id=user_id,
            )
            logger.info(
                "conversation.created",
                conversation_id=conversation_id,
                platform=platform,
            )
            return
        if existing.get("user_id") != user_id:
            await self._storage.conversations.update(conversation_id, user_id=user_id)

    def _clear_task_state(self, conversation_id: str, clear_working_memory: bool) -> None:
        if clear_working_memory:
            self._task_store.clear(conversation_id)
