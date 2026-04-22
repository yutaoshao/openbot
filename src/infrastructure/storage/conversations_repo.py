"""Conversation storage repository."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.core.user_scope import SINGLE_USER_ID

from ._base import now_utc, row_to_dict

if TYPE_CHECKING:
    from src.infrastructure.database import Database

CONVERSATION_COLUMNS = [
    "id",
    "user_id",
    "title",
    "summary",
    "platform",
    "created_at",
    "updated_at",
]


class ConversationRepo:
    """CRUD + search for the ``conversations`` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        id: str,
        platform: str,
        user_id: str = SINGLE_USER_ID,
        title: str | None = None,
    ) -> None:
        now = now_utc()
        async with self._db.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO conversations
                    (id, user_id, platform, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (id, user_id, platform, title, now, now),
            )
            await conn.commit()

    async def get(self, id: str) -> dict[str, Any] | None:
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                f"SELECT {', '.join(CONVERSATION_COLUMNS)} FROM conversations WHERE id = ?",
                (id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return row_to_dict(row, CONVERSATION_COLUMNS)

    async def update(self, id: str, **fields: Any) -> None:
        allowed = {"user_id", "title", "summary", "updated_at"}
        to_set = {key: value for key, value in fields.items() if key in allowed}
        if not to_set:
            return
        to_set.setdefault("updated_at", now_utc())
        set_clause = ", ".join(f"{key} = ?" for key in to_set)
        params = [*to_set.values(), id]
        async with self._db.get_connection() as conn:
            await conn.execute(f"UPDATE conversations SET {set_clause} WHERE id = ?", params)
            await conn.commit()

    async def reassign_user(
        self,
        source_user_id: str,
        target_user_id: str,
    ) -> None:
        if not source_user_id or source_user_id == target_user_id:
            return
        async with self._db.get_connection() as conn:
            await conn.execute(
                """
                UPDATE conversations
                SET user_id = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (target_user_id, now_utc(), source_user_id),
            )
            await conn.commit()

    async def list_recent(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                f"""
                SELECT {', '.join(CONVERSATION_COLUMNS)} FROM conversations
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )
            rows = await cursor.fetchall()
        return [row_to_dict(row, CONVERSATION_COLUMNS) for row in rows]

    async def search(
        self,
        query: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        pattern = f"%{query}%"
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                f"""
                SELECT {', '.join(CONVERSATION_COLUMNS)} FROM conversations
                WHERE title LIKE ? OR summary LIKE ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (pattern, pattern, limit),
            )
            rows = await cursor.fetchall()
        return [row_to_dict(row, CONVERSATION_COLUMNS) for row in rows]

    async def delete(self, id: str) -> None:
        async with self._db.get_connection() as conn:
            await conn.execute("DELETE FROM conversations WHERE id = ?", (id,))
            await conn.commit()
