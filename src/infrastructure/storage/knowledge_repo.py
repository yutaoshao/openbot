"""Knowledge storage repository."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._base import json_dumps, now_utc, row_to_dict

if TYPE_CHECKING:
    from src.infrastructure.database import Database

KNOWLEDGE_COLUMNS = [
    "id",
    "user_id",
    "source_conversation_id",
    "category",
    "content",
    "tags",
    "priority",
    "confidence",
    "access_count",
    "created_at",
    "updated_at",
    "expires_at",
]
KNOWLEDGE_JSON_FIELDS = {"tags"}


class KnowledgeRepo:
    """CRUD + search for the ``knowledge`` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def add(
        self,
        id: str,
        user_id: str,
        category: str,
        content: str,
        tags: list[str] | None = None,
        priority: str = "P1",
        confidence: float | None = None,
        source_conversation_id: str | None = None,
        expires_at: str | None = None,
    ) -> None:
        now = now_utc()
        async with self._db.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO knowledge
                    (id, user_id, source_conversation_id, category, content, tags,
                     priority, confidence, access_count,
                     created_at, updated_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    id,
                    user_id,
                    source_conversation_id,
                    category,
                    content,
                    json_dumps(tags),
                    priority,
                    confidence,
                    now,
                    now,
                    expires_at,
                ),
            )
            await conn.commit()

    async def get(self, id: str) -> dict[str, Any] | None:
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                f"SELECT {', '.join(KNOWLEDGE_COLUMNS)} FROM knowledge WHERE id = ?",
                (id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return row_to_dict(row, KNOWLEDGE_COLUMNS, KNOWLEDGE_JSON_FIELDS)

    async def update(self, id: str, **fields: Any) -> None:
        allowed = {
            "category",
            "content",
            "tags",
            "priority",
            "confidence",
            "expires_at",
            "updated_at",
        }
        to_set: dict[str, Any] = {}
        for key, value in fields.items():
            if key not in allowed:
                continue
            to_set[key] = json_dumps(value) if key == "tags" else value
        if not to_set:
            return
        to_set.setdefault("updated_at", now_utc())
        set_clause = ", ".join(f"{key} = ?" for key in to_set)
        params = [*to_set.values(), id]
        async with self._db.get_connection() as conn:
            await conn.execute(f"UPDATE knowledge SET {set_clause} WHERE id = ?", params)
            await conn.commit()

    async def list_all(
        self,
        category: str | None = None,
        priority: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if category is not None:
            clauses.append("category = ?")
            params.append(category)
        if priority is not None:
            clauses.append("priority = ?")
            params.append(priority)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.extend([limit, offset])
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                f"""
                SELECT {', '.join(KNOWLEDGE_COLUMNS)} FROM knowledge
                {where}
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                params,
            )
            rows = await cursor.fetchall()
        return [row_to_dict(row, KNOWLEDGE_COLUMNS, KNOWLEDGE_JSON_FIELDS) for row in rows]

    async def search(
        self,
        query: str,
        limit: int = 10,
        user_id: str | None = None,
        include_legacy: bool = False,
    ) -> list[dict[str, Any]]:
        pattern = f"%{query}%"
        clauses = ["(content LIKE ? OR tags LIKE ?)"]
        params: list[Any] = [pattern, pattern]
        if user_id is not None:
            if include_legacy:
                clauses.append("(user_id = ? OR user_id = '')")
            else:
                clauses.append("user_id = ?")
            params.append(user_id)
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                f"""
                SELECT {', '.join(KNOWLEDGE_COLUMNS)} FROM knowledge
                WHERE {' AND '.join(clauses)}
                ORDER BY access_count DESC, updated_at DESC
                LIMIT ?
                """,
                [*params, limit],
            )
            rows = await cursor.fetchall()
        return [row_to_dict(row, KNOWLEDGE_COLUMNS, KNOWLEDGE_JSON_FIELDS) for row in rows]

    async def increment_access(self, id: str) -> None:
        async with self._db.get_connection() as conn:
            await conn.execute(
                "UPDATE knowledge SET access_count = access_count + 1 WHERE id = ?",
                (id,),
            )
            await conn.commit()

    async def delete(self, id: str) -> None:
        async with self._db.get_connection() as conn:
            await conn.execute("DELETE FROM knowledge WHERE id = ?", (id,))
            await conn.commit()

    async def delete_expired(self) -> int:
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                "DELETE FROM knowledge WHERE expires_at IS NOT NULL AND expires_at < ?",
                (now_utc(),),
            )
            await conn.commit()
            return cursor.rowcount

    async def reassign_user(self, source_user_id: str, target_user_id: str) -> None:
        if not source_user_id or source_user_id == target_user_id:
            return
        async with self._db.get_connection() as conn:
            await conn.execute(
                """
                UPDATE knowledge
                SET user_id = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (target_user_id, now_utc(), source_user_id),
            )
            await conn.commit()
