"""Typed repository layer on top of SQLite.

Provides high-level data access through sub-repositories grouped under a
single ``Storage`` facade.  Each repository maps to one database table and
exposes only the operations the rest of the application needs.

All SQL uses parameterized queries.  JSON columns (tool_calls, metadata,
tags, evidence) are serialised on write and deserialised on read.
"""

from __future__ import annotations

import contextlib
import json
import uuid
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.core.logging import get_logger

if TYPE_CHECKING:
    from src.infrastructure.database import Database

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CHARS_PER_TOKEN = 4  # heuristic for token budget estimation


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


def _json_dumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=_json_default)


def _json_default(value: Any) -> Any:
    """Best-effort conversion for non-JSON-native runtime objects."""
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        with contextlib.suppress(Exception):
            return model_dump()

    return str(value)


def _json_loads(raw: str | None) -> Any:
    if raw is None:
        return None
    return json.loads(raw)


def _row_to_dict(
    row: Any,
    columns: list[str],
    json_fields: set[str] | None = None,
) -> dict[str, Any]:
    """Convert an ``aiosqlite.Row`` (tuple) into a dict, parsing JSON cols."""
    result: dict[str, Any] = {}
    for idx, col in enumerate(columns):
        value = row[idx]
        if json_fields and col in json_fields and isinstance(value, str):
            value = _json_loads(value)
        result[col] = value
    return result


# ---------------------------------------------------------------------------
# ConversationRepo
# ---------------------------------------------------------------------------

_CONV_COLS = [
    "id", "user_id", "title", "summary", "platform", "created_at", "updated_at",
]


