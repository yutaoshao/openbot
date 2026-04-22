from __future__ import annotations

import sqlite3

from src.core.config import StorageConfig
from src.core.user_scope import SINGLE_USER_ID
from src.infrastructure.database import Database


async def test_migrate_to_v6_removes_message_cost_column(tmp_path) -> None:
    db_path = tmp_path / "openbot.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE schema_version (
            version INTEGER NOT NULL,
            applied_at TEXT NOT NULL
        );
        INSERT INTO schema_version (version, applied_at)
        VALUES (5, '2026-04-12T00:00:00+00:00');

        CREATE TABLE conversations (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL DEFAULT '',
            title TEXT,
            summary TEXT,
            platform TEXT NOT NULL DEFAULT 'unknown',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        INSERT INTO conversations
            (id, user_id, title, summary, platform, created_at, updated_at)
        VALUES
            ('conv-1', 'user-1', 't', 's', 'web',
             '2026-04-12T00:00:00+00:00', '2026-04-12T00:00:00+00:00');

        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
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

        INSERT INTO messages
            (id, conversation_id, role, content, model, tokens_in, tokens_out,
             cost, latency_ms, tool_calls, metadata, created_at)
        VALUES
            ('msg-1', 'conv-1', 'assistant', 'hello', 'test-model',
             3, 5, 0.12, 42, '[]', '{}', '2026-04-12T00:00:00+00:00');
        """
    )
    conn.commit()
    conn.close()

    db = Database(StorageConfig(db_path=str(db_path)))
    await db.initialize()

    async with db.get_connection() as migrated:
        columns = await migrated.execute_fetchall("PRAGMA table_info(messages)")
        rows = await migrated.execute_fetchall(
            """
            SELECT id, conversation_id, role, content, model,
                   tokens_in, tokens_out, latency_ms, tool_calls, metadata, created_at
            FROM messages
            """
        )

    await db.close()

    column_names = [row[1] for row in columns]
    assert "cost" not in column_names
    assert len(rows) == 1
    assert rows[0][0] == "msg-1"
    assert rows[0][5] == 3
    assert rows[0][6] == 5


async def test_migrate_to_v7_collapses_history_into_single_user_scope(tmp_path) -> None:
    db_path = tmp_path / "openbot.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE schema_version (
            version INTEGER NOT NULL,
            applied_at TEXT NOT NULL
        );
        INSERT INTO schema_version (version, applied_at)
        VALUES (6, '2026-04-20T00:00:00+00:00');

        CREATE TABLE conversations (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL DEFAULT '',
            title TEXT,
            summary TEXT,
            platform TEXT NOT NULL DEFAULT 'unknown',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE knowledge (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL DEFAULT '',
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

        CREATE TABLE preferences (
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

        CREATE TABLE user_identities (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            platform TEXT NOT NULL,
            platform_user_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(platform, platform_user_id)
        );

        INSERT INTO conversations
            (id, user_id, title, summary, platform, created_at, updated_at)
        VALUES
            ('conv-a', 'user-a', 'A', 'sum-a', 'telegram',
             '2026-04-20T00:00:00+00:00', '2026-04-20T01:00:00+00:00'),
            ('conv-b', 'user-b', 'B', 'sum-b', 'wechat',
             '2026-04-20T00:00:00+00:00', '2026-04-20T02:00:00+00:00');

        INSERT INTO knowledge
            (id, user_id, source_conversation_id, category, content, tags, priority,
             confidence, access_count, created_at, updated_at, expires_at)
        VALUES
            ('know-a', 'user-a', 'conv-a', 'fact', 'alpha', '[]', 'P1', 1.0, 0,
             '2026-04-20T00:00:00+00:00', '2026-04-20T00:30:00+00:00', NULL),
            ('know-b', 'user-b', 'conv-b', 'fact', 'beta', '[]', 'P1', 1.0, 0,
             '2026-04-20T00:00:00+00:00', '2026-04-20T00:40:00+00:00', NULL);

        INSERT INTO preferences
            (id, user_id, category, key, value, evidence, confidence, created_at, updated_at)
        VALUES
            ('pref-old', 'user-a', 'communication', 'reply_language', 'English', '["conv-a"]', 0.6,
             '2026-04-20T00:00:00+00:00', '2026-04-20T00:10:00+00:00'),
            ('pref-new', 'user-b', 'communication', 'reply_language', 'Chinese', '["conv-b"]', 0.9,
             '2026-04-20T00:00:00+00:00', '2026-04-20T00:20:00+00:00');

        INSERT INTO user_identities
            (id, user_id, platform, platform_user_id, created_at, updated_at)
        VALUES
            ('id-a', 'user-a', 'telegram', '123',
             '2026-04-20T00:00:00+00:00', '2026-04-20T00:00:00+00:00'),
            ('id-b', 'user-b', 'wechat', 'abc',
             '2026-04-20T00:00:00+00:00', '2026-04-20T00:00:00+00:00');
        """
    )
    conn.commit()
    conn.close()

    db = Database(StorageConfig(db_path=str(db_path)))
    await db.initialize()

    async with db.get_connection() as migrated:
        conversation_rows = await migrated.execute_fetchall(
            "SELECT user_id FROM conversations ORDER BY id"
        )
        knowledge_rows = await migrated.execute_fetchall(
            "SELECT user_id FROM knowledge ORDER BY id"
        )
        identity_rows = await migrated.execute_fetchall(
            "SELECT user_id FROM user_identities ORDER BY id"
        )
        preference_rows = await migrated.execute_fetchall(
            """
            SELECT user_id, category, key, value, confidence
            FROM preferences
            ORDER BY id
            """
        )

    await db.close()

    assert [row[0] for row in conversation_rows] == [SINGLE_USER_ID, SINGLE_USER_ID]
    assert [row[0] for row in knowledge_rows] == [SINGLE_USER_ID, SINGLE_USER_ID]
    assert [row[0] for row in identity_rows] == [SINGLE_USER_ID, SINGLE_USER_ID]
    assert [tuple(row) for row in preference_rows] == [
        (SINGLE_USER_ID, "communication", "reply_language", "Chinese", 0.9)
    ]
