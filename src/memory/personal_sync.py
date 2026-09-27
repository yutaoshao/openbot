"""Independently checkpoint personal and general extraction for a closed turn."""

from __future__ import annotations

from typing import Any

from src.core.user_scope import SINGLE_USER_ID
from src.memory.personal_documents import ProfileRevisionConflictError


class PersonalMemorySync:
    def __init__(self, *, profile: Any, semantic: Any, gateway: Any, progress: Any) -> None:
        self.profile = profile
        self.semantic = semantic
        self.gateway = gateway
        self.progress = progress

    async def sync_turn(self, user: dict, assistant: dict, *, adjacent: list[dict]) -> None:
        errors = []
        for operation in (
            lambda: self._personal(user, adjacent),
            lambda: self._general(user, assistant),
        ):
            try:
                await operation()
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise errors[0]

    async def _personal(self, user: dict, adjacent: list[dict]) -> None:
        source = f"message:{user['id']}"
        personal = await self.progress.stage(source, "personal")
        if personal is None:
            claims = await self.profile.extract(
                self.gateway,
                user["content"],
                stated_at=user["timestamp"],
                context_messages=[
                    {key: message.get(key) for key in ("id", "role", "content", "timestamp")}
                    for message in adjacent
                ],
            )
            await self.progress.save_stage(source, "personal", claims)
            personal = (claims, False)
        if not personal[1]:
            try:
                await self.profile.apply_claims(
                    personal[0], source=source, stated_at=user["timestamp"]
                )
            except ProfileRevisionConflictError:
                # Re-extract against the edited authority on the next durable retry.
                await self.progress.invalidate_stage(source, "personal")
                raise
            await self.progress.complete_stage(source, "personal")

    async def _general(self, user: dict, assistant: dict) -> None:
        source = f"message:{user['id']}"
        general = await self.progress.stage(source, "general")
        if general is None:
            items = await self.semantic.extract_items(
                [
                    {"role": message["role"], "content": message["content"]}
                    for message in (user, assistant)
                ]
            )
            await self.progress.save_stage(source, "general", items)
            general = (items, False)
        if not general[1]:
            await self.semantic.store_extracted_knowledge(
                general[0], user["conversation_id"], SINGLE_USER_ID, source=source
            )
            await self.progress.complete_stage(source, "general")
