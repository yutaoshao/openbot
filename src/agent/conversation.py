"""Conversation manager: assembles messages with memory context.

Orchestrates all memory tiers to build the final message list that the
agent sends to the model.  Handles conversation lifecycle (create, persist,
archive) and the "search-before-act" pattern.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from src.core.logging import get_logger

if TYPE_CHECKING:
    from src.infrastructure.model_gateway import ModelGateway
    from src.infrastructure.storage import Storage
    from src.memory.episodic import EpisodicMemory
    from src.memory.procedural import ProceduralMemory
    from src.memory.semantic import SemanticMemory
    from src.memory.working import WorkingMemory

logger = get_logger(__name__)


class ConversationManager:
    """Manages conversation lifecycle and message assembly with memory.

    Responsible for:
    - Creating / tracking conversations
    - Building the full message context (system prompt + preferences +
      recalled knowledge + working memory messages)
    - Persisting messages to storage
    - Triggering memory extraction on conversation end
    """

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
        # Active working memories keyed by conversation_id (LRU eviction)
        self._working: OrderedDict[str, WorkingMemory] = OrderedDict()
        self._max_working: int = 100  # max concurrent working memories

    # ------------------------------------------------------------------
    # Conversation lifecycle
    # ------------------------------------------------------------------

    async def get_or_create_conversation(
        self,
        conversation_id: str,
        platform: str,
        token_budget: int = 8000,
    ) -> WorkingMemory:
        """Get existing or create new working memory for a conversation."""
        if conversation_id in self._working:
            # Move to end (most recently used)
            self._working.move_to_end(conversation_id)
            return self._working[conversation_id]

        # Check if conversation exists in DB
        existing = await self._storage.conversations.get(conversation_id)
        if not existing:
            await self._storage.conversations.create(
                id=conversation_id,
                platform=platform,
            )
            logger.info(
                "conversation.created",
                conversation_id=conversation_id,
                platform=platform,
            )

        from src.memory.working import WorkingMemory

        wm = WorkingMemory(
            conversation_id=conversation_id,
            token_budget=token_budget,
        )

        # Load recent messages from DB into working memory
        recent = await self._storage.messages.get_recent(
            conversation_id, token_budget,
        )
        for msg in recent:
            wm.add({"role": msg["role"], "content": msg["content"]})

        self._working[conversation_id] = wm

        # Evict oldest if over limit
        while len(self._working) > self._max_working:
            evicted_id, _ = self._working.popitem(last=False)
            logger.debug("conversation.evicted", conversation_id=evicted_id)

        return wm

    async def build_messages(
        self,
        conversation_id: str,
        system_prompt: str,
        user_input: str,
    ) -> list[dict[str, Any]]:
        """Assemble the full message list for model invocation.

        Order:
        1. System prompt (with injected preferences + recalled knowledge)
        2. Working memory messages (pinned + summary + recent)
        3. Current user input
        """
        wm = self._working.get(conversation_id)
        if wm is None:
            # Fallback: no working memory, just basic messages
            return [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ]

        # Search-before-act: recall relevant knowledge and past conversations
        enriched_prompt = await self._enrich_system_prompt(
            system_prompt, user_input,
        )

        # Build messages
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": enriched_prompt},
        ]

        # Add working memory context (pinned + summary + history)
        # Note: current user message is already in working memory
        # (added by add_user_message before build_messages is called)
        wm_messages = wm.get_messages()
        messages.extend(wm_messages)

        return messages

    async def add_user_message(
        self,
        conversation_id: str,
        content: str,
    ) -> None:
        """Record a user message in working memory and storage."""
        msg_id = uuid.uuid4().hex

        # Add to working memory
        wm = self._working.get(conversation_id)
        if wm:
            wm.add({"role": "user", "content": content})

        # Persist to storage
        await self._storage.messages.add(
            id=msg_id,
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
        cost: float = 0.0,
        latency_ms: int = 0,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        """Record an assistant message in working memory and storage."""
        msg_id = uuid.uuid4().hex

        # Add to working memory
        wm = self._working.get(conversation_id)
        if wm:
            wm.add({"role": "assistant", "content": content})

        # Persist to storage
        await self._storage.messages.add(
            id=msg_id,
            conversation_id=conversation_id,
            role="assistant",
            content=content,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost=cost,
            latency_ms=latency_ms,
            tool_calls=tool_calls,
        )

    async def maybe_compress(
        self,
        conversation_id: str,
    ) -> None:
        """Compress working memory if token budget is exceeded.

        Before compression, extracts key knowledge (pre-compression flush)
        and persists it to semantic memory.
        """
        wm = self._working.get(conversation_id)
        if not wm or not wm.needs_compression():
            return

        logger.info(
            "conversation.compression_triggered",
            conversation_id=conversation_id,
            tokens_est=wm.estimate_tokens(),
        )

        # Pre-compression flush: extract knowledge before discarding
        try:
            extracted = await wm.extract_before_compression(self._gateway)
            for item in extracted:
                await self._semantic.add_knowledge(
                    category=item["category"],
                    content=item["content"],
                    priority="P1",
                )
        except Exception:
            logger.warning(
                "conversation.pre_compression_flush_failed",
                conversation_id=conversation_id,
                exc_info=True,
            )

        # Compress
        await wm.compress(self._gateway)

    async def end_conversation(
        self,
        conversation_id: str,
    ) -> None:
        """Trigger end-of-conversation memory extraction.

        Archives the conversation (episodic), extracts knowledge (semantic),
        and observes preferences (procedural).
        """
        messages = await self._storage.messages.get_by_conversation(
            conversation_id,
        )
        if not messages:
            return

        llm_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m.get("content")
        ]

        # Parallel extraction (errors isolated per tier)
        try:
            await self._episodic.on_conversation_end(conversation_id)
        except Exception:
            logger.warning(
                "conversation.episodic_archive_failed",
                conversation_id=conversation_id,
                exc_info=True,
            )

        try:
            await self._semantic.extract_knowledge(
                llm_messages, conversation_id,
            )
        except Exception:
            logger.warning(
                "conversation.semantic_extract_failed",
                conversation_id=conversation_id,
                exc_info=True,
            )

        try:
            await self._procedural.observe(llm_messages, conversation_id)
        except Exception:
            logger.warning(
                "conversation.procedural_observe_failed",
                conversation_id=conversation_id,
                exc_info=True,
            )

        # Clean up working memory
        self._working.pop(conversation_id, None)

        logger.info(
            "conversation.ended",
            conversation_id=conversation_id,
            message_count=len(messages),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _enrich_system_prompt(
        self,
        base_prompt: str,
        user_input: str,
    ) -> str:
        """Enrich system prompt with preferences and recalled knowledge."""
        sections: list[str] = [base_prompt]

        # Inject user preferences
        try:
            pref_context = await self._procedural.get_system_prompt_context()
            if pref_context:
                sections.append(pref_context)
        except Exception:
            logger.debug(
                "conversation.preference_load_failed",
                exc_info=True,
            )

        # Search-before-act: recall relevant knowledge
        try:
            knowledge_items = await self._semantic.recall(
                user_input, limit=3,
            )
            if knowledge_items:
                knowledge_lines = ["Relevant Knowledge:"]
                for item in knowledge_items:
                    content = item.get("content", "")[:200]
                    category = item.get("category", "")
                    knowledge_lines.append(
                        f"- [{category}] {content}"
                    )
                sections.append("\n".join(knowledge_lines))
        except Exception:
            logger.debug(
                "conversation.knowledge_recall_failed",
                exc_info=True,
            )

        # Recall relevant past conversations
        try:
            past = await self._episodic.recall(user_input, limit=2)
            if past:
                past_lines = ["Related Past Conversations:"]
                for conv in past:
                    title = conv.get("title", "")
                    summary = conv.get("summary", "")[:150]
                    if summary:
                        past_lines.append(f"- {title}: {summary}")
                sections.append("\n".join(past_lines))
        except Exception:
            logger.debug(
                "conversation.episodic_recall_failed",
                exc_info=True,
            )

        return "\n\n".join(sections)
