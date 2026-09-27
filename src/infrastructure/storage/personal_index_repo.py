"""Disposable search projections of versioned Markdown paragraphs."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.infrastructure.database import Database


class PersonalIndexRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def all(self) -> list[dict]:
        async with self._db.get_connection() as conn:
            rows = await (await conn.execute("SELECT * FROM personal_search_chunks")).fetchall()
        return [{**dict(row), "embedding": json.loads(row["embedding"])} for row in rows]

    async def replace(self, chunks: list[dict]) -> None:
        async with self._db.get_connection() as conn:
            await conn.execute("DELETE FROM personal_search_chunks")
            await conn.executemany(
                """INSERT INTO personal_search_chunks
                   (id, path, revision, section, content, embedding_model, embedding)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        item["id"],
                        item["path"],
                        item["revision"],
                        item["section"],
                        item["content"],
                        item["embedding_model"],
                        json.dumps(item["embedding"]),
                    )
                    for item in chunks
                ],
            )
            await conn.commit()
