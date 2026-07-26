from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from src.agent.agent import Agent
from src.agent.runtime.finalize import verify_and_publish_final_response
from src.agent.state import TaskState
from src.agent.turn_outcome import CompletedTurn, FailedTurn
from src.core.config import AgentConfig
from src.core.trace import current_trace, trace_scope
from src.infrastructure.model_gateway import StreamChunk, Usage


class FakeEventBus:
    async def publish(self, event_name: str, data: dict[str, Any]) -> None:
        return None


class FakeStreamingGateway:
    def __init__(self) -> None:
        self.trace_ids: list[str] = []

    async def model_round_chunks(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **_: Any,
    ):
        trace = current_trace()
        self.trace_ids.append(trace.trace_id if trace else "")
        yield StreamChunk(type="text", text="Hello")
        yield StreamChunk(type="text", text=" streaming")
        yield StreamChunk(
            type="done",
            usage=Usage(tokens_in=12, tokens_out=8),
            model="fake-model",
        )


class VagueReplyGateway:
    async def model_round_chunks(self, *_args: object, **_kwargs: object):
        yield StreamChunk(type="text", text="done")
        yield StreamChunk(type="done", usage=Usage(tokens_in=3, tokens_out=1))


class FakeConversationManager:
    def __init__(self) -> None:
        self.compress_started = asyncio.Event()
        self.release_background = asyncio.Event()
        self.compress_calls: list[str] = []
        self.sync_calls: list[str] = []
        self.sync_trace_ids: list[str] = []
        self.sync_interaction_ids: list[str] = []
        self.sync_triggers: list[str] = []
        self.user_timestamps: list[datetime] = []
        self.assistant_timestamps: list[datetime] = []
        self.failed_turns: list[FailedTurn] = []
        self.task_state: TaskState | None = None

    async def get_or_create_conversation(
        self,
        conversation_id: str,
        platform: str,
        user_id: str,
        token_budget: int,
    ) -> None:
        return None

    async def add_user_message(
        self,
        conversation_id: str,
        content: str,
        *,
        timestamp: datetime,
        archive_metadata: Any = None,
    ) -> None:
        self.user_timestamps.append(timestamp)
        return None

    async def build_messages(
        self,
        conversation_id: str,
        system_prompt: str,
        user_input: str,
        user_id: str,
        message_timestamp: datetime | None = None,
    ) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ]

    def get_task_state(self, conversation_id: str) -> TaskState | None:
        return self.task_state

    async def add_assistant_message(self, conversation_id: str, **kwargs: Any) -> None:
        self.assistant_timestamps.append(kwargs["timestamp"])
        return None

    async def add_failed_assistant_message(
        self,
        conversation_id: str,
        failed_turn: FailedTurn,
        **kwargs: Any,
    ) -> None:
        self.assistant_timestamps.append(kwargs["timestamp"])
        self.failed_turns.append(failed_turn)

    async def maybe_compress(self, conversation_id: str) -> None:
        self.compress_started.set()
        await self.release_background.wait()
        self.compress_calls.append(conversation_id)

    async def sync_memory_after_turn(self, conversation_id: str) -> None:
        trace = current_trace()
        self.sync_calls.append(conversation_id)
        self.sync_trace_ids.append(trace.trace_id if trace else "")
        self.sync_interaction_ids.append(trace.interaction_id if trace else "")
        self.sync_triggers.append(trace.extra.get("trigger", "") if trace else "")

    async def end_conversation(
        self,
        conversation_id: str,
        *,
        clear_working_memory: bool = True,
    ) -> None:
        raise AssertionError("end_conversation should not be used for post-reply sync")


async def test_run_returns_before_background_memory_finalize_completes() -> None:
    conversation_manager = FakeConversationManager()
    agent = Agent(
        model_gateway=FakeStreamingGateway(),
        event_bus=FakeEventBus(),
        config=AgentConfig(max_iterations=3),
        tool_registry=None,
        conversation_manager=conversation_manager,
    )

    result = await asyncio.wait_for(
        agent.run("hello world", conversation_id="conv-1", platform="telegram"),
        timeout=0.5,
    )

    assert result.content == "Hello streaming"
    assert conversation_manager.user_timestamps
    assert conversation_manager.assistant_timestamps

    await asyncio.sleep(0)
    assert conversation_manager.compress_started.is_set()
    assert conversation_manager.compress_calls == []
    assert conversation_manager.sync_calls == []

    background_task = agent._memory_finalize_tasks["conv-1"]
    conversation_manager.release_background.set()
    await asyncio.wait_for(background_task, timeout=0.5)

    assert conversation_manager.compress_calls == ["conv-1"]
    assert conversation_manager.sync_calls == ["conv-1"]


