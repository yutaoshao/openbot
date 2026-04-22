"""Platform identity storage repository."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._base import new_id, now_utc, row_to_dict

if TYPE_CHECKING:
    from src.infrastructure.database import Database

IDENTITY_COLUMNS = [
    "id",
    "user_id",
    "platform",
    "platform_user_id",
    "created_at",
    "updated_at",
]


class UserIdentityRepo:
    """Mappings from platform-specific accounts to canonical user ids."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, platform: str, platform_user_id: str) -> dict[str, Any] | None:
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                f"""
                SELECT {', '.join(IDENTITY_COLUMNS)} FROM user_identities
                WHERE platform = ? AND platform_user_id = ?
                """,
                (platform, platform_user_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return row_to_dict(row, IDENTITY_COLUMNS)

    async def set(
        self,
        *,
        user_id: str,
        platform: str,
        platform_user_id: str,
    ) -> dict[str, Any]:
        now = now_utc()
        existing = await self.get(platform, platform_user_id)
        async with self._db.get_connection() as conn:
            if existing is None:
                identity_id = new_id()
                await conn.execute(
                    """
                    INSERT INTO user_identities
                        (id, user_id, platform, platform_user_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (identity_id, user_id, platform, platform_user_id, now, now),
                )
            else:
                identity_id = existing["id"]
                await conn.execute(
                    """
                    UPDATE user_identities
                    SET user_id = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (user_id, now, identity_id),
                )
            await conn.commit()
        result = await self.get(platform, platform_user_id)
        if result is None:
            raise RuntimeError("Failed to persist user identity mapping.")
        return result

    async def list_all(
        self,
        *,
        user_id: str | None = None,
        platform: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        if platform is not None:
            clauses.append("platform = ?")
            params.append(platform)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                f"""
                SELECT {', '.join(IDENTITY_COLUMNS)} FROM user_identities
                {where}
                ORDER BY user_id ASC, platform ASC, platform_user_id ASC
                """,
                params,
            )
            rows = await cursor.fetchall()
        return [row_to_dict(row, IDENTITY_COLUMNS) for row in rows]

    async def reassign_user(self, source_user_id: str, target_user_id: str) -> None:
        if not source_user_id or source_user_id == target_user_id:
            return
        async with self._db.get_connection() as conn:
            await conn.execute(
                """
                UPDATE user_identities
                SET user_id = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (target_user_id, now_utc(), source_user_id),
            )
            await conn.commit()
