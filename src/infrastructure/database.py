"""SQLite database initialization with sqlite-vec vector extension.

Manages async database connections, schema creation, migrations,
and sqlite-vec virtual tables for vector similarity search.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import TYPE_CHECKING

import aiosqlite
import sqlite_vec

from src.core.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from src.core.config import StorageConfig

logger = get_logger(__name__)

# Bump this when schema changes require migration
SCHEMA_VERSION = 3

_SCHEMA_SQL = """\
-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL,
    applied_at TEXT NOT NULL
);

-- Conversations
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT,
    summary TEXT,
    core TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Messages
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    model TEXT,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    cost REAL DEFAULT 0.0,
    latency_ms INTEGER DEFAULT 0,
    tool_calls TEXT,
    metadata TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_id
    ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_created_at
    ON messages(created_at);

-- Knowledge
CREATE TABLE IF NOT EXISTS knowledge (
    id TEXT PRIMARY KEY,
    source_conversation_id TEXT,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    tags TEXT,
    priority TEXT NOT NULL DEFAULT 'P1',
    confidence REAL DEFAULT 1.0,
    access_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_knowledge_category
    ON knowledge(category);
CREATE INDEX IF NOT EXISTS idx_knowledge_priority
    ON knowledge(priority);
CREATE INDEX IF NOT EXISTS idx_knowledge_expires_at
    ON knowledge(expires_at);

-- Preferences
CREATE TABLE IF NOT EXISTS preferences (
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    evidence TEXT,
    confidence REAL DEFAULT 0.5,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(category, key)
);

CREATE INDEX IF NOT EXISTS idx_preferences_category
    ON preferences(category);

-- Metrics
CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_name TEXT NOT NULL,
    data TEXT NOT NULL,
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_metrics_event_name
    ON metrics(event_name);
CREATE INDEX IF NOT EXISTS idx_metrics_timestamp
    ON metrics(timestamp);

-- Logs (AgentTrace three-surface structured logs)
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    level TEXT NOT NULL,
    event TEXT NOT NULL,
    surface TEXT,
    trace_id TEXT,
    interaction_id TEXT,
    platform TEXT,
    iteration INTEGER,
    data TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_logs_trace_id ON logs(trace_id);
CREATE INDEX IF NOT EXISTS idx_logs_interaction_id ON logs(interaction_id);
CREATE INDEX IF NOT EXISTS idx_logs_event ON logs(event);
CREATE INDEX IF NOT EXISTS idx_logs_surface ON logs(surface);
CREATE INDEX IF NOT EXISTS idx_logs_level ON logs(level);

-- Schedules
CREATE TABLE IF NOT EXISTS schedules (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    prompt TEXT NOT NULL,
    cron TEXT NOT NULL,
    target_platform TEXT,
    target_id TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    last_run_at TEXT,
    next_run_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_schedules_status
    ON schedules(status);
CREATE INDEX IF NOT EXISTS idx_schedules_next_run_at
    ON schedules(next_run_at);
"""

_VEC_TABLES_SQL = """\
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_embeddings USING vec0(
    knowledge_id TEXT PRIMARY KEY,
    embedding float[1536]
);

CREATE VIRTUAL TABLE IF NOT EXISTS conversation_embeddings USING vec0(
    conversation_id TEXT PRIMARY KEY,
    embedding float[1536]
);
"""


class Database:
    """Async SQLite database with sqlite-vec vector extension.

    Usage::

        db = Database(config)
        await db.initialize()
        async with db.get_connection() as conn:
            rows = await conn.execute_fetchall("SELECT ...")
        await db.close()
    """

    def __init__(self, config: StorageConfig) -> None:
        self._db_path = config.db_path
        self._conn: aiosqlite.Connection | None = None

    @property
    def db_path(self) -> str:
        """Resolved database file path."""
        return self._db_path

    @property
    def connection(self) -> aiosqlite.Connection:
        """Active database connection.

        Raises:
            RuntimeError: If the database has not been initialized.
        """
        if self._conn is None:
            raise RuntimeError(
                "Database not initialized. Call await database.initialize() first."
            )
        return self._conn

    async def initialize(self) -> None:
        """Open the database, load extensions, and apply schema.

        Creates the parent directory if it does not exist, enables WAL mode
        and foreign keys, loads sqlite-vec, and runs schema migrations.
        """
        db_dir = Path(self._db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row

        # Enable WAL mode and foreign keys
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")

        # Load sqlite-vec extension
        await self._load_vec_extension()

        # Apply schema
        await self._apply_schema()

        logger.info(
            "database.initialized",
            db_path=self._db_path,
            schema_version=SCHEMA_VERSION,
        )

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
            logger.info("database.closed", db_path=self._db_path)

    @contextlib.asynccontextmanager
    async def get_connection(self) -> AsyncIterator[aiosqlite.Connection]:
        """Yield the shared database connection.

        Ensures the connection is initialized before use.

        Yields:
            The active ``aiosqlite.Connection``.

        Raises:
            RuntimeError: If the database has not been initialized.
        """
        yield self.connection

    async def _load_vec_extension(self) -> None:
        """Load the sqlite-vec loadable extension."""
        conn = self.connection
        await conn.enable_load_extension(True)
        await conn.load_extension(sqlite_vec.loadable_path())
        await conn.enable_load_extension(False)
        logger.debug("database.vec_extension_loaded")

    async def _apply_schema(self) -> None:
        """Apply schema and track version.

        Checks the current schema version and applies migrations when the
        stored version is older than ``SCHEMA_VERSION``.  On a fresh database
        (no ``schema_version`` table) the full schema is created from scratch.
        """
        conn = self.connection

        current_version = await self._get_schema_version()

        if current_version >= SCHEMA_VERSION:
            logger.debug(
                "database.schema_up_to_date",
                version=current_version,
            )
            return

        # Apply core tables and indexes
        await conn.executescript(_SCHEMA_SQL)

        # Apply vec0 virtual tables (executescript resets the connection
        # state which drops loaded extensions, so use individual executes)
        for statement in _VEC_TABLES_SQL.strip().split(";"):
            statement = statement.strip()
            if statement:
                await conn.execute(statement)

        # Record schema version
        from datetime import UTC, datetime

        await conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION, datetime.now(UTC).isoformat()),
        )
        await conn.commit()

        logger.info(
            "database.schema_applied",
            previous_version=current_version,
            new_version=SCHEMA_VERSION,
        )

    async def _get_schema_version(self) -> int:
        """Return the current schema version, or 0 if not yet tracked."""
        conn = self.connection
        try:
            cursor = await conn.execute(
                "SELECT MAX(version) FROM schema_version"
            )
            row = await cursor.fetchone()
            return row[0] if row and row[0] is not None else 0
        except aiosqlite.OperationalError:
            # Table does not exist yet
            return 0
