from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from src.agent.agent import Agent
from src.agent.conversation import ConversationManager
from src.core.config import AgentConfig
from src.core.user_scope import SINGLE_USER_ID
from src.infrastructure.model_gateway import StreamChunk, Usage

FIRST_TS = datetime(2026, 5, 15, 1, 0, tzinfo=UTC)
SECOND_TS = datetime(2026, 5, 15, 3, 0, tzinfo=UTC)


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
    def __init__(self, conversations: _FakeConversationRepo) -> None:
        self._conversations = conversations
        self._messages: dict[str, list[dict[str, Any]]] = {}

    async def get_recent_global(
        self,
        token_budget: int,
        include_platforms: tuple[str, ...],
        *,
        user_id: str,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for conversation_id, messages in self._messages.items():
            conversation = await self._conversations.get(conversation_id)
            if conversation is None or conversation.get("platform") not in include_platforms:
                continue
            if conversation.get("user_id") != user_id:
                continue
            items.extend(messages)
        return sorted(items, key=lambda item: str(item["timestamp"]))

    async def add(self, **kwargs: object) -> None:
        conversation_id = str(kwargs["conversation_id"])
        self._messages.setdefault(conversation_id, []).append(
            {
                "role": str(kwargs["role"]),
                "content": str(kwargs["content"]),
                "timestamp": kwargs["timestamp"],
            }
        )

    async def get_by_conversation(self, conversation_id: str) -> list[dict[str, Any]]:
        return list(self._messages.get(conversation_id, []))


class _NoopMemoryTier:
    async def on_conversation_end(self, conversation_id: str, user_id: str) -> None:
        return None

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


class _CapturingGateway:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, Any]]] = []

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **_: Any,
    ):
        self.calls.append(messages)
        yield StreamChunk(type="text", text="scheduled result")
        yield StreamChunk(
            type="done",
            usage=Usage(tokens_in=12, tokens_out=8),
            model="fake-model",
        )


class _FakeEventBus:
    async def publish(self, event_name: str, data: dict[str, Any]) -> None:
        return None


def _storage() -> SimpleNamespace:
    conversations = _FakeConversationRepo()
    return SimpleNamespace(
        conversations=conversations,
        messages=_FakeMessageRepo(conversations),
    )


def _manager(storage: SimpleNamespace) -> ConversationManager:
    memory = _NoopMemoryTier()
    return ConversationManager(
        storage=storage,
        model_gateway=object(),
        semantic_memory=memory,
        episodic_memory=memory,
        procedural_memory=memory,
    )


async def test_scheduler_current_input_is_last_message_after_shared_history() -> None:
    storage = _storage()
    manager = _manager(storage)
    await manager.get_or_create_conversation("web-conv", "web", SINGLE_USER_ID)
    await manager.add_user_message("web-conv", "刚刚在解释 grep_tool 代码", timestamp=FIRST_TS)
    await manager.get_or_create_conversation("schedule_sched-1", "scheduler", SINGLE_USER_ID)
    await manager.add_user_message(
        "schedule_sched-1",
        "写每日研究日报，聚焦 OpenBot 调度问题",
        timestamp=SECOND_TS,
    )

    messages = await manager.build_messages(
        "schedule_sched-1",
        "system base",
        "写每日研究日报，聚焦 OpenBot 调度问题",
        SINGLE_USER_ID,
    )

    rendered = "\n".join(str(item.get("content", "")) for item in messages)
    assert "刚刚在解释 grep_tool 代码" in rendered
    assert messages[-1]["role"] == "user"
    assert "写每日研究日报" in str(messages[-1]["content"])


async def test_chat_current_input_is_not_duplicated_when_timeline_contains_it() -> None:
    storage = _storage()
    manager = _manager(storage)
    await manager.get_or_create_conversation("web-conv", "web", SINGLE_USER_ID)
    await manager.add_user_message("web-conv", "继续解释 grep_tool", timestamp=FIRST_TS)

    messages = await manager.build_messages(
        "web-conv",
        "system base",
        "继续解释 grep_tool",
        SINGLE_USER_ID,
    )

    contents = [str(item.get("content", "")) for item in messages if item.get("role") == "user"]
    assert sum("继续解释 grep_tool" in content for content in contents) == 1
    assert messages[-1]["role"] == "user"
    assert "继续解释 grep_tool" in str(messages[-1]["content"])


async def test_scheduler_runtime_sends_current_prompt_after_chat_history() -> None:
    storage = _storage()
    manager = _manager(storage)
    await manager.get_or_create_conversation("web-conv", "web", SINGLE_USER_ID)
    await manager.add_user_message("web-conv", "最近在解释 grep_tool", timestamp=FIRST_TS)
    gateway = _CapturingGateway()
    agent = Agent(
        model_gateway=gateway,
        event_bus=_FakeEventBus(),
        config=AgentConfig(max_iterations=3),
        tool_registry=None,
        conversation_manager=manager,
    )

    result = await agent.run(
        "写每日研究日报，聚焦 OpenBot 调度问题",
        conversation_id="schedule_sched-1",
        platform="scheduler",
        message_timestamp=SECOND_TS,
    )

    assert result.content == "scheduled result"
    messages = gateway.calls[0]
    rendered = "\n".join(str(item.get("content", "")) for item in messages)
    assert "最近在解释 grep_tool" in rendered
    assert messages[-1]["role"] == "user"
    assert "写每日研究日报" in str(messages[-1]["content"])
    background_task = agent._memory_finalize_tasks.get("schedule_sched-1")
    if background_task is not None:
        await asyncio.wait_for(background_task, timeout=0.5)
