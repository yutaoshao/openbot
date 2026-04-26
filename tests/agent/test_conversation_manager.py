from __future__ import annotations

from types import SimpleNamespace

from src.agent.conversation import _WORKING_MEMORY_IDLE_TTL_SECONDS, ConversationManager
from src.agent.conversation import prompt_builder as prompt_builder_module
from src.core.user_scope import SINGLE_USER_ID


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

    async def get_recent_global(
        self,
        token_budget: int,
        include_platforms: tuple[str, ...],
        *,
        user_id: str,
    ) -> list[dict[str, str]]:
        return []

    async def add(self, **kwargs: object) -> None:
        conversation_id = str(kwargs["conversation_id"])
        self._messages.setdefault(conversation_id, []).append(
            {
                "role": str(kwargs["role"]),
                "content": str(kwargs["content"]),
            }
        )

    async def get_by_conversation(self, conversation_id: str) -> list[dict[str, str]]:
        return list(self._messages.get(conversation_id, []))


class _NoopMemoryTier:
    def __init__(self) -> None:
        self.ended: list[tuple[str, str]] = []
        self.extracted: list[tuple[str, str, list[dict[str, str]]]] = []
        self.observed: list[tuple[str, str, list[dict[str, str]]]] = []

    async def on_conversation_end(self, conversation_id: str, user_id: str) -> None:
        self.ended.append((conversation_id, user_id))

    async def extract_knowledge(
        self,
        llm_messages: list[dict[str, str]],
        conversation_id: str,
        user_id: str,
    ) -> None:
        self.extracted.append((conversation_id, user_id, llm_messages))
        return None

    async def observe(
        self,
        llm_messages: list[dict[str, str]],
        conversation_id: str,
        user_id: str,
    ) -> None:
        self.observed.append((conversation_id, user_id, llm_messages))
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


class _PromptContextTier(_NoopMemoryTier):
    async def get_system_prompt_context(self, user_id: str) -> str:
        return "prefs"

    async def recall(
        self,
        user_input: str,
        user_id: str,
        limit: int = 3,
    ) -> list[dict[str, str]]:
        return [{"category": "fact", "content": "shared context"}]


class _FailingPromptTier(_NoopMemoryTier):
    async def get_system_prompt_context(self, user_id: str) -> str:
        raise RuntimeError("preference lookup failed")

    async def recall(
        self,
        user_input: str,
        user_id: str,
        limit: int = 3,
    ) -> list[dict[str, str]]:
        raise RuntimeError("recall failed")


class _WarningRecorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def warning(self, event: str, **fields: object) -> None:
        self.events.append((event, fields))


async def test_get_or_create_does_not_prune_idle_working_memories_inline() -> None:
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
    manager._task_store._last_active["stale-conv"] -= _WORKING_MEMORY_IDLE_TTL_SECONDS + 1  # noqa: SLF001

    await manager.get_or_create_conversation("fresh-conv", "web", "user-fresh")

    assert manager.get_task_state("stale-conv") is not None
    assert manager.get_task_state("fresh-conv") is not None
    assert episodic.ended == []


async def test_prune_idle_conversations_archives_stale_working_memories() -> None:
    episodic = _NoopMemoryTier()
    semantic = _NoopMemoryTier()
    procedural = _NoopMemoryTier()
    storage = SimpleNamespace(
        conversations=_FakeConversationRepo(),
        messages=_FakeMessageRepo(),
    )
    manager = ConversationManager(
        storage=storage,
        model_gateway=object(),
        semantic_memory=semantic,
        episodic_memory=episodic,
        procedural_memory=procedural,
    )

    await manager.get_or_create_conversation("stale-conv", "web", "user-stale")
    await manager.add_user_message("stale-conv", "remember this")
    manager._task_store._last_active["stale-conv"] -= _WORKING_MEMORY_IDLE_TTL_SECONDS + 1  # noqa: SLF001

    await manager.get_or_create_conversation("fresh-conv", "web", "user-fresh")
    await manager.add_user_message("fresh-conv", "still active")

    await manager.prune_idle_conversations()

    assert manager.get_task_state("stale-conv") is None
    assert manager.get_task_state("fresh-conv") is not None
    assert episodic.ended == [("stale-conv", SINGLE_USER_ID)]
    assert [item[:2] for item in semantic.extracted] == [("stale-conv", SINGLE_USER_ID)]
    assert [item[:2] for item in procedural.observed] == [("stale-conv", SINGLE_USER_ID)]


async def test_build_messages_uses_shared_cross_platform_timeline() -> None:
    storage = SimpleNamespace(
        conversations=_FakeConversationRepo(),
        messages=_FakeMessageRepo(),
    )
    manager = ConversationManager(
        storage=storage,
        model_gateway=object(),
        semantic_memory=_PromptContextTier(),
        episodic_memory=_PromptContextTier(),
        procedural_memory=_PromptContextTier(),
    )

    await manager.get_or_create_conversation("telegram-conv", "telegram", SINGLE_USER_ID)
    await manager.add_user_message("telegram-conv", "来自 Telegram 的消息")
    await manager.get_or_create_conversation("wechat-conv", "wechat", SINGLE_USER_ID)
    await manager.add_user_message("wechat-conv", "来自微信的消息")

    messages = await manager.build_messages(
        "wechat-conv",
        "system base",
        "现在继续聊",
        SINGLE_USER_ID,
    )

    rendered = "\n".join(str(item.get("content", "")) for item in messages)
    assert "来自 Telegram 的消息" in rendered
    assert "来自微信的消息" in rendered
    assert "shared context" in rendered


async def test_build_messages_logs_memory_context_failures(monkeypatch) -> None:
    recorder = _WarningRecorder()
    monkeypatch.setattr(prompt_builder_module, "logger", recorder, raising=False)
    failing = _FailingPromptTier()
    storage = SimpleNamespace(
        conversations=_FakeConversationRepo(),
        messages=_FakeMessageRepo(),
    )
    manager = ConversationManager(
        storage=storage,
        model_gateway=object(),
        semantic_memory=failing,
        episodic_memory=failing,
        procedural_memory=failing,
    )

    await manager.get_or_create_conversation("conv-1", "web", SINGLE_USER_ID)
    await manager.add_user_message("conv-1", "hello")
    messages = await manager.build_messages(
        "conv-1",
        "system base",
        "hello",
        SINGLE_USER_ID,
    )

    assert messages[0]["content"] == "system base"
    assert [event for event, _fields in recorder.events] == [
        "conversation.prompt_context_failed",
        "conversation.prompt_context_failed",
        "conversation.prompt_context_failed",
    ]
    assert [fields["tier"] for _event, fields in recorder.events] == [
        "procedural",
        "semantic",
        "episodic",
    ]
