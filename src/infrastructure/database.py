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
from src.core.user_scope import SINGLE_USER_ID

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from src.core.config import StorageConfig

logger = get_logger(__name__)

# Bump this when schema changes require migration
SCHEMA_VERSION = 7

_SCHEMA_SQL = """\
-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL,
    applied_at TEXT NOT NULL
);

-- Conversations
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '{single_user_id}',
    title TEXT,
    summary TEXT,
    platform TEXT NOT NULL DEFAULT 'unknown',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Messages
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    model TEXT,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
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
    user_id TEXT NOT NULL DEFAULT '{single_user_id}',
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
    user_id TEXT NOT NULL DEFAULT '{single_user_id}',
    category TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    evidence TEXT,
    confidence REAL DEFAULT 0.5,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, category, key)
);

CREATE INDEX IF NOT EXISTS idx_preferences_category
    ON preferences(category);
-- User identities
CREATE TABLE IF NOT EXISTS user_identities (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    platform_user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(platform, platform_user_id)
);

CREATE INDEX IF NOT EXISTS idx_user_identities_user_id
    ON user_identities(user_id);

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
    embedding float[{dimensions}]
);

CREATE VIRTUAL TABLE IF NOT EXISTS conversation_embeddings USING vec0(
    conversation_id TEXT PRIMARY KEY,
    embedding float[{dimensions}]
);
"""


def _migration_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


class Database:
    """Async SQLite database with sqlite-vec vector extension.

    Usage::

        db = Database(config)
        await db.initialize()
        async with db.get_connection() as conn:
            rows = await conn.execute_fetchall("SELECT ...")
        await db.close()
    """

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
        """Active database connection.

        Raises:
            RuntimeError: If the database has not been initialized.
        """
        if self._conn is None:
            raise RuntimeError("Database not initialized. Call await database.initialize() first.")
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
        await conn.executescript(_SCHEMA_SQL.format(single_user_id=SINGLE_USER_ID))

        if current_version != 0:
            await self._apply_migrations(current_version)

        await self._ensure_user_scope_indexes()

        # Apply vec0 virtual tables (executescript resets the connection
        # state which drops loaded extensions, so use individual executes)
        vec_sql = _VEC_TABLES_SQL.format(dimensions=self._embedding_dimensions)
        for statement in vec_sql.strip().split(";"):
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
            cursor = await conn.execute("SELECT MAX(version) FROM schema_version")
            row = await cursor.fetchone()
            return row[0] if row and row[0] is not None else 0
        except aiosqlite.OperationalError:
            # Table does not exist yet
            return 0

    async def _apply_migrations(self, current_version: int) -> None:
        """Apply incremental migrations required after the base schema."""
        if current_version < 5:
            await self._migrate_to_v5()
        if current_version < 6:
            await self._migrate_to_v6()
        if current_version < 7:
            await self._migrate_to_v7()

    async def _migrate_to_v5(self) -> None:
        """Backfill user-scoped memory tables and identity mapping support."""
        await self._ensure_column(
            "conversations",
            "user_id",
            "TEXT NOT NULL DEFAULT ''",
        )
        await self._ensure_column(
            "knowledge",
            "user_id",
            "TEXT NOT NULL DEFAULT ''",
        )
        await self._recreate_preferences_with_user_scope()

    async def _migrate_to_v6(self) -> None:
        """Remove the deprecated cost column from the messages table."""
        if not await self._has_column("messages", "cost"):
            return

        await self.connection.executescript(
            """
            CREATE TABLE messages_v6 (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                model TEXT,
                tokens_in INTEGER DEFAULT 0,
                tokens_out INTEGER DEFAULT 0,
                latency_ms INTEGER DEFAULT 0,
                tool_calls TEXT,
                metadata TEXT,
                created_at TEXT NOT NULL
            );

            INSERT INTO messages_v6
                (id, conversation_id, role, content, model, tokens_in,
                 tokens_out, latency_ms, tool_calls, metadata, created_at)
            SELECT
                id, conversation_id, role, content, model, tokens_in,
                tokens_out, latency_ms, tool_calls, metadata, created_at
            FROM messages;

            DROP TABLE messages;
            ALTER TABLE messages_v6 RENAME TO messages;
            """
        )

    async def _ensure_column(
        self,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        """Add a missing column without failing on already-migrated DBs."""
        if await self._has_column(table, column):
            return
        await self.connection.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}",
        )

    async def _has_column(self, table: str, column: str) -> bool:
        """Return True when *table* already has *column*."""
        cursor = await self.connection.execute(f"PRAGMA table_info({table})")
        rows = await cursor.fetchall()
        return any(row[1] == column for row in rows)

    async def _recreate_preferences_with_user_scope(self) -> None:
        """Rebuild the preferences table so uniqueness includes user_id."""
        if await self._has_column("preferences", "user_id"):
            return

        await self.connection.executescript(
            """
            CREATE TABLE preferences_v5 (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                evidence TEXT,
                confidence REAL DEFAULT 0.5,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, category, key)
            );

            INSERT INTO preferences_v5
                (id, user_id, category, key, value, evidence, confidence,
                 created_at, updated_at)
            SELECT
                id, '', category, key, value, evidence, confidence,
                created_at, updated_at
            FROM preferences;

            DROP TABLE preferences;
            ALTER TABLE preferences_v5 RENAME TO preferences;
            """
        )

    async def _ensure_user_scope_indexes(self) -> None:
        """Create indexes that may need to be recreated after migrations."""
        statements = [
            "CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id)",
            "CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_knowledge_user_id ON knowledge(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_preferences_user_id ON preferences(user_id)",
        ]
        for statement in statements:
            await self.connection.execute(statement)

    async def _migrate_to_v7(self) -> None:
        """Collapse historical data into the single-user memory scope."""
        await self.connection.execute(
            "UPDATE conversations SET user_id = ?, updated_at = ?",
            (SINGLE_USER_ID, _migration_now()),
        )
        await self.connection.execute(
            "UPDATE knowledge SET user_id = ?, updated_at = ?",
            (SINGLE_USER_ID, _migration_now()),
        )
        await self.connection.execute(
            "UPDATE user_identities SET user_id = ?, updated_at = ?",
            (SINGLE_USER_ID, _migration_now()),
        )
        await self._recreate_preferences_for_single_user()
        await self.connection.commit()

    async def _recreate_preferences_for_single_user(self) -> None:
        """Rebuild preferences so all rows live under the single-user scope."""
        await self.connection.executescript(
            f"""
            CREATE TABLE preferences_v7 (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT '{SINGLE_USER_ID}',
                category TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                evidence TEXT,
                confidence REAL DEFAULT 0.5,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, category, key)
            );

            INSERT INTO preferences_v7
                (id, user_id, category, key, value, evidence, confidence,
                 created_at, updated_at)
            SELECT
                ranked.id,
                '{SINGLE_USER_ID}',
                ranked.category,
                ranked.key,
                ranked.value,
                ranked.evidence,
                ranked.confidence,
                ranked.created_at,
                ranked.updated_at
            FROM (
                SELECT
                    id, category, key, value, evidence, confidence, created_at, updated_at,
                    ROW_NUMBER() OVER (
                        PARTITION BY category, key
                        ORDER BY updated_at DESC,
                                 COALESCE(confidence, 0) DESC,
                                 created_at DESC,
                                 id DESC
                    ) AS row_num
                FROM preferences
            ) AS ranked
            WHERE ranked.row_num = 1;

            DROP TABLE preferences;
            ALTER TABLE preferences_v7 RENAME TO preferences;
            """
        )
