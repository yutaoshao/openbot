"""Durable position of personal-memory extraction for each conversation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.infrastructure.database import Database


class PersonalProgressRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, conversation_id: str) -> int:
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT cursor FROM personal_memory_progress WHERE conversation_id = ?",
                (conversation_id,),
            )
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def advance(self, conversation_id: str, cursor: int) -> None:
        async with self._db.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO personal_memory_progress (conversation_id, cursor)
                VALUES (?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET cursor = excluded.cursor
                WHERE excluded.cursor >= personal_memory_progress.cursor
                """,
                (conversation_id, cursor),
            )
            await conn.commit()

    async def stage(self, source: str, stage: str) -> tuple[list[dict], bool] | None:
        async with self._db.get_connection() as conn:
            row = await (
                await conn.execute(
                    "SELECT payload, complete FROM memory_stage_results "
                    "WHERE source = ? AND stage = ?",
                    (source, stage),
                )
            ).fetchone()
        return (json.loads(row[0]), bool(row[1])) if row else None

    async def save_stage(self, source: str, stage: str, payload: list[dict]) -> None:
        async with self._db.get_connection() as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO memory_stage_results (source, stage, payload) "
                "VALUES (?, ?, ?)",
                (source, stage, json.dumps(payload, ensure_ascii=False)),
            )
            await conn.commit()

    async def invalidate_stage(self, source: str, stage: str) -> None:
        async with self._db.get_connection() as conn:
            await conn.execute(
                "DELETE FROM memory_stage_results WHERE source = ? AND stage = ? AND complete = 0",
                (source, stage),
            )
            await conn.commit()

    async def complete_stage(self, source: str, stage: str) -> None:
        async with self._db.get_connection() as conn:
            await conn.execute(
                "UPDATE memory_stage_results SET complete = 1 WHERE source = ? AND stage = ?",
                (source, stage),
            )
            await conn.commit()
