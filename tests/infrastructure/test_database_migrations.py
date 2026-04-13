from __future__ import annotations

import sqlite3

from src.core.config import StorageConfig
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
