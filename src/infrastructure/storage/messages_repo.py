"""Message storage repository."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._base import CHARS_PER_TOKEN, json_dumps, now_utc, row_to_dict

if TYPE_CHECKING:
    from src.infrastructure.database import Database

MESSAGE_COLUMNS = [
    "id",
    "conversation_id",
    "role",
    "content",
    "model",
    "tokens_in",
    "tokens_out",
    "latency_ms",
    "tool_calls",
    "metadata",
    "created_at",
]
MESSAGE_JSON_FIELDS = {"tool_calls", "metadata"}


class MessageRepo:
    """Insert / query operations for the ``messages`` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def add(
        self,
        id: str,
        conversation_id: str,
        role: str,
        content: str,
        model: str | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        latency_ms: int | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        async with self._db.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO messages
                    (id, conversation_id, role, content, model,
                     tokens_in, tokens_out, latency_ms,
                     tool_calls, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    id,
                    conversation_id,
                    role,
                    content,
                    model,
                    tokens_in,
                    tokens_out,
                    latency_ms,
                    json_dumps(tool_calls),
                    json_dumps(metadata),
                    now_utc(),
                ),
            )
            await conn.commit()

    async def get_by_conversation(
        self,
        conversation_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        sql = f"""
            SELECT {", ".join(MESSAGE_COLUMNS)} FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at ASC
        """
        params: list[Any] = [conversation_id]
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(sql, params)
            rows = await cursor.fetchall()
        return [row_to_dict(row, MESSAGE_COLUMNS, MESSAGE_JSON_FIELDS) for row in rows]

    async def get_recent(
        self,
        conversation_id: str,
        token_budget: int,
    ) -> list[dict[str, Any]]:
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                f"""
                SELECT {", ".join(MESSAGE_COLUMNS)} FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at DESC
                """,
                (conversation_id,),
            )
            rows = await cursor.fetchall()
        return self._select_rows_within_budget(rows, token_budget)

    async def get_recent_global(
        self,
        token_budget: int,
        include_platforms: tuple[str, ...],
        *,
        user_id: str,
    ) -> list[dict[str, Any]]:
        if not include_platforms:
            return []
        placeholders = ", ".join("?" for _ in include_platforms)
        params = [*include_platforms, user_id]
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                f"""
                SELECT m.{", m.".join(MESSAGE_COLUMNS)}
                FROM messages AS m
                JOIN conversations AS c ON c.id = m.conversation_id
                WHERE c.platform IN ({placeholders}) AND c.user_id = ?
                ORDER BY m.created_at DESC
                """,
                params,
            )
            rows = await cursor.fetchall()
        return self._select_rows_within_budget(rows, token_budget)

    async def count_by_conversation(self, conversation_id: str) -> int:
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            )
            row = await cursor.fetchone()
        return row[0] if row else 0

    async def count_by_conversations(self, conversation_ids: list[str]) -> dict[str, int]:
        if not conversation_ids:
            return {}
        placeholders = ", ".join("?" for _ in conversation_ids)
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                f"""
                SELECT conversation_id, COUNT(*)
                FROM messages
                WHERE conversation_id IN ({placeholders})
                GROUP BY conversation_id
                """,
                conversation_ids,
            )
            rows = await cursor.fetchall()
        return {row[0]: row[1] for row in rows}

    @staticmethod
    def _select_rows_within_budget(rows: list[Any], token_budget: int) -> list[dict[str, Any]]:
        char_budget = token_budget * CHARS_PER_TOKEN
        selected: list[Any] = []
        used = 0
        content_idx = MESSAGE_COLUMNS.index("content")
        for row in rows:
            content = row[content_idx] or ""
            content_chars = len(content)
            if used + content_chars > char_budget:
                break
            selected.append(row)
            used += content_chars
        selected.reverse()
        return [row_to_dict(row, MESSAGE_COLUMNS, MESSAGE_JSON_FIELDS) for row in selected]
