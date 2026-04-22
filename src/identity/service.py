"""Canonical user identity resolution across messaging platforms."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.core.user_scope import SINGLE_USER_ID

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
        """Return the fixed single-user id and record observed identities."""
        if platform and platform_user_id:
            await self._storage.user_identities.set(
                user_id=SINGLE_USER_ID,
                platform=platform,
                platform_user_id=platform_user_id,
            )
        return SINGLE_USER_ID

    async def bind_identity(
        self,
        *,
        user_id: str | None = None,
        platform: str,
        platform_user_id: str,
    ) -> dict[str, Any]:
        """Bind a platform identity to a canonical user, merging old data."""
        if user_id and user_id != SINGLE_USER_ID:
            raise ValueError(
                "OpenBot runs in local single-user mode; only local-single-user is supported.",
            )
        if not platform:
            raise ValueError("platform is required")
        if not platform_user_id:
            raise ValueError("platform_user_id is required")

        return await self._storage.user_identities.set(
            user_id=SINGLE_USER_ID,
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
