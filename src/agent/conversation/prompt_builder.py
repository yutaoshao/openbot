"""Prompt assembly helpers for shared single-user memory."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.core.logging import get_logger

if TYPE_CHECKING:
    from src.memory.episodic import EpisodicMemory
    from src.memory.procedural import ProceduralMemory
    from src.memory.semantic import SemanticMemory

logger = get_logger(__name__)


class PromptBuilder:
    """Build system prompt fragments from long-term memory tiers."""

    def __init__(
        self,
        semantic_memory: SemanticMemory,
        episodic_memory: EpisodicMemory,
        procedural_memory: ProceduralMemory,
        personal_profile: object | None = None,
        personal_history: object | None = None,
        personal_retrieval: object | None = None,
        followups: object | None = None,
    ) -> None:
        self._semantic = semantic_memory
        self._episodic = episodic_memory
        self._procedural = procedural_memory
        self._profile = personal_profile
        self._history = personal_history
        self._retrieval = personal_retrieval
        self._followups = followups

    async def enrich(
        self,
        base_prompt: str,
        user_input: str,
        user_id: str,
    ) -> str:
        sections: list[str] = [base_prompt]
        for section in await self._memory_sections(user_input, user_id):
            if section:
                sections.append(section)
        return "\n\n".join(sections)

    async def _memory_sections(self, user_input: str, user_id: str) -> list[str]:
        if self._profile is not None:
            matches = await self._retrieval.recall(user_input) if self._retrieval else None
            profile_context = self._profile.context(user_input, matches=matches)
            past = await self._episodic.recall(user_input, user_id, limit=2)
            history_context = (
                self._history.context(
                    user_input,
                    profile_content=profile_context,
                    conversation_ids=[item["id"] for item in past if item.get("id")],
                )
                if self._history
                else ""
            )
            return [
                await self._procedural_context(user_id, query=user_input),
                profile_context,
                history_context,
                await self._semantic_context(user_input, user_id, exclude_personal=True),
                await self._followups.context(
                    user_input, profile_context=profile_context, history_context=history_context
                )
                if self._followups
                else "",
            ]
        return [
            await self._procedural_context(user_id),
            await self._semantic_context(user_input, user_id),
            await self._episodic_context(user_input, user_id),
        ]

    async def _procedural_context(self, user_id: str, *, query: str | None = None) -> str:
        try:
            pref_context = await self._procedural.get_system_prompt_context(
                user_id, **({"query": query} if query is not None else {})
            )
            return pref_context or ""
        except Exception:
            _log_context_failure("procedural")
            return ""

    async def _semantic_context(
        self, user_input: str, user_id: str, *, exclude_personal: bool = False
    ) -> str:
        try:
            knowledge_items = await self._semantic.recall(user_input, user_id, limit=10)
            if exclude_personal:
                knowledge_items = [
                    item for item in knowledge_items if item.get("memory_type") == "general"
                ]
            knowledge_items = knowledge_items[:3]
            if not knowledge_items:
                return ""
            lines = ["Relevant Knowledge:"]
            lines.extend(
                f"- [{item.get('category', '')}] {item.get('content', '')[:200]}"
                for item in knowledge_items
            )
            return "\n".join(lines)
        except Exception:
            _log_context_failure("semantic")
            return ""

    async def _episodic_context(self, user_input: str, user_id: str) -> str:
        try:
            past = await self._episodic.recall(user_input, user_id, limit=2)
            if not past:
                return ""
            lines = ["Related Past Conversations (generated summaries are leads, not evidence):"]
            for conversation in past:
                summary = conversation.get("summary", "")[:150]
                if summary:
                    lines.append(f"- {conversation.get('title', '')}: {summary}")
            return "\n".join(lines)
        except Exception:
            _log_context_failure("episodic")
            return ""


def _log_context_failure(tier: str) -> None:
    logger.warning(
        "conversation.prompt_context_failed",
        tier=tier,
        exc_info=True,
    )
