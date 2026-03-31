from __future__ import annotations

from types import SimpleNamespace

from src.agent.conversation import ConversationManager, _WORKING_MEMORY_IDLE_TTL_SECONDS


class _FakeConversationRepo:
    def __init__(self) -> None:
        self._items: dict[str, dict[str, str]] = {}

    async def get(self, conversation_id: str) -> dict[str, str] | None:
        return self._items.get(conversation_id)

    async def create(self, *, id: str, platform: str) -> None:
        self._items[id] = {"id": id, "platform": platform}


class _FakeMessageRepo:
    async def get_recent(self, conversation_id: str, token_budget: int) -> list[dict[str, str]]:
        return []

    async def add(self, **kwargs: object) -> None:
        return None

    async def get_by_conversation(self, conversation_id: str) -> list[dict[str, str]]:
        return []


class _NoopMemoryTier:
    async def on_conversation_end(self, conversation_id: str) -> None:
        return None

    async def extract_knowledge(self, llm_messages: list[dict[str, str]], conversation_id: str) -> None:
        return None

    async def observe(self, llm_messages: list[dict[str, str]], conversation_id: str) -> None:
        return None

    async def get_system_prompt_context(self) -> str:
        return ""

    async def recall(self, user_input: str, limit: int = 3) -> list[dict[str, str]]:
        return []

    async def add_knowledge(self, **kwargs: object) -> None:
        return None


async def test_get_or_create_prunes_idle_working_memories() -> None:
    storage = SimpleNamespace(
        conversations=_FakeConversationRepo(),
        messages=_FakeMessageRepo(),
    )
    manager = ConversationManager(
        storage=storage,
        model_gateway=object(),
        semantic_memory=_NoopMemoryTier(),
        episodic_memory=_NoopMemoryTier(),
        procedural_memory=_NoopMemoryTier(),
    )

    await manager.get_or_create_conversation("stale-conv", "web")
    manager._working_last_active["stale-conv"] -= _WORKING_MEMORY_IDLE_TTL_SECONDS + 1

    await manager.get_or_create_conversation("fresh-conv", "web")

    assert "stale-conv" not in manager._working
    assert "fresh-conv" in manager._working
