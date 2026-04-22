"""Schedules storage repository."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._base import new_id, now_utc, row_to_dict

if TYPE_CHECKING:
    from src.infrastructure.database import Database

SCHEDULE_COLUMNS = [
    "id",
    "name",
    "prompt",
    "cron",
    "target_platform",
    "target_id",
    "status",
    "last_run_at",
    "next_run_at",
    "created_at",
    "updated_at",
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
        schedule_id = new_id()
        now = now_utc()
        async with self._db.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO schedules
                    (id, name, prompt, cron, target_platform, target_id,
                     status, next_run_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    schedule_id,
                    name,
                    prompt,
                    cron,
                    target_platform,
                    target_id,
                    status,
                    next_run_at,
                    now,
                    now,
                ),
            )
            await conn.commit()
        return {
            "id": schedule_id,
            "name": name,
            "prompt": prompt,
            "cron": cron,
            "target_platform": target_platform,
            "target_id": target_id,
            "status": status,
            "last_run_at": None,
            "next_run_at": next_run_at,
            "created_at": now,
            "updated_at": now,
        }

    async def get(self, id: str) -> dict[str, Any] | None:
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                f"SELECT {', '.join(SCHEDULE_COLUMNS)} FROM schedules WHERE id = ?",
                (id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return row_to_dict(row, SCHEDULE_COLUMNS)

    async def update(self, id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {
            "name",
            "prompt",
            "cron",
            "target_platform",
            "target_id",
            "status",
            "last_run_at",
            "next_run_at",
        }
        to_set = {key: value for key, value in fields.items() if key in allowed}
        if not to_set:
            return await self.get(id)
        to_set["updated_at"] = now_utc()
        set_clause = ", ".join(f"{key} = ?" for key in to_set)
        params = [*to_set.values(), id]
        async with self._db.get_connection() as conn:
            await conn.execute(f"UPDATE schedules SET {set_clause} WHERE id = ?", params)
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
                SELECT {", ".join(SCHEDULE_COLUMNS)} FROM schedules
                {where}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                params,
            )
            rows = await cursor.fetchall()
        return [row_to_dict(row, SCHEDULE_COLUMNS) for row in rows]

    async def list_active(self) -> list[dict[str, Any]]:
        return await self.list_all(status="active")

    async def delete(self, id: str) -> None:
        async with self._db.get_connection() as conn:
            await conn.execute("DELETE FROM schedules WHERE id = ?", (id,))
            await conn.commit()
