"""Metrics storage repository."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._base import json_dumps, now_utc, row_to_dict

if TYPE_CHECKING:
    from src.infrastructure.database import Database

METRIC_COLUMNS = ["id", "event_name", "data", "timestamp"]
METRIC_JSON_FIELDS = {"data"}


class MetricsRepo:
    """Append-only event recording and time-range queries for ``metrics``."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(self, event_name: str, data: dict[str, Any]) -> None:
        async with self._db.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO metrics (event_name, data, timestamp)
                VALUES (?, ?, ?)
                """,
                (event_name, json_dumps(data), now_utc()),
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
                SELECT {', '.join(METRIC_COLUMNS)} FROM metrics
                {where}
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                params,
            )
            rows = await cursor.fetchall()
        return [row_to_dict(row, METRIC_COLUMNS, METRIC_JSON_FIELDS) for row in rows]

    async def query_multi(
        self,
        event_names: list[str],
        start: str | None = None,
        limit: int = 5000,
    ) -> dict[str, list[dict[str, Any]]]:
        if not event_names:
            return {}
        placeholders = ", ".join("?" for _ in event_names)
        clauses = [f"event_name IN ({placeholders})"]
        params: list[Any] = list(event_names)
        if start is not None:
            clauses.append("timestamp >= ?")
            params.append(start)
        params.append(limit)
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                f"""
                SELECT {', '.join(METRIC_COLUMNS)} FROM metrics
                WHERE {' AND '.join(clauses)}
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                params,
            )
            rows = await cursor.fetchall()
        result: dict[str, list[dict[str, Any]]] = {name: [] for name in event_names}
        for row in rows:
            item = row_to_dict(row, METRIC_COLUMNS, METRIC_JSON_FIELDS)
            event_name = item.get("event_name", "")
            if event_name in result:
                result[event_name].append(item)
        return result
