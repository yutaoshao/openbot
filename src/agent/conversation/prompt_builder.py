"""Prompt assembly helpers for shared single-user memory."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.memory.episodic import EpisodicMemory
    from src.memory.procedural import ProceduralMemory
    from src.memory.semantic import SemanticMemory


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

        try:
            pref_context = await self._procedural.get_system_prompt_context(user_id)
            if pref_context:
                sections.append(pref_context)
        except Exception:
            pass

        try:
            knowledge_items = await self._semantic.recall(user_input, user_id, limit=3)
            if knowledge_items:
                sections.append(
                    "\n".join(
                        [
                            "Relevant Knowledge:",
                            *[
                                f"- [{item.get('category', '')}] {item.get('content', '')[:200]}"
                                for item in knowledge_items
                            ],
                        ]
                    )
                )
        except Exception:
            pass

        try:
            past = await self._episodic.recall(user_input, user_id, limit=2)
            if past:
                lines = ["Related Past Conversations:"]
                for conversation in past:
                    summary = conversation.get("summary", "")[:150]
                    if summary:
                        lines.append(f"- {conversation.get('title', '')}: {summary}")
                sections.append("\n".join(lines))
        except Exception:
            pass

        return "\n\n".join(sections)
