"""SQLite database initialization with sqlite-vec vector extension."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import TYPE_CHECKING

import aiosqlite
import sqlite_vec

from src.core.logging import get_logger
from src.core.user_scope import SINGLE_USER_ID

from .database_migrations import DatabaseMigrationMixin
from .database_schema import SCHEMA_SQL, VEC_TABLES_SQL

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from src.core.config import StorageConfig

logger = get_logger(__name__)

SCHEMA_VERSION = 7


class Database(DatabaseMigrationMixin):
    """Async SQLite database with sqlite-vec vector extension."""

    def __init__(self, config: StorageConfig, *, embedding_dimensions: int = 1024) -> None:
        self._db_path = config.db_path
        self._embedding_dimensions = embedding_dimensions
        self._conn: aiosqlite.Connection | None = None

    @property
    def db_path(self) -> str:
        """Resolved database file path."""
        return self._db_path

    @property
    def connection(self) -> aiosqlite.Connection:
        """Active database connection."""
        if self._conn is None:
            raise RuntimeError("Database not initialized. Call await database.initialize() first.")
        return self._conn

    async def initialize(self) -> None:
        """Open the database, load extensions, and apply schema."""
        db_dir = Path(self._db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._load_vec_extension()
        await self._apply_schema()
        logger.info(
            "database.initialized",
            db_path=self._db_path,
            schema_version=SCHEMA_VERSION,
        )

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn is None:
            return
        await self._conn.close()
        self._conn = None
        logger.info("database.closed", db_path=self._db_path)

    @contextlib.asynccontextmanager
    async def get_connection(self) -> AsyncIterator[aiosqlite.Connection]:
        """Yield the shared database connection."""
        yield self.connection

    async def _load_vec_extension(self) -> None:
        conn = self.connection
        await conn.enable_load_extension(True)
        await conn.load_extension(sqlite_vec.loadable_path())
        await conn.enable_load_extension(False)
        logger.debug("database.vec_extension_loaded")

    async def _apply_schema(self) -> None:
        conn = self.connection
        current_version = await self._get_schema_version()
        if current_version >= SCHEMA_VERSION:
            logger.debug("database.schema_up_to_date", version=current_version)
            return

        await conn.executescript(SCHEMA_SQL.format(single_user_id=SINGLE_USER_ID))
        if current_version != 0:
            await self._apply_migrations(current_version)
        await self._ensure_user_scope_indexes()
        await self._apply_vec_tables()
        await self._record_schema_version()
        logger.info(
            "database.schema_applied",
            previous_version=current_version,
            new_version=SCHEMA_VERSION,
        )

    async def _get_schema_version(self) -> int:
        try:
            cursor = await self.connection.execute("SELECT MAX(version) FROM schema_version")
            row = await cursor.fetchone()
            return row[0] if row and row[0] is not None else 0
        except aiosqlite.OperationalError:
            return 0

    async def _apply_vec_tables(self) -> None:
        vec_sql = VEC_TABLES_SQL.format(dimensions=self._embedding_dimensions)
        for statement in vec_sql.strip().split(";"):
            statement = statement.strip()
            if statement:
                await self.connection.execute(statement)

    async def _record_schema_version(self) -> None:
        from datetime import UTC, datetime

        await self.connection.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION, datetime.now(UTC).isoformat()),
        )
        await self.connection.commit()
