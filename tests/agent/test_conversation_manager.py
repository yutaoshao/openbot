from __future__ import annotations

from types import SimpleNamespace

from src.agent.conversation import _WORKING_MEMORY_IDLE_TTL_SECONDS, ConversationManager


class _FakeConversationRepo:
    def __init__(self) -> None:
        self._items: dict[str, dict[str, str]] = {}

    async def get(self, conversation_id: str) -> dict[str, str] | None:
        return self._items.get(conversation_id)

    async def create(self, *, id: str, platform: str, user_id: str = "") -> None:
        self._items[id] = {"id": id, "platform": platform, "user_id": user_id}

    async def update(self, conversation_id: str, **fields: object) -> None:
        self._items.setdefault(conversation_id, {"id": conversation_id}).update(fields)


class _FakeMessageRepo:
    def __init__(self) -> None:
        self._messages: dict[str, list[dict[str, str]]] = {}

    async def get_recent(self, conversation_id: str, token_budget: int) -> list[dict[str, str]]:
        return []

    async def add(self, **kwargs: object) -> None:
        conversation_id = str(kwargs["conversation_id"])
        self._messages.setdefault(conversation_id, []).append({
            "role": str(kwargs["role"]),
            "content": str(kwargs["content"]),
        })

    async def get_by_conversation(self, conversation_id: str) -> list[dict[str, str]]:
        return list(self._messages.get(conversation_id, []))


class _NoopMemoryTier:
    def __init__(self) -> None:
        self.ended: list[tuple[str, str]] = []

    async def on_conversation_end(self, conversation_id: str, user_id: str) -> None:
        self.ended.append((conversation_id, user_id))

    async def extract_knowledge(
        self,
        llm_messages: list[dict[str, str]],
        conversation_id: str,
        user_id: str,
    ) -> None:
        return None

    async def observe(
        self,
        llm_messages: list[dict[str, str]],
        conversation_id: str,
        user_id: str,
    ) -> None:
        return None

    async def get_system_prompt_context(self, user_id: str) -> str:
        return ""

    async def recall(
        self,
        user_input: str,
        user_id: str,
        limit: int = 3,
    ) -> list[dict[str, str]]:
        return []

    async def add_knowledge(self, **kwargs: object) -> None:
        return None


async def test_get_or_create_prunes_idle_working_memories() -> None:
    episodic = _NoopMemoryTier()
    storage = SimpleNamespace(
        conversations=_FakeConversationRepo(),
        messages=_FakeMessageRepo(),
    )
    manager = ConversationManager(
        storage=storage,
        model_gateway=object(),
        semantic_memory=_NoopMemoryTier(),
        episodic_memory=episodic,
        procedural_memory=_NoopMemoryTier(),
    )

    await manager.get_or_create_conversation("stale-conv", "web", "user-stale")
    await manager.add_user_message("stale-conv", "remember this")
    manager._working_last_active["stale-conv"] -= _WORKING_MEMORY_IDLE_TTL_SECONDS + 1

    await manager.get_or_create_conversation("fresh-conv", "web", "user-fresh")

    assert "stale-conv" not in manager._working
    assert "fresh-conv" in manager._working
    assert episodic.ended == [("stale-conv", "user-stale")]