async def test_run_passes_explicit_message_timestamp_to_conversation_manager() -> None:
    conversation_manager = FakeConversationManager()
    agent = Agent(
        model_gateway=FakeStreamingGateway(),
        event_bus=FakeEventBus(),
        config=AgentConfig(max_iterations=3),
        tool_registry=None,
        conversation_manager=conversation_manager,
    )
    timestamp = datetime(2026, 5, 1, 8, 30, tzinfo=UTC)

    result = await agent.run(
        "hello world",
        conversation_id="conv-1",
        platform="telegram",
        message_timestamp=timestamp,
    )

    assert result.content == "Hello streaming"
    assert conversation_manager.user_timestamps == [timestamp]

    background_task = agent._memory_finalize_tasks["conv-1"]
    conversation_manager.release_background.set()
    await asyncio.wait_for(background_task, timeout=0.5)


async def test_run_reuses_active_trace_context() -> None:
    gateway = FakeStreamingGateway()
    agent = Agent(
        model_gateway=gateway,
        event_bus=FakeEventBus(),
        config=AgentConfig(max_iterations=3),
        tool_registry=None,
        conversation_manager=None,
    )

    with trace_scope(interaction_id="conv-1", platform="wechat") as trace:
        result = await agent.run("hello world", conversation_id="conv-1", platform="wechat")

    assert result.content == "Hello streaming"
    assert gateway.trace_ids == [trace.trace_id]


async def test_background_memory_sync_uses_child_trace_context() -> None:
    conversation_manager = FakeConversationManager()
    agent = Agent(
        model_gateway=FakeStreamingGateway(),
        event_bus=FakeEventBus(),
        config=AgentConfig(max_iterations=3),
        tool_registry=None,
        conversation_manager=conversation_manager,
    )

    with trace_scope(interaction_id="conv-1", platform="wechat") as trace:
        result = await agent.run("hello world", conversation_id="conv-1", platform="wechat")

    assert result.content == "Hello streaming"
    background_task = agent._memory_finalize_tasks["conv-1"]
    conversation_manager.release_background.set()
    await asyncio.wait_for(background_task, timeout=0.5)

    assert len(conversation_manager.sync_trace_ids) == 1
    assert conversation_manager.sync_trace_ids[0] != trace.trace_id
    assert conversation_manager.sync_interaction_ids == ["conv-1"]
    assert conversation_manager.sync_triggers == ["post_reply_sync"]


async def test_failed_turn_is_persisted_without_background_memory_sync() -> None:
    conversation_manager = FakeConversationManager()
    agent = Agent(
        model_gateway=VagueReplyGateway(),
        event_bus=FakeEventBus(),
        config=AgentConfig(max_iterations=3),
        tool_registry=None,
        conversation_manager=conversation_manager,
    )

    response = await agent.run("hello", conversation_id="conv-failed", platform="wechat")

    assert "本轮未完成" in response.content
    assert [failure.reason for failure in conversation_manager.failed_turns] == [
        "stop_verification"
    ]
    assert "conv-failed" not in agent._memory_finalize_tasks
    assert conversation_manager.compress_calls == []
    assert conversation_manager.sync_calls == []


async def test_failed_turn_is_persisted_before_final_text_is_consumed() -> None:
    conversation_manager = FakeConversationManager()
    agent = Agent(
        model_gateway=VagueReplyGateway(),
        event_bus=FakeEventBus(),
        config=AgentConfig(max_iterations=3),
        conversation_manager=conversation_manager,
    )
    stream = agent.run_stream(
        "hello",
        conversation_id="conv-cancelled",
        platform="wechat",
    )

    first_chunk = await anext(stream)
    assert first_chunk.type == "text"
    assert [failure.reason for failure in conversation_manager.failed_turns] == [
        "stop_verification"
    ]

    await stream.aclose()
    assert "conv-cancelled" not in agent._memory_finalize_tasks


async def test_vague_post_tool_reply_becomes_typed_failed_outcome() -> None:
    conversation_manager = FakeConversationManager()
    conversation_manager.task_state = TaskState(objective="inspect logs")
    agent = Agent(
        model_gateway=FakeStreamingGateway(),
        event_bus=FakeEventBus(),
        config=AgentConfig(max_iterations=3),
        conversation_manager=conversation_manager,
    )

    outcome = await verify_and_publish_final_response(
        agent,
        conversation_id="conv-1",
        platform="wechat",
        outcome=CompletedTurn("done"),
        iterations=1,
        all_tool_calls=[{"name": "file_manager"}],
    )

    assert isinstance(outcome, FailedTurn)
    assert outcome.reason == "response_verification"
