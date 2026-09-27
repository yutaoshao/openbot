from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from src.agent.conversation.manager import ConversationManager
from src.core.config import StorageConfig
from src.infrastructure.database import Database
from src.infrastructure.storage import Storage

if TYPE_CHECKING:
    from pathlib import Path


class _Profile:
    def __init__(self, *, fail_on: str = "") -> None:
        self.fail_on = fail_on
        self.sources: list[str] = []

    async def extract(self, gateway, user_text: str, *, stated_at: str, context_messages=None):
        if user_text == self.fail_on:
            raise ValueError("extraction unavailable")
        return [{"fact": user_text}]

    async def apply_claims(self, claims, *, source: str, stated_at: str) -> int:
        self.sources.append(source)
        return 1


class _Semantic:
    def __init__(self):
        self.sources = []

    async def extract_items(self, messages):
        return [{"content": messages[0]["content"]}]

    async def store_extracted_knowledge(self, items, conversation_id, user_id, *, source):
        self.sources.append(source)
        return items


async def test_cursor_survives_failure_and_restart(tmp_path: Path) -> None:
    db = Database(StorageConfig(db_path=str(tmp_path / "memory.db")))
    await db.initialize()
    try:
        storage = Storage(db)
        await storage.conversations.create(id="chat", platform="web", user_id="local-single-user")
        base = datetime(2026, 9, 27, tzinfo=UTC)
        for index, (role, content) in enumerate(
            [
                ("user", "first"),
                ("assistant", "reply"),
                ("user", "second"),
                ("assistant", "reply"),
            ]
        ):
            await storage.messages.add(
                id=f"m{index}",
                conversation_id="chat",
                role=role,
                content=content,
                timestamp=base + timedelta(seconds=index),
            )
        first = _Profile(fail_on="second")
        semantic = _Semantic()
        kwargs = dict(
            storage=storage,
            model_gateway=SimpleNamespace(),
            semantic_memory=semantic,
            episodic_memory=SimpleNamespace(),
            procedural_memory=SimpleNamespace(),
        )
        manager = ConversationManager(**kwargs, personal_profile=first)
        with pytest.raises(ValueError, match="unavailable"):
            await manager.sync_memory_after_turn("chat")
        assert first.sources == ["message:m0"]
        assert await storage.personal_progress.get("chat") == 2

        restarted = _Profile()
        manager = ConversationManager(**kwargs, personal_profile=restarted)
        await manager.sync_memory_after_turn("chat")
        assert restarted.sources == ["message:m2"]
        assert await storage.personal_progress.get("chat") == 4
        assert semantic.sources == ["message:m0", "message:m2"]
    finally:
        await db.close()
