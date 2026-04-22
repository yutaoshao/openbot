"""Schema migration helpers for the SQLite storage layer."""

from __future__ import annotations

from src.core.user_scope import SINGLE_USER_ID


def migration_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


class DatabaseMigrationMixin:
    """Reusable migration helpers shared by ``Database``."""

    async def _apply_migrations(self, current_version: int) -> None:
        if current_version < 5:
            await self._migrate_to_v5()
        if current_version < 6:
            await self._migrate_to_v6()
        if current_version < 7:
            await self._migrate_to_v7()

    async def _migrate_to_v5(self) -> None:
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
        if await self._has_column(table, column):
            return
        await self.connection.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}",
        )

    async def _has_column(self, table: str, column: str) -> bool:
        cursor = await self.connection.execute(f"PRAGMA table_info({table})")
        rows = await cursor.fetchall()
        return any(row[1] == column for row in rows)

    async def _recreate_preferences_with_user_scope(self) -> None:
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
        await self.connection.execute(
            "UPDATE conversations SET user_id = ?, updated_at = ?",
            (SINGLE_USER_ID, migration_now()),
        )
        await self.connection.execute(
            "UPDATE knowledge SET user_id = ?, updated_at = ?",
            (SINGLE_USER_ID, migration_now()),
        )
        await self.connection.execute(
            "UPDATE user_identities SET user_id = ?, updated_at = ?",
            (SINGLE_USER_ID, migration_now()),
        )
        await self._recreate_preferences_for_single_user()
        await self.connection.commit()

    async def _recreate_preferences_for_single_user(self) -> None:
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
