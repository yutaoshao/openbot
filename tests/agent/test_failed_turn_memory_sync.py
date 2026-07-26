from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from src.agent.conversation import ConversationManager
from src.agent.turn_outcome import FailedTurn
from src.core.user_scope import SINGLE_USER_ID
from src.memory.message_format import strip_internal_timestamp_prefixes

FIRST_TS = datetime(2026, 7, 19, 10, 0, tzinfo=UTC)
SECOND_TS = datetime(2026, 7, 19, 10, 1, tzinfo=UTC)


class _ConversationRepo:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, str]] = {}

    async def get(self, conversation_id: str) -> dict[str, str] | None:
        return self.records.get(conversation_id)

    async def create(self, *, id: str, platform: str, user_id: str = "") -> None:
        self.records[id] = {"id": id, "platform": platform, "user_id": user_id}

    async def update(self, conversation_id: str, **fields: object) -> None:
        self.records.setdefault(conversation_id, {"id": conversation_id}).update(fields)


class _MessageRepo:
    def __init__(self) -> None:
        self.records: dict[str, list[dict[str, Any]]] = {}

    async def get_recent_global(self, *_args: object, **_kwargs: object) -> list[dict[str, Any]]:
        return []

    async def add(self, **fields: object) -> None:
        conversation_id = str(fields["conversation_id"])
        stored_message = {
            "role": str(fields["role"]),
            "content": str(fields["content"]),
            "timestamp": fields["timestamp"],
            "metadata": fields.get("metadata"),
        }
        self.records.setdefault(conversation_id, []).append(stored_message)

    async def get_by_conversation(self, conversation_id: str) -> list[dict[str, Any]]:
        return list(self.records.get(conversation_id, []))


class _CaptureMemoryTier:
    def __init__(self) -> None:
        self.extractions: list[list[dict[str, Any]]] = []
        self.observations: list[list[dict[str, Any]]] = []

    async def extract_knowledge(
        self,
        messages: list[dict[str, Any]],
        _conversation_id: str,
        _user_id: str,
    ) -> None:
        self.extractions.append(messages)

    async def observe(
        self,
        messages: list[dict[str, Any]],
        _conversation_id: str,
        _user_id: str,
    ) -> None:
        self.observations.append(messages)

    async def on_conversation_end(self, *_args: object) -> None:
        return None

    async def get_system_prompt_context(self, _user_id: str) -> str:
        return ""

    async def recall(self, *_args: object, **_kwargs: object) -> list[dict[str, str]]:
        return []


def _conversation_memory(
    storage: SimpleNamespace,
    semantic_tier: _CaptureMemoryTier,
    procedural_tier: _CaptureMemoryTier,
) -> ConversationManager:
    return ConversationManager(
        storage=storage,
        model_gateway=object(),
        semantic_memory=semantic_tier,
        episodic_memory=_CaptureMemoryTier(),
        procedural_memory=procedural_tier,
    )


def _stored_contents(messages: list[dict[str, Any]]) -> list[str]:
    return [strip_internal_timestamp_prefixes(str(message["content"])) for message in messages]


async def test_restart_sync_excludes_persisted_failed_pair() -> None:
    storage = SimpleNamespace(
        conversations=_ConversationRepo(),
        messages=_MessageRepo(),
    )
    initial_memory = _conversation_memory(
        storage,
        _CaptureMemoryTier(),
        _CaptureMemoryTier(),
    )
    await initial_memory.get_or_create_conversation("conv-1", "web", SINGLE_USER_ID)
    await initial_memory.add_user_message("conv-1", "错误路径纠正", timestamp=FIRST_TS)
    failed_turn = FailedTurn("本轮未完成", reason="stop_verification")
    await initial_memory.add_failed_assistant_message(
        "conv-1",
        failed_turn,
        timestamp=FIRST_TS,
    )

    persisted = await storage.messages.get_by_conversation("conv-1")
    assert persisted[1]["content"] == "本轮未完成"
    assert persisted[1]["metadata"] == failed_turn.message_metadata()
    task_state = initial_memory.get_task_state("conv-1")
    assert task_state is not None
    assert task_state.status == "active"
    assert task_state.completed_items == []
    assert task_state.open_items == ["错误路径纠正"]

    semantic_tier = _CaptureMemoryTier()
    procedural_tier = _CaptureMemoryTier()
    restarted_memory = _conversation_memory(storage, semantic_tier, procedural_tier)
    await restarted_memory.get_or_create_conversation("conv-1", "web", SINGLE_USER_ID)
    await restarted_memory.add_user_message("conv-1", "正确的新问题", timestamp=SECOND_TS)
    await restarted_memory.add_assistant_message(
        "conv-1",
        "正确的新回答",
        timestamp=SECOND_TS,
    )
    await restarted_memory.sync_memory_after_turn("conv-1")

    assert _stored_contents(semantic_tier.extractions[0]) == [
        "正确的新问题",
        "正确的新回答",
    ]
    assert procedural_tier.observations == semantic_tier.extractions


async def test_sync_does_not_advance_across_concurrent_open_turn() -> None:
    storage = SimpleNamespace(
        conversations=_ConversationRepo(),
        messages=_MessageRepo(),
    )
    semantic_tier = _CaptureMemoryTier()
    procedural_tier = _CaptureMemoryTier()
    conversation_memory = _conversation_memory(storage, semantic_tier, procedural_tier)
    await conversation_memory.get_or_create_conversation("conv-1", "web", SINGLE_USER_ID)
    await conversation_memory.add_user_message("conv-1", "第一问", timestamp=FIRST_TS)
    await conversation_memory.add_assistant_message("conv-1", "第一答", timestamp=FIRST_TS)
    await conversation_memory.add_user_message("conv-1", "第二问", timestamp=SECOND_TS)

    await conversation_memory.sync_memory_after_turn("conv-1")
    assert _stored_contents(semantic_tier.extractions[0]) == ["第一问", "第一答"]

    await conversation_memory.add_assistant_message("conv-1", "第二答", timestamp=SECOND_TS)
    await conversation_memory.sync_memory_after_turn("conv-1")
    assert _stored_contents(semantic_tier.extractions[1]) == ["第二问", "第二答"]
