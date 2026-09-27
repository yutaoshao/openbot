"""Durable transport receipts and event-specific follow-up interaction state."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ._base import now_utc

if TYPE_CHECKING:
    from src.infrastructure.database import Database


class FollowupsRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record_delivery(
        self, *, delivery_id: str, conversation_id: str, content: str, candidates: list[dict]
    ) -> None:
        async with self._db.get_connection() as conn:
            await conn.execute(
                """INSERT OR IGNORE INTO memory_deliveries
                   (id, conversation_id, content, candidates, delivered_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    delivery_id,
                    conversation_id,
                    content,
                    json.dumps(candidates, ensure_ascii=False),
                    now_utc(),
                ),
            )
            await conn.commit()

    async def pending(self) -> list[dict]:
        async with self._db.get_connection() as conn:
            rows = await (
                await conn.execute(
                    "SELECT * FROM memory_deliveries WHERE processed = 0 ORDER BY delivered_at"
                )
            ).fetchall()
        return [{**dict(row), "candidates": json.loads(row["candidates"])} for row in rows]

    async def finish_delivery(self, receipt: dict, asked: list[dict]) -> None:
        async with self._db.get_connection() as conn:
            await conn.executemany(
                """INSERT OR IGNORE INTO memory_followups
                   (event_id, field, question, asked_source, asked_at) VALUES (?, ?, ?, ?, ?)""",
                [
                    (
                        item["event_id"],
                        item["field"],
                        item["question"],
                        f"delivery:{receipt['id']}",
                        receipt["delivered_at"],
                    )
                    for item in asked
                ],
            )
            await conn.execute(
                "UPDATE memory_deliveries SET processed = 1 WHERE id = ?", (receipt["id"],)
            )
            await conn.commit()

    async def asked(self) -> set[tuple[str, str]]:
        async with self._db.get_connection() as conn:
            rows = await (
                await conn.execute("SELECT event_id, field FROM memory_followups")
            ).fetchall()
        return {(row[0], row[1]) for row in rows}

    async def resolve(self, event_id: str, source: str) -> None:
        async with self._db.get_connection() as conn:
            await conn.execute(
                "UPDATE memory_followups SET answered_source = ? WHERE event_id = ?",
                (source, event_id),
            )
            await conn.commit()
