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
    ) -> None:
        self._semantic = semantic_memory
        self._episodic = episodic_memory
        self._procedural = procedural_memory

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
        return [
            await self._procedural_context(user_id),
            await self._semantic_context(user_input, user_id),
            await self._episodic_context(user_input, user_id),
        ]

    async def _procedural_context(self, user_id: str) -> str:
        try:
            pref_context = await self._procedural.get_system_prompt_context(user_id)
            return pref_context or ""
        except Exception:
            _log_context_failure("procedural")
            return ""

    async def _semantic_context(self, user_input: str, user_id: str) -> str:
        try:
            knowledge_items = await self._semantic.recall(user_input, user_id, limit=3)
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
            lines = ["Related Past Conversations:"]
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
