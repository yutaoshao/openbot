from __future__ import annotations

from datetime import UTC, datetime

from src.agent.conversation.shared_timeline import SharedTimelineMemory
from src.core.config import StorageConfig
from src.core.user_scope import SINGLE_USER_ID
from src.infrastructure.database import Database
from src.infrastructure.model_gateway import ModelResponse
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


async def test_empty_summary_preserves_messages_and_boundary_on_failure(tmp_path) -> None:
    db = Database(StorageConfig(db_path=str(tmp_path / "memory.db")))
    await db.initialize()
    async with db.get_connection() as conn:
        await conn.execute(
            """INSERT INTO conversations
            (id, user_id, platform, created_at, updated_at)
            VALUES ('chat', ?, 'web', '2026-05-01', '2026-05-01')""",
            (SINGLE_USER_ID,),
        )
        await conn.commit()
    repo = MessageRepo(db)
    timeline = SharedTimelineMemory(token_budget=1, recent_budget=100)
    await timeline.ensure_loaded(repo)
    for index, role in enumerate(("user", "assistant", "user", "assistant")):
        timestamp = datetime(2026, 5, 1, 8, index, tzinfo=UTC)
        await repo.add(
            id=f"m{index}",
            conversation_id="chat",
            role=role,
            content=f"text{index}",
            timestamp=timestamp,
        )
        timeline.add(dict(id=f"m{index}", role=role, content=f"text{index}", timestamp=timestamp))

    class EmptyGateway:
        async def chat(self, messages):
            return ModelResponse(text="")

    before = timeline.get_messages()
    summary = await timeline.compress(EmptyGateway())
    assert summary == ""
    assert timeline.get_messages() == before
    saved = await repo.get_working_summary()
    assert saved is None
    await db.close()


async def test_recent_history_keeps_whole_turn_and_persisted_summary(tmp_path) -> None:
    db = Database(StorageConfig(db_path=str(tmp_path / "memory.db")))
    await db.initialize()
    async with db.get_connection() as conn:
        await conn.execute(
            """INSERT INTO conversations
            (id, user_id, platform, created_at, updated_at)
            VALUES ('chat', ?, 'web', '2026-05-01', '2026-05-01')""",
            (SINGLE_USER_ID,),
        )
        await conn.commit()
    repo = MessageRepo(db)
    timeline = SharedTimelineMemory(token_budget=1, recent_budget=120)
    await timeline.ensure_loaded(repo)
    for index, (role, content) in enumerate(
        [
            ("user", "old question"),
            ("assistant", "old answer"),
            ("user", "recent question"),
            ("assistant", "recent answer"),
        ]
    ):
        timestamp = datetime(2026, 5, 1, 8, index, tzinfo=UTC)
        await repo.add(
            id=f"m{index}", conversation_id="chat", role=role, content=content, timestamp=timestamp
        )
        timeline.add(dict(id=f"m{index}", role=role, content=content, timestamp=timestamp))
    assert [
        item["role"] for item in await repo.get_recent_global(60, ("web",), user_id=SINGLE_USER_ID)
    ] == ["user", "assistant"]

    class Gateway:
        async def chat(self, messages):
            return ModelResponse(text="old question was answered")

    startup = SharedTimelineMemory(token_budget=1, recent_budget=120)
    await startup.ensure_loaded(repo, Gateway())
    assert (await repo.get_working_summary())["boundary_id"] == "m1"
    assert "recent question" in startup.get_messages()[1]["content"]

    await timeline.compress(Gateway())
    saved = await repo.get_working_summary()
    assert saved and saved["boundary_id"] == "m1"
    restarted = SharedTimelineMemory(token_budget=1, recent_budget=120)
    await restarted.ensure_loaded(repo)
    rendered = restarted.get_messages()
    assert rendered[0]["role"] == "system" and "old question" in rendered[0]["content"]
    assert [item["role"] for item in rendered[1:]] == ["user", "assistant"]
    assert "recent question" in rendered[1]["content"]
    await db.close()


async def test_first_startup_compacts_long_history_in_bounded_segments(tmp_path) -> None:
    db = Database(StorageConfig(db_path=str(tmp_path / "memory.db")))
    await db.initialize()
    async with db.get_connection() as conn:
        await conn.execute(
            """INSERT INTO conversations
            (id, user_id, platform, created_at, updated_at)
            VALUES ('chat', ?, 'web', '2026-05-01', '2026-05-01')""",
            (SINGLE_USER_ID,),
        )
        await conn.commit()
    repo = MessageRepo(db)
    for index in range(128):
        await repo.add(
            id=f"m{index}",
            conversation_id="chat",
            role="user" if index % 2 == 0 else "assistant",
            content=f"entry {index} " + "details " * 30,
            timestamp=datetime(2026, 5, 1, 8, index // 60, index % 60, tzinfo=UTC),
        )

    class Gateway:
        calls = 0

        async def chat(self, messages):
            self.calls += 1
            assert len(messages[0]["content"]) < 20_000
            return ModelResponse(text=f"summary part {self.calls}")

    gateway = Gateway()
    timeline = SharedTimelineMemory(token_budget=500, recent_budget=200)
    await timeline.ensure_loaded(repo, gateway)
    saved = await repo.get_working_summary()
    assert gateway.calls >= 2
    assert saved and saved["version"] >= 2
    assert timeline.get_messages()[1]["role"] == "user"
    assert timeline.get_messages()[-1]["role"] == "assistant"
    await db.close()
