"""Procedural memory: user preference extraction and retrieval.

Observes conversations to extract explicit and implicit user preferences,
persists them via the Storage layer, and assembles them into system prompt
context for personalised agent responses.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any

from src.core.logging import get_logger

if TYPE_CHECKING:
    from src.infrastructure.model_gateway import ModelGateway
    from src.infrastructure.storage import Storage

logger = get_logger(__name__)

# Valid preference categories.
CATEGORIES: frozenset[str] = frozenset(
    {"communication", "coding", "workflow", "tool"}
)

_OBSERVATION_PROMPT = """\
You are a preference extraction engine.  Analyze the conversation below and
extract any user preferences you can identify.

Look for:
1. **Explicit statements** - "I prefer Python", "always use type hints",
   "reply in Chinese" (confidence: 0.9)
2. **Corrections** - the user correcting the assistant implies a preference
   (confidence: 0.6)
3. **Repeated patterns** - the user consistently requesting a certain format
   or style (confidence: 0.4)

Categorize each preference into exactly one of:
- communication: language preference, response length, formality, tone
- coding: preferred languages, frameworks, style conventions
- workflow: preferred tools, processes, habits
- tool: tool-specific preferences and configurations

Return a JSON array (no markdown fences).  Each element must have:
- "category": one of communication / coding / workflow / tool
- "key": short snake_case identifier (e.g. "preferred_language")
- "value": concise description of the preference
- "confidence": float (0.9 / 0.6 / 0.4 per the rules above)

Only extract **clear** preferences.  Skip anything ambiguous.
If no preferences are found, return an empty array: []

Conversation:
"""


class ProceduralMemory:
    """Extracts, stores, and retrieves user preferences."""

    def __init__(
        self,
        storage: Storage,
        model_gateway: ModelGateway,
    ) -> None:
        self._storage = storage
        self._gateway = model_gateway

    # ------------------------------------------------------------------
    # Observe
    # ------------------------------------------------------------------

    async def observe(
        self,
        messages: list[dict[str, Any]],
        conversation_id: str,
    ) -> list[dict[str, Any]]:
        """Analyze *messages* for user preferences via LLM.

        Extracted preferences are upserted into storage with
        *conversation_id* recorded as evidence.  Returns the list of
        extracted / updated preference dicts.
        """
        if not messages:
            return []

        conversation_text = self._format_messages(messages)
        prompt_messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": _OBSERVATION_PROMPT,
            },
            {
                "role": "user",
                "content": conversation_text,
            },
        ]

        try:
            response = await self._gateway.chat(prompt_messages)
        except Exception:
            logger.error(
                "procedural.observe_llm_failed",
                conversation_id=conversation_id,
            )
            return []

        raw_prefs = self._parse_preferences(response.text)
        if not raw_prefs:
            return []

        saved: list[dict[str, Any]] = []
        for pref in raw_prefs:
            category = pref.get("category", "")
            key = pref.get("key", "")
            value = pref.get("value", "")
            confidence = pref.get("confidence", 0.4)

            if not category or not key or not value:
                continue
            if category not in CATEGORIES:
                continue

            # Build evidence list: merge existing evidence with new id.
            existing = await self._storage.preferences.get(
                category, key,
            )
            evidence: list[str] = []
            if existing and existing.get("evidence"):
                evidence = list(existing["evidence"])
            if conversation_id not in evidence:
                evidence.append(conversation_id)

            pref_id = (
                existing["id"] if existing else uuid.uuid4().hex
            )

            await self._storage.preferences.set(
                id=pref_id,
                category=category,
                key=key,
                value=value,
                evidence=evidence,
                confidence=float(confidence),
            )

            saved.append(
                {
                    "id": pref_id,
                    "category": category,
                    "key": key,
                    "value": value,
                    "confidence": confidence,
                    "evidence": evidence,
                }
            )

        logger.info(
            "procedural.observe_done",
            conversation_id=conversation_id,
            extracted=len(saved),
        )
        return saved

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    async def get_preferences(
        self,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return preferences, optionally filtered by *category*."""
        if category is not None:
            return await self._storage.preferences.get_by_category(
                category,
            )
        return await self._storage.preferences.get_all()

    async def get_system_prompt_context(self) -> str:
        """Assemble all preferences into a string for system prompt.

        Returns an empty string when no preferences exist.
        """
        prefs = await self._storage.preferences.get_all()
        if not prefs:
            return ""

        lines: list[str] = ["User Preferences:"]
        for p in prefs:
            lines.append(
                f"- [{p['category']}] {p['key']}: {p['value']}"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Manual CRUD
    # ------------------------------------------------------------------

    async def update_preference(
        self,
        category: str,
        key: str,
        value: str,
    ) -> None:
        """Manually set or update a preference (API / frontend)."""
        existing = await self._storage.preferences.get(category, key)
        pref_id = existing["id"] if existing else uuid.uuid4().hex

        evidence: list[str] = []
        if existing and existing.get("evidence"):
            evidence = list(existing["evidence"])

        await self._storage.preferences.set(
            id=pref_id,
            category=category,
            key=key,
            value=value,
            evidence=evidence,
            confidence=1.0,
        )
        logger.info(
            "procedural.preference_updated",
            category=category,
            key=key,
        )

    async def delete_preference(
        self,
        category: str,
        key: str,
    ) -> None:
        """Remove a preference."""
        await self._storage.preferences.delete(category, key)
        logger.info(
            "procedural.preference_deleted",
            category=category,
            key=key,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_messages(messages: list[dict[str, Any]]) -> str:
        """Render messages into a readable transcript for the LLM."""
        parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            parts.append(f"[{role}]: {content}")
        return "\n".join(parts)

    @staticmethod
    def _parse_preferences(text: str) -> list[dict[str, Any]]:
        """Best-effort parse of JSON array from LLM response text."""
        cleaned = text.strip()

        # Strip optional markdown fences.
        if cleaned.startswith("```"):
            first_newline = cleaned.index("\n") + 1
            cleaned = cleaned[first_newline:]
        if cleaned.endswith("```"):
            cleaned = cleaned[: cleaned.rfind("```")]
        cleaned = cleaned.strip()

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning(
                "procedural.parse_failed",
                text_preview=cleaned[:200],
            )
            return []

        if not isinstance(parsed, list):
            return []
        return [
            item
            for item in parsed
            if isinstance(item, dict)
        ]
