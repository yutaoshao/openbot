"""Preference storage repository."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._base import json_dumps, now_utc, row_to_dict

if TYPE_CHECKING:
    from src.infrastructure.database import Database

PREFERENCE_COLUMNS = [
    "id",
    "user_id",
    "category",
    "key",
    "value",
    "evidence",
    "confidence",
    "created_at",
    "updated_at",
]
PREFERENCE_JSON_FIELDS = {"evidence"}


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
        now = now_utc()
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT id FROM preferences
                WHERE user_id = ? AND category = ? AND key = ?
                """,
                (user_id, category, key),
            )
            existing = await cursor.fetchone()
            if existing:
                await conn.execute(
                    """
                    UPDATE preferences
                    SET value = ?, evidence = ?, confidence = ?, updated_at = ?
                    WHERE user_id = ? AND category = ? AND key = ?
                    """,
                    (
                        value,
                        json_dumps(evidence),
                        confidence,
                        now,
                        user_id,
                        category,
                        key,
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
                        id,
                        user_id,
                        category,
                        key,
                        value,
                        json_dumps(evidence),
                        confidence,
                        now,
                        now,
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
            f"SELECT {', '.join(PREFERENCE_COLUMNS)} FROM preferences "
            "WHERE user_id = ? AND category = ? AND key = ?"
        )
        params: list[Any] = [user_id, category, key]
        if include_legacy:
            sql = (
                f"SELECT {', '.join(PREFERENCE_COLUMNS)} FROM preferences "
                "WHERE (user_id = ? OR user_id = '') "
                "AND category = ? AND key = ? "
                "ORDER BY CASE WHEN user_id = ? THEN 0 ELSE 1 END "
                "LIMIT 1"
            )
            params.append(user_id)
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(sql, params)
            row = await cursor.fetchone()
        if row is None:
            return None
        return row_to_dict(row, PREFERENCE_COLUMNS, PREFERENCE_JSON_FIELDS)

    async def get_by_category(
        self,
        user_id: str,
        category: str,
        *,
        include_legacy: bool = True,
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT {', '.join(PREFERENCE_COLUMNS)} FROM preferences "
            "WHERE user_id = ? AND category = ? "
            "ORDER BY key ASC"
        )
        params: list[Any] = [user_id, category]
        if include_legacy:
            sql = (
                f"SELECT {', '.join(PREFERENCE_COLUMNS)} FROM preferences "
                "WHERE (user_id = ? OR user_id = '') AND category = ? "
                "ORDER BY user_id DESC, key ASC"
            )
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(sql, params)
            rows = await cursor.fetchall()
        return [row_to_dict(row, PREFERENCE_COLUMNS, PREFERENCE_JSON_FIELDS) for row in rows]

    async def get_all(
        self,
        user_id: str,
        *,
        include_legacy: bool = True,
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT {', '.join(PREFERENCE_COLUMNS)} FROM preferences "
            "WHERE user_id = ? ORDER BY category ASC, key ASC"
        )
        params: list[Any] = [user_id]
        if include_legacy:
            sql = (
                f"SELECT {', '.join(PREFERENCE_COLUMNS)} FROM preferences "
                "WHERE user_id = ? OR user_id = '' "
                "ORDER BY user_id DESC, category ASC, key ASC"
            )
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(sql, params)
            rows = await cursor.fetchall()
        return [row_to_dict(row, PREFERENCE_COLUMNS, PREFERENCE_JSON_FIELDS) for row in rows]

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

    async def reassign_user(self, source_user_id: str, target_user_id: str) -> None:
        if not source_user_id or source_user_id == target_user_id:
            return
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                f"""
                SELECT {", ".join(PREFERENCE_COLUMNS)} FROM preferences
                WHERE user_id = ?
                ORDER BY category ASC, key ASC
                """,
                (source_user_id,),
            )
            rows = await cursor.fetchall()
            for row in rows:
                pref = row_to_dict(row, PREFERENCE_COLUMNS, PREFERENCE_JSON_FIELDS)
                target_cursor = await conn.execute(
                    f"""
                    SELECT {", ".join(PREFERENCE_COLUMNS)} FROM preferences
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
                        (target_user_id, now_utc(), pref["id"]),
                    )
                    continue
                target_pref = row_to_dict(
                    target_row,
                    PREFERENCE_COLUMNS,
                    PREFERENCE_JSON_FIELDS,
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
                        json_dumps(merged_evidence),
                        merged_confidence,
                        now_utc(),
                        target_pref["id"],
                    ),
                )
                await conn.execute("DELETE FROM preferences WHERE id = ?", (pref["id"],))
            await conn.commit()

    @staticmethod
    def _merge_evidence(left: list[str] | None, right: list[str] | None) -> list[str]:
        merged: list[str] = []
        for value in [*(left or []), *(right or [])]:
            if value not in merged:
                merged.append(value)
        return merged
