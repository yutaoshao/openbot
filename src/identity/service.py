"""Canonical user identity resolution across messaging platforms."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.infrastructure.storage import Storage


class IdentityService:
    """Resolves platform accounts into a shared internal user id."""

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    async def resolve_user_id(
        self,
        *,
        platform: str,
        platform_user_id: str,
        conversation_id: str = "",
        user_id: str | None = None,
    ) -> str:
        """Return an existing canonical user id or create a new one."""
        if user_id:
            return user_id
        if platform == "web":
            return conversation_id or platform_user_id or uuid.uuid4().hex
        if not platform or not platform_user_id:
            return conversation_id or uuid.uuid4().hex

        identity = await self._storage.user_identities.get(
            platform,
            platform_user_id,
        )
        if identity is not None:
            return identity["user_id"]

        resolved_user_id = uuid.uuid4().hex
        await self._storage.user_identities.set(
            user_id=resolved_user_id,
            platform=platform,
            platform_user_id=platform_user_id,
        )
        return resolved_user_id

    async def bind_identity(
        self,
        *,
        user_id: str,
        platform: str,
        platform_user_id: str,
    ) -> dict[str, Any]:
        """Bind a platform identity to a canonical user, merging old data."""
        if not user_id:
            raise ValueError("user_id is required")
        if not platform:
            raise ValueError("platform is required")
        if not platform_user_id:
            raise ValueError("platform_user_id is required")

        existing = await self._storage.user_identities.get(
            platform,
            platform_user_id,
        )
        if existing is not None and existing["user_id"] != user_id:
            await self._storage.conversations.reassign_user(
                existing["user_id"],
                user_id,
            )
            await self._storage.knowledge.reassign_user(
                existing["user_id"],
                user_id,
            )
            await self._storage.preferences.reassign_user(
                existing["user_id"],
                user_id,
            )
            await self._storage.user_identities.reassign_user(
                existing["user_id"],
                user_id,
            )

        return await self._storage.user_identities.set(
            user_id=user_id,
            platform=platform,
            platform_user_id=platform_user_id,
        )

    async def list_identities(
        self,
        *,
        user_id: str | None = None,
        platform: str | None = None,
    ) -> list[dict[str, Any]]:
        """List stored identity mappings with optional filtering."""
        return await self._storage.user_identities.list_all(
            user_id=user_id,
            platform=platform,
        )
