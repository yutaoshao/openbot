from __future__ import annotations

from datetime import UTC, datetime

from src.core.config import StorageConfig
from src.infrastructure.database import Database
from src.infrastructure.storage.messages_repo import MessageRepo


async def test_add_persists_message_timestamp_separately_from_created_at(tmp_path) -> None:
    db = Database(StorageConfig(db_path=str(tmp_path / "openbot.db")))
    await db.initialize()

    async with db.get_connection() as conn:
        await conn.execute(
            """
            INSERT INTO conversations
                (id, user_id, platform, title, created_at, updated_at)
            VALUES
                ('conv-1', 'openbot-local-user', 'web', NULL,
                 '2026-05-01T00:00:00+00:00',
                 '2026-05-01T00:00:00+00:00')
            """
        )
        await conn.commit()

    repo = MessageRepo(db)
    timestamp = datetime(2026, 5, 1, 8, 30, tzinfo=UTC)

    await repo.add(
        id="msg-1",
        conversation_id="conv-1",
        role="user",
        content="hello",
        timestamp=timestamp,
    )

    rows = await repo.get_by_conversation("conv-1")
    await db.close()

    assert rows[0]["timestamp"] == "2026-05-01T08:30:00+00:00"
    assert rows[0]["created_at"] != rows[0]["timestamp"]
    assert rows[0]["content"] == "hello"
