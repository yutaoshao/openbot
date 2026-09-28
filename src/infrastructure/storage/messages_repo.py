"""Message storage repository."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.memory.request_budget import estimate_input_tokens

from ._base import json_dumps, now_utc, row_to_dict

if TYPE_CHECKING:
    from src.infrastructure.database import Database

MESSAGE_COLUMNS = [
    "id",
    "conversation_id",
    "role",
    "content",
    "timestamp",
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
        timestamp: datetime | str,
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
                    (id, conversation_id, role, content, timestamp, model,
                     tokens_in, tokens_out, latency_ms,
                     tool_calls, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    id,
                    conversation_id,
                    role,
                    content,
                    _timestamp_text(timestamp),
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
            ORDER BY timestamp ASC, created_at ASC
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
                ORDER BY timestamp DESC, created_at DESC
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
                ORDER BY m.timestamp DESC, m.created_at DESC
                """,
                params,
            )
            rows = await cursor.fetchall()
        return self._select_rows_within_budget(rows, token_budget)

    async def get_working_summary(self) -> dict[str, Any] | None:
        async with self._db.get_connection() as conn:
            row = await (await conn.execute(
                "SELECT boundary_id, content, version FROM working_memory_summaries "
                "WHERE timeline = 'shared'"
            )).fetchone()
        return dict(row) if row else None

    async def save_working_summary(self, boundary_id: str, content: str) -> None:
        async with self._db.get_connection() as conn:
            if not await (await conn.execute(
                "SELECT id FROM messages WHERE id = ?", (boundary_id,)
            )).fetchone():
                raise ValueError(f"Compressed source missing from database: {boundary_id}")
            await conn.execute("""
                INSERT INTO working_memory_summaries
                    (timeline, boundary_id, content, version, updated_at)
                VALUES ('shared', ?, ?, 1, ?)
                ON CONFLICT(timeline) DO UPDATE SET
                    boundary_id=excluded.boundary_id,
                    content=excluded.content,
                    version=working_memory_summaries.version + 1,
                    updated_at=excluded.updated_at
            """, (boundary_id, content, now_utc()))
            await conn.commit()

    async def get_global_after(
        self, boundary_id: str, include_platforms: tuple[str, ...], *, user_id: str
    ) -> list[dict[str, Any]]:
        async with self._db.get_connection() as conn:
            boundary = await (await conn.execute(
                "SELECT timestamp, created_at FROM messages WHERE id = ?", (boundary_id,)
            )).fetchone()
            if not boundary:
                raise ValueError(f"Compressed source missing from database: {boundary_id}")
            if not include_platforms:
                return []
            placeholders = ", ".join("?" for _ in include_platforms)
            rows = await (await conn.execute(f"""
                SELECT m.{", m.".join(MESSAGE_COLUMNS)} FROM messages m
                JOIN conversations c ON c.id = m.conversation_id
                WHERE c.platform IN ({placeholders}) AND c.user_id = ? AND
                  (m.timestamp > ? OR (m.timestamp = ? AND m.created_at > ?) OR
                   (m.timestamp = ? AND m.created_at = ? AND m.id > ?))
                ORDER BY m.timestamp, m.created_at, m.id
            """, (*include_platforms, user_id, boundary[0], boundary[0], boundary[1],
                  boundary[0], boundary[1], boundary_id))).fetchall()
        return [row_to_dict(row, MESSAGE_COLUMNS, MESSAGE_JSON_FIELDS) for row in rows]

    async def get_global_history(
        self, include_platforms: tuple[str, ...], *, user_id: str
    ) -> list[dict[str, Any]]:
        if not include_platforms:
            return []
        placeholders = ", ".join("?" for _ in include_platforms)
        async with self._db.get_connection() as conn:
            rows = await (await conn.execute(f"""
                SELECT m.{", m.".join(MESSAGE_COLUMNS)} FROM messages m
                JOIN conversations c ON c.id = m.conversation_id
                WHERE c.platform IN ({placeholders}) AND c.user_id = ?
                ORDER BY m.timestamp, m.created_at, m.id
            """, (*include_platforms, user_id))).fetchall()
        return [row_to_dict(row, MESSAGE_COLUMNS, MESSAGE_JSON_FIELDS) for row in rows]

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
        chronological = [row_to_dict(row, MESSAGE_COLUMNS, MESSAGE_JSON_FIELDS)
                         for row in reversed(rows)]
        pairs: list[list[int]] = []
        pending: dict[str, int] = {}
        for index, item in enumerate(chronological):
            conversation_id = item["conversation_id"]
            if item["role"] == "user":
                if conversation_id in pending:
                    pairs.append([pending[conversation_id]])
                pending[conversation_id] = index
            elif item["role"] == "assistant" and conversation_id in pending:
                pairs.append([pending.pop(conversation_id), index])
        pairs.extend([index] for index in pending.values())
        pairs.sort(key=lambda group: max(group))
        selected: set[int] = set()
        used = 32
        for group in reversed(pairs):
            cost = estimate_input_tokens([chronological[index] for index in group]).tokens - 32
            if selected and used + cost > token_budget:
                break
            selected.update(group)
            used += cost
        return [item for index, item in enumerate(chronological) if index in selected]


def _timestamp_text(value: datetime | str) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("message timestamp must be timezone-aware")
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        return value
    raise ValueError("message timestamp is required")
