"""Synchronize completed turns without sharing the backfill cursor."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.memory.personal_sync import PersonalMemorySync
from src.memory.turn_selection import select_memory_batch

from .memory_sync import sync_eligible_long_term_memory

if TYPE_CHECKING:
    from src.infrastructure.model_gateway import ModelGateway
    from src.infrastructure.storage import Storage
    from src.memory.personal_profile import PersonalProfile
    from src.memory.procedural import ProceduralMemory
    from src.memory.semantic import SemanticMemory


class OnlineMemorySync:
    """Own online progress, extraction serialization and retry boundaries."""

    def __init__(
        self,
        storage: Storage,
        gateway: ModelGateway,
        semantic: SemanticMemory,
        procedural: ProceduralMemory,
        profile: PersonalProfile | None,
    ) -> None:
        self._storage = storage
        self._semantic = semantic
        self._procedural = procedural
        self._personal = (
            PersonalMemorySync(
                profile=profile,
                semantic=semantic,
                gateway=gateway,
                progress=storage.personal_progress,
            )
            if profile is not None
            else None
        )
        self._lock = asyncio.Lock()
        self._legacy_cursors: dict[str, int] = {}

    async def sync(self, conversation_id: str) -> None:
        if self._personal is None:
            cursor = self._legacy_cursors.get(conversation_id, 0)
            self._legacy_cursors[conversation_id] = await sync_eligible_long_term_memory(
                storage=self._storage,
                semantic_memory=self._semantic,
                procedural_memory=self._procedural,
                conversation_id=conversation_id,
                cursor=cursor,
            )
            return
        async with self._lock:
            cursor = await self._storage.personal_progress.get(conversation_id)
            messages = await self._storage.messages.get_by_conversation(conversation_id)
            selected = select_memory_batch(messages, cursor)
            eligible = iter(selected.messages)
            for user, assistant in zip(eligible, eligible, strict=True):
                user_index = messages.index(user, cursor)
                await self._personal.sync_turn(
                    user, assistant, adjacent=messages[max(0, user_index - 8) : user_index]
                )
                await self._storage.personal_progress.advance(
                    conversation_id, messages.index(assistant, cursor) + 1
                )
            await self._storage.personal_progress.advance(conversation_id, selected.next_cursor)
