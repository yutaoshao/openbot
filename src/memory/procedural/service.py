"""Procedural memory service implementation."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from src.core.logging import get_logger

from .helpers import (
    CATEGORIES,
    OBSERVATION_PROMPT,
    dedupe_preferences,
    format_messages,
    parse_preferences,
)

if TYPE_CHECKING:
    from src.infrastructure.model_gateway import ModelGateway
    from src.infrastructure.storage import Storage

logger = get_logger(__name__)


class ProceduralMemory:
    """Extracts, stores, and retrieves user preferences."""

    def __init__(self, storage: Storage, model_gateway: ModelGateway) -> None:
        self._storage = storage
        self._gateway = model_gateway

    async def observe(
        self,
        messages: list[dict[str, Any]],
        conversation_id: str,
        user_id: str,
    ) -> list[dict[str, Any]]:
        if not messages:
            return []

        prompt_messages = [
            {"role": "system", "content": OBSERVATION_PROMPT},
            {"role": "user", "content": format_messages(messages)},
        ]
        try:
            response = await self._gateway.chat(prompt_messages)
        except Exception:
            logger.error("procedural.observe_llm_failed", conversation_id=conversation_id)
            return []

        raw_prefs = parse_preferences(response.text)
        if not raw_prefs:
            return []

        saved: list[dict[str, Any]] = []
        for pref in raw_prefs:
            category = pref.get("category", "")
            key = pref.get("key", "")
            value = pref.get("value", "")
            confidence = pref.get("confidence", 0.4)
            if not category or not key or not value or category not in CATEGORIES:
                continue

            existing = await self._storage.preferences.get(user_id, category, key)
            if existing and existing.get("evidence"):
                evidence: list[str] = list(existing["evidence"])
            else:
                evidence = []
            if conversation_id not in evidence:
                evidence.append(conversation_id)

            pref_id = existing["id"] if existing else uuid.uuid4().hex
            await self._storage.preferences.set(
                id=pref_id,
                user_id=user_id,
                category=category,
                key=key,
                value=value,
                evidence=evidence,
                confidence=confidence,
            )
            saved.append(
                {
                    "id": pref_id,
                    "user_id": user_id,
                    "category": category,
                    "key": key,
                    "value": value,
                    "confidence": confidence,
                    "evidence": evidence,
                }
            )

        logger.info(
            "procedural.observe",
            conversation_id=conversation_id,
            extracted=len(raw_prefs),
            stored=len(saved),
        )
        return saved

    async def get_preferences(
        self,
        user_id: str,
        *,
        include_legacy: bool = True,
    ) -> list[dict[str, Any]]:
        prefs = await self._storage.preferences.get_all(user_id, include_legacy=include_legacy)
        return dedupe_preferences(prefs)

    async def get_system_prompt_context(self, user_id: str) -> str:
        prefs = await self.get_preferences(user_id)
        if not prefs:
            return ""
        lines = ["User Preferences:"]
        for pref in prefs:
            lines.append(f"- [{pref['category']}] {pref['key']}: {pref['value']}")
        return "\n".join(lines)

    async def update_preference(
        self,
        user_id: str,
        category: str,
        key: str,
        value: str,
        evidence: list[str] | None = None,
    ) -> None:
        existing = await self._storage.preferences.get(user_id, category, key)
        pref_id = existing["id"] if existing else uuid.uuid4().hex
        if evidence is None:
            evidence = []
        elif existing and existing.get("evidence"):
            evidence = list(existing["evidence"])

        await self._storage.preferences.set(
            id=pref_id,
            user_id=user_id,
            category=category,
            key=key,
            value=value,
            evidence=evidence,
            confidence=1.0,
        )
        logger.info("procedural.preference_updated", category=category, key=key)

    async def delete_preference(self, user_id: str, category: str, key: str) -> None:
        await self._storage.preferences.delete(user_id, category, key)
        logger.info("procedural.preference_deleted", category=category, key=key)
