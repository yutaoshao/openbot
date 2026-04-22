"""Structured logs storage repository."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._base import row_to_dict

if TYPE_CHECKING:
    from src.infrastructure.database import Database

LOG_COLUMNS = [
    "id",
    "timestamp",
    "level",
    "event",
    "surface",
    "trace_id",
    "interaction_id",
    "platform",
    "iteration",
    "data",
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
        async with self._db.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO logs
                    (timestamp, level, event, surface, trace_id,
                     interaction_id, platform, iteration, data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp,
                    level,
                    event,
                    surface,
                    trace_id,
                    interaction_id,
                    platform,
                    iteration,
                    data,
                ),
            )
            await conn.commit()

    async def insert_batch(self, entries: list[dict[str, Any]]) -> None:
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
                        entry.get("timestamp", ""),
                        entry.get("level", "info"),
                        entry.get("event", ""),
                        entry.get("surface"),
                        entry.get("trace_id"),
                        entry.get("interaction_id"),
                        entry.get("platform"),
                        entry.get("iteration"),
                        entry.get("data"),
                    )
                    for entry in entries
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
                SELECT {', '.join(LOG_COLUMNS)} FROM logs
                {where}
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                params,
            )
            rows = await cursor.fetchall()
        return [row_to_dict(row, LOG_COLUMNS) for row in rows]

    async def count(
        self,
        *,
        since: str | None = None,
        platform: str | None = None,
        surface: str | None = None,
        level: str | None = None,
    ) -> int:
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
            cursor = await conn.execute(f"SELECT COUNT(*) FROM logs {where}", params)
            row = await cursor.fetchone()
        return row[0] if row else 0