class ConversationRepo:
    """CRUD + search for the ``conversations`` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        id: str,
        platform: str,
        user_id: str = "",
        title: str | None = None,
    ) -> None:
        now = _now()
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
                f"SELECT {', '.join(_CONV_COLS)} FROM conversations WHERE id = ?",
                (id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_dict(row, _CONV_COLS)

    async def update(self, id: str, **fields: Any) -> None:
        allowed = {"user_id", "title", "summary", "updated_at"}
        to_set = {k: v for k, v in fields.items() if k in allowed}
        if not to_set:
            return
        to_set.setdefault("updated_at", _now())
        set_clause = ", ".join(f"{k} = ?" for k in to_set)
        params = [*to_set.values(), id]
        async with self._db.get_connection() as conn:
            await conn.execute(
                f"UPDATE conversations SET {set_clause} WHERE id = ?",
                params,
            )
            await conn.commit()

    async def reassign_user(
        self,
        source_user_id: str,
        target_user_id: str,
    ) -> None:
        """Move all conversation ownership from one user to another."""
        if not source_user_id or source_user_id == target_user_id:
            return
        async with self._db.get_connection() as conn:
            await conn.execute(
                """
                UPDATE conversations
                SET user_id = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (target_user_id, _now(), source_user_id),
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
                SELECT {', '.join(_CONV_COLS)} FROM conversations
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )
            rows = await cursor.fetchall()
        return [_row_to_dict(r, _CONV_COLS) for r in rows]

    async def search(
        self,
        query: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        pattern = f"%{query}%"
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                f"""
                SELECT {', '.join(_CONV_COLS)} FROM conversations
                WHERE title LIKE ? OR summary LIKE ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (pattern, pattern, limit),
            )
            rows = await cursor.fetchall()
        return [_row_to_dict(r, _CONV_COLS) for r in rows]

    async def delete(self, id: str) -> None:
        async with self._db.get_connection() as conn:
            await conn.execute(
                "DELETE FROM conversations WHERE id = ?", (id,)
            )
            await conn.commit()


# ---------------------------------------------------------------------------
# MessageRepo
# ---------------------------------------------------------------------------

_MSG_COLS = [
    "id", "conversation_id", "role", "content", "model",
    "tokens_in", "tokens_out", "latency_ms",
    "tool_calls", "metadata", "created_at",
]
_MSG_JSON_FIELDS = {"tool_calls", "metadata"}


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
                    id, conversation_id, role, content, model,
                    tokens_in, tokens_out, latency_ms,
                    _json_dumps(tool_calls), _json_dumps(metadata),
                    _now(),
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
            SELECT {', '.join(_MSG_COLS)} FROM messages
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
        return [
            _row_to_dict(r, _MSG_COLS, _MSG_JSON_FIELDS) for r in rows
        ]

    async def get_recent(
        self,
        conversation_id: str,
        token_budget: int,
    ) -> list[dict[str, Any]]:
        """Return most-recent messages that fit within *token_budget*.

        Uses a simple heuristic of ~4 characters per token.  Messages are
        returned in chronological order (oldest first).
        """
        char_budget = token_budget * _CHARS_PER_TOKEN
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                f"""
                SELECT {', '.join(_MSG_COLS)} FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at DESC
                """,
                (conversation_id,),
            )
            rows = await cursor.fetchall()

        selected: list[Any] = []
        used = 0
        for row in rows:
            content = row[_MSG_COLS.index("content")] or ""
            content_chars = len(content)
            if used + content_chars > char_budget:
                break
            selected.append(row)
            used += content_chars

        selected.reverse()
        return [
            _row_to_dict(r, _MSG_COLS, _MSG_JSON_FIELDS) for r in selected
        ]

    async def count_by_conversation(self, conversation_id: str) -> int:
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            )
            row = await cursor.fetchone()
        return row[0] if row else 0

    async def count_by_conversations(
        self, conversation_ids: list[str],
    ) -> dict[str, int]:
        """Return message counts for multiple conversations in one query."""
        if not conversation_ids:
            return {}
        placeholders = ", ".join("?" for _ in conversation_ids)
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                f"SELECT conversation_id, COUNT(*) FROM messages "
                f"WHERE conversation_id IN ({placeholders}) "
                f"GROUP BY conversation_id",
                conversation_ids,
            )
            rows = await cursor.fetchall()
        return {row[0]: row[1] for row in rows}


# ---------------------------------------------------------------------------
# KnowledgeRepo
# ---------------------------------------------------------------------------

_KNOW_COLS = [
    "id", "user_id", "source_conversation_id", "category", "content", "tags",
    "priority", "confidence", "access_count",
    "created_at", "updated_at", "expires_at",
]
_KNOW_JSON_FIELDS = {"tags"}


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
        now = _now()
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
                    id, user_id, source_conversation_id, category, content,
                    _json_dumps(tags), priority, confidence,
                    now, now, expires_at,
                ),
            )
            await conn.commit()

    async def get(self, id: str) -> dict[str, Any] | None:
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                f"SELECT {', '.join(_KNOW_COLS)} FROM knowledge "
                "WHERE id = ?",
                (id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_dict(row, _KNOW_COLS, _KNOW_JSON_FIELDS)

    async def update(self, id: str, **fields: Any) -> None:
        allowed = {
            "category", "content", "tags", "priority",
            "confidence", "expires_at", "updated_at",
        }
        to_set: dict[str, Any] = {}
        for k, v in fields.items():
            if k not in allowed:
                continue
            to_set[k] = _json_dumps(v) if k == "tags" else v
        if not to_set:
            return
        to_set.setdefault("updated_at", _now())
        set_clause = ", ".join(f"{k} = ?" for k in to_set)
        params = [*to_set.values(), id]
        async with self._db.get_connection() as conn:
            await conn.execute(
                f"UPDATE knowledge SET {set_clause} WHERE id = ?",
                params,
            )
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
                SELECT {', '.join(_KNOW_COLS)} FROM knowledge
                {where}
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                params,
            )
            rows = await cursor.fetchall()
        return [
            _row_to_dict(r, _KNOW_COLS, _KNOW_JSON_FIELDS) for r in rows
        ]

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
                SELECT {', '.join(_KNOW_COLS)} FROM knowledge
                WHERE {' AND '.join(clauses)}
                ORDER BY access_count DESC, updated_at DESC
                LIMIT ?
                """,
                [*params, limit],
            )
            rows = await cursor.fetchall()
        return [
            _row_to_dict(r, _KNOW_COLS, _KNOW_JSON_FIELDS) for r in rows
        ]

    async def increment_access(self, id: str) -> None:
        async with self._db.get_connection() as conn:
            await conn.execute(
                "UPDATE knowledge SET access_count = access_count + 1 "
                "WHERE id = ?",
                (id,),
            )
            await conn.commit()

    async def delete(self, id: str) -> None:
        async with self._db.get_connection() as conn:
            await conn.execute(
                "DELETE FROM knowledge WHERE id = ?", (id,)
            )
            await conn.commit()

    async def delete_expired(self) -> int:
        """Delete knowledge rows past their ``expires_at`` and return count."""
        now = _now()
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                "DELETE FROM knowledge "
                "WHERE expires_at IS NOT NULL AND expires_at < ?",
                (now,),
            )
            await conn.commit()
            return cursor.rowcount

    async def reassign_user(
        self,
        source_user_id: str,
        target_user_id: str,
    ) -> None:
        """Move all user-scoped knowledge from one user to another."""
        if not source_user_id or source_user_id == target_user_id:
            return
        async with self._db.get_connection() as conn:
            await conn.execute(
                """
                UPDATE knowledge
                SET user_id = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (target_user_id, _now(), source_user_id),
            )
            await conn.commit()


# ---------------------------------------------------------------------------
# PreferenceRepo
# ---------------------------------------------------------------------------

_PREF_COLS = [
    "id", "user_id", "category", "key", "value", "evidence",
    "confidence", "created_at", "updated_at",
]
_PREF_JSON_FIELDS = {"evidence"}


class PreferenceRepo:
    """Upsert / query for the ``preferences`` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def set(
        self,
        id: str,
        user_id: str,
        category: str,
        key: str,
        value: str,
        evidence: list[str] | None = None,
        confidence: float | None = None,
    ) -> None:
        """Insert or update a preference keyed by (user_id, category, key)."""
        now = _now()
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT id FROM preferences "
                "WHERE user_id = ? AND category = ? AND key = ?",
                (user_id, category, key),
            )
            existing = await cursor.fetchone()
            if existing:
                await conn.execute(
                    """
                    UPDATE preferences
                    SET value = ?, evidence = ?, confidence = ?,
                        updated_at = ?
                    WHERE user_id = ? AND category = ? AND key = ?
                    """,
                    (
                        value, _json_dumps(evidence), confidence,
                        now, user_id, category, key,
                    ),
                )
            else:
                await conn.execute(
                    """
                    INSERT INTO preferences
                        (id, user_id, category, key, value, evidence, confidence,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        id, user_id, category, key, value,
                        _json_dumps(evidence), confidence, now, now,
                    ),
                )
            await conn.commit()

    async def get(
        self,
        user_id: str,
        category: str,
        key: str,
        *,
        include_legacy: bool = False,
    ) -> dict[str, Any] | None:
        sql = (
            f"SELECT {', '.join(_PREF_COLS)} FROM preferences "
            "WHERE user_id = ? AND category = ? AND key = ?"
        )
        params: list[Any] = [user_id, category, key]
        if include_legacy:
            sql = (
                f"SELECT {', '.join(_PREF_COLS)} FROM preferences "
                "WHERE (user_id = ? OR user_id = '') "
                "AND category = ? AND key = ? "
                "ORDER BY CASE WHEN user_id = ? THEN 0 ELSE 1 END "
                "LIMIT 1"
            )
            params.append(user_id)
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                sql,
                params,
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_dict(row, _PREF_COLS, _PREF_JSON_FIELDS)

    async def get_by_category(
        self,
        user_id: str,
        category: str,
        *,
        include_legacy: bool = True,
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT {', '.join(_PREF_COLS)} FROM preferences "
            "WHERE user_id = ? AND category = ? "
            "ORDER BY key ASC"
        )
        params: list[Any] = [user_id, category]
        if include_legacy:
            sql = (
                f"SELECT {', '.join(_PREF_COLS)} FROM preferences "
                "WHERE (user_id = ? OR user_id = '') AND category = ? "
                "ORDER BY user_id DESC, key ASC"
            )
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                sql,
                params,
            )
            rows = await cursor.fetchall()
        return [
            _row_to_dict(r, _PREF_COLS, _PREF_JSON_FIELDS) for r in rows
        ]

    async def get_all(
        self,
        user_id: str,
        *,
        include_legacy: bool = True,
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT {', '.join(_PREF_COLS)} FROM preferences "
            "WHERE user_id = ? "
            "ORDER BY category ASC, key ASC"
        )
        params: list[Any] = [user_id]
        if include_legacy:
            sql = (
                f"SELECT {', '.join(_PREF_COLS)} FROM preferences "
                "WHERE user_id = ? OR user_id = '' "
                "ORDER BY user_id DESC, category ASC, key ASC"
            )
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                sql,
                params,
            )
            rows = await cursor.fetchall()
        return [
            _row_to_dict(r, _PREF_COLS, _PREF_JSON_FIELDS) for r in rows
        ]

    async def delete(self, user_id: str, category: str, key: str) -> None:
        async with self._db.get_connection() as conn:
            await conn.execute(
                """
                DELETE FROM preferences
                WHERE user_id = ? AND category = ? AND key = ?
                """,
                (user_id, category, key),
            )
            await conn.commit()

    async def reassign_user(
        self,
        source_user_id: str,
        target_user_id: str,
    ) -> None:
        """Move preferences to another user, merging duplicate keys."""
        if not source_user_id or source_user_id == target_user_id:
            return

        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                f"""
                SELECT {', '.join(_PREF_COLS)} FROM preferences
                WHERE user_id = ?
                ORDER BY category ASC, key ASC
                """,
                (source_user_id,),
            )
            rows = await cursor.fetchall()
            for row in rows:
                pref = _row_to_dict(row, _PREF_COLS, _PREF_JSON_FIELDS)
                target_cursor = await conn.execute(
                    f"""
                    SELECT {', '.join(_PREF_COLS)} FROM preferences
                    WHERE user_id = ? AND category = ? AND key = ?
                    """,
                    (target_user_id, pref["category"], pref["key"]),
                )
                target_row = await target_cursor.fetchone()
                if target_row is None:
                    await conn.execute(
                        """
                        UPDATE preferences
                        SET user_id = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (target_user_id, _now(), pref["id"]),
                    )
                    continue

                target_pref = _row_to_dict(
                    target_row,
                    _PREF_COLS,
                    _PREF_JSON_FIELDS,
                )
                merged_evidence = self._merge_evidence(
                    target_pref.get("evidence"),
                    pref.get("evidence"),
                )
                merged_confidence = max(
                    float(target_pref.get("confidence") or 0.0),
                    float(pref.get("confidence") or 0.0),
                )
                await conn.execute(
                    """
                    UPDATE preferences
                    SET evidence = ?, confidence = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        _json_dumps(merged_evidence),
                        merged_confidence,
                        _now(),
                        target_pref["id"],
                    ),
                )
                await conn.execute(
                    "DELETE FROM preferences WHERE id = ?",
                    (pref["id"],),
                )
            await conn.commit()

    @staticmethod
    def _merge_evidence(
        left: list[str] | None,
        right: list[str] | None,
    ) -> list[str]:
        merged: list[str] = []
        for value in [*(left or []), *(right or [])]:
            if value not in merged:
                merged.append(value)
        return merged


# ---------------------------------------------------------------------------
# UserIdentityRepo
# ---------------------------------------------------------------------------

_IDENTITY_COLS = [
    "id", "user_id", "platform", "platform_user_id", "created_at", "updated_at",
]


class UserIdentityRepo:
    """Mappings from platform-specific accounts to canonical user ids."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(
        self,
        platform: str,
        platform_user_id: str,
    ) -> dict[str, Any] | None:
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                f"""
                SELECT {', '.join(_IDENTITY_COLS)} FROM user_identities
                WHERE platform = ? AND platform_user_id = ?
                """,
                (platform, platform_user_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_dict(row, _IDENTITY_COLS)

    async def set(
        self,
        *,
        user_id: str,
        platform: str,
        platform_user_id: str,
    ) -> dict[str, Any]:
        now = _now()
        existing = await self.get(platform, platform_user_id)
        async with self._db.get_connection() as conn:
            if existing is None:
                identity_id = _new_id()
                await conn.execute(
                    """
                    INSERT INTO user_identities
                        (id, user_id, platform, platform_user_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        identity_id,
                        user_id,
                        platform,
                        platform_user_id,
                        now,
                        now,
                    ),
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
                SELECT {', '.join(_IDENTITY_COLS)} FROM user_identities
                {where}
                ORDER BY user_id ASC, platform ASC, platform_user_id ASC
                """,
                params,
            )
            rows = await cursor.fetchall()
        return [_row_to_dict(row, _IDENTITY_COLS) for row in rows]

    async def reassign_user(
        self,
        source_user_id: str,
        target_user_id: str,
    ) -> None:
        """Move all identity rows from one canonical user to another."""
        if not source_user_id or source_user_id == target_user_id:
            return
        async with self._db.get_connection() as conn:
            await conn.execute(
                """
                UPDATE user_identities
                SET user_id = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (target_user_id, _now(), source_user_id),
            )
            await conn.commit()


# ---------------------------------------------------------------------------
# MetricsRepo
# ---------------------------------------------------------------------------

_METRIC_COLS = ["id", "event_name", "data", "timestamp"]
_METRIC_JSON_FIELDS = {"data"}


class MetricsRepo:
    """Append-only event recording and time-range queries for ``metrics``."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self,
        event_name: str,
        data: dict[str, Any],
    ) -> None:
        async with self._db.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO metrics (event_name, data, timestamp)
                VALUES (?, ?, ?)
                """,
                (event_name, _json_dumps(data), _now()),
            )
            await conn.commit()

    async def query(
        self,
        event_name: str | None = None,
        start: str | None = None,
        end: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if event_name is not None:
            clauses.append("event_name = ?")
            params.append(event_name)
        if start is not None:
            clauses.append("timestamp >= ?")
            params.append(start)
        if end is not None:
            clauses.append("timestamp <= ?")
            params.append(end)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                f"""
                SELECT {', '.join(_METRIC_COLS)} FROM metrics
                {where}
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                params,
            )
            rows = await cursor.fetchall()
        return [
            _row_to_dict(r, _METRIC_COLS, _METRIC_JSON_FIELDS)
            for r in rows
        ]

    async def query_multi(
        self,
        event_names: list[str],
        start: str | None = None,
        limit: int = 5000,
    ) -> dict[str, list[dict[str, Any]]]:
        """Query multiple event types in a single DB call.

        Returns a dict keyed by event_name -> list of rows.
        """
        if not event_names:
            return {}
        placeholders = ", ".join("?" for _ in event_names)
        clauses = [f"event_name IN ({placeholders})"]
        params: list[Any] = list(event_names)
        if start is not None:
            clauses.append("timestamp >= ?")
            params.append(start)
        where = "WHERE " + " AND ".join(clauses)
        params.append(limit)
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                f"""
                SELECT {', '.join(_METRIC_COLS)} FROM metrics
                {where}
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                params,
            )
            rows = await cursor.fetchall()
        result: dict[str, list[dict[str, Any]]] = {name: [] for name in event_names}
        for r in rows:
            row_dict = _row_to_dict(r, _METRIC_COLS, _METRIC_JSON_FIELDS)
            ev = row_dict.get("event_name", "")
            if ev in result:
                result[ev].append(row_dict)
        return result


# ---------------------------------------------------------------------------
# ScheduleRepo
# ---------------------------------------------------------------------------

_SCHED_COLS = [
    "id", "name", "prompt", "cron", "target_platform", "target_id",
    "status", "last_run_at", "next_run_at", "created_at", "updated_at",
]


class ScheduleRepo:
    """CRUD for the ``schedules`` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        name: str,
        prompt: str,
        cron: str,
        target_platform: str | None = None,
        target_id: str | None = None,
        status: str = "active",
        next_run_at: str | None = None,
    ) -> dict[str, Any]:
        sched_id = _new_id()
        now = _now()
        async with self._db.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO schedules
                    (id, name, prompt, cron, target_platform, target_id,
                     status, next_run_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sched_id, name, prompt, cron, target_platform, target_id,
                    status, next_run_at, now, now,
                ),
            )
            await conn.commit()
        return {
            "id": sched_id, "name": name, "prompt": prompt, "cron": cron,
            "target_platform": target_platform, "target_id": target_id,
            "status": status, "last_run_at": None,
            "next_run_at": next_run_at, "created_at": now, "updated_at": now,
        }

    async def get(self, id: str) -> dict[str, Any] | None:
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                f"SELECT {', '.join(_SCHED_COLS)} FROM schedules WHERE id = ?",
                (id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_dict(row, _SCHED_COLS)

    async def update(self, id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {
            "name", "prompt", "cron", "target_platform", "target_id",
            "status", "last_run_at", "next_run_at",
        }
        to_set = {k: v for k, v in fields.items() if k in allowed}
        if not to_set:
            return await self.get(id)
        to_set["updated_at"] = _now()
        set_clause = ", ".join(f"{k} = ?" for k in to_set)
        params = [*to_set.values(), id]
        async with self._db.get_connection() as conn:
            await conn.execute(
                f"UPDATE schedules SET {set_clause} WHERE id = ?",
                params,
            )
            await conn.commit()
        return await self.get(id)

    async def list_all(
        self,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.extend([limit, offset])
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                f"""
                SELECT {', '.join(_SCHED_COLS)} FROM schedules
                {where}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                params,
            )
            rows = await cursor.fetchall()
        return [_row_to_dict(r, _SCHED_COLS) for r in rows]

    async def list_active(self) -> list[dict[str, Any]]:
        """Return all schedules with status='active'."""
        return await self.list_all(status="active")

    async def delete(self, id: str) -> None:
        async with self._db.get_connection() as conn:
            await conn.execute(
                "DELETE FROM schedules WHERE id = ?", (id,),
            )
            await conn.commit()


# ---------------------------------------------------------------------------
# LogRepo
# ---------------------------------------------------------------------------

_LOG_COLS = [
    "id", "timestamp", "level", "event", "surface",
    "trace_id", "interaction_id", "platform", "iteration", "data",
]


class LogRepo:
    """CRUD for the ``logs`` table (AgentTrace structured logs)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert(
        self,
        timestamp: str,
        level: str,
        event: str,
        surface: str | None = None,
        trace_id: str | None = None,
        interaction_id: str | None = None,
        platform: str | None = None,
        iteration: int | None = None,
        data: str | None = None,
    ) -> None:
        """Insert a single log entry."""
        async with self._db.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO logs
                    (timestamp, level, event, surface, trace_id,
                     interaction_id, platform, iteration, data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp, level, event, surface, trace_id,
                    interaction_id, platform, iteration, data,
                ),
            )
            await conn.commit()

    async def insert_batch(self, entries: list[dict[str, Any]]) -> None:
        """Insert multiple log entries in a single transaction."""
        if not entries:
            return
        async with self._db.get_connection() as conn:
            await conn.executemany(
                """
                INSERT INTO logs
                    (timestamp, level, event, surface, trace_id,
                     interaction_id, platform, iteration, data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        e.get("timestamp", ""), e.get("level", "info"),
                        e.get("event", ""), e.get("surface"),
                        e.get("trace_id"), e.get("interaction_id"),
                        e.get("platform"), e.get("iteration"),
                        e.get("data"),
                    )
                    for e in entries
                ],
            )
            await conn.commit()

    async def query(
        self,
        *,
        trace_id: str | None = None,
        interaction_id: str | None = None,
        platform: str | None = None,
        surface: str | None = None,
        level: str | None = None,
        event: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Query logs with optional filters."""
        clauses: list[str] = []
        params: list[Any] = []

        if trace_id:
            clauses.append("trace_id = ?")
            params.append(trace_id)
        if interaction_id:
            clauses.append("interaction_id = ?")
            params.append(interaction_id)
        if platform:
            clauses.append("platform = ?")
            params.append(platform)
        if surface:
            clauses.append("surface = ?")
            params.append(surface)
        if level:
            clauses.append("level = ?")
            params.append(level)
        if event:
            clauses.append("event = ?")
            params.append(event)
        if since:
            clauses.append("timestamp >= ?")
            params.append(since)
        if until:
            clauses.append("timestamp <= ?")
            params.append(until)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.extend([limit, offset])

        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                f"""
                SELECT {', '.join(_LOG_COLS)} FROM logs
                {where}
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                params,
            )
            rows = await cursor.fetchall()
        return [_row_to_dict(r, _LOG_COLS) for r in rows]

    async def count(
        self,
        *,
        since: str | None = None,
        platform: str | None = None,
        surface: str | None = None,
        level: str | None = None,
    ) -> int:
        """Count log entries with optional filters."""
        clauses: list[str] = []
        params: list[Any] = []
        if since:
            clauses.append("timestamp >= ?")
            params.append(since)
        if platform:
            clauses.append("platform = ?")
            params.append(platform)
        if surface:
            clauses.append("surface = ?")
            params.append(surface)
        if level:
            clauses.append("level = ?")
            params.append(level)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                f"SELECT COUNT(*) FROM logs {where}", params,
            )
            row = await cursor.fetchone()
        return row[0] if row else 0


# ---------------------------------------------------------------------------
# Storage facade
# ---------------------------------------------------------------------------


class Storage:
    """Top-level data access object aggregating all repositories."""

    def __init__(self, db: Database) -> None:
        self.conversations = ConversationRepo(db)
        self.messages = MessageRepo(db)
        self.knowledge = KnowledgeRepo(db)
        self.preferences = PreferenceRepo(db)
        self.user_identities = UserIdentityRepo(db)
        self.metrics = MetricsRepo(db)
        self.schedules = ScheduleRepo(db)
        self.logs = LogRepo(db)
