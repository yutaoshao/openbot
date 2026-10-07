from __future__ import annotations

from datetime import UTC, datetime

from src.agent.turn_outcome import FailedTurn
from src.infrastructure.model_gateway import ModelResponse
from src.memory.working import WorkingMemory
from src.memory.working_compaction import _merge_summaries, summarize_messages

TS1 = datetime(2026, 5, 1, 8, 30, tzinfo=UTC)
TS2 = datetime(2026, 5, 1, 8, 31, tzinfo=UTC)
TS3 = datetime(2026, 5, 1, 8, 32, tzinfo=UTC)
TS4 = datetime(2026, 5, 1, 8, 33, tzinfo=UTC)


class FakeModelGateway:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.calls: list[list[dict[str, str]]] = []

    async def chat(self, messages: list[dict[str, str]]) -> ModelResponse:
        self.calls.append(messages)
        return ModelResponse(text=self._responses.pop(0))


def _message(
    role: str,
    content: str,
    timestamp: datetime,
    **fields: object,
) -> dict[str, object]:
    return {"role": role, "content": content, "timestamp": timestamp, **fields}


async def test_working_memory_compress_replaces_older_half_with_summary() -> None:
    gateway = FakeModelGateway(["summary: keep key facts"])
    wm = WorkingMemory(conversation_id="conv-1", token_budget=1)

    wm.add(_message("user", "old user", TS1))
    wm.add(_message("assistant", "old assistant", TS2))
    wm.add(_message("user", "recent user", TS3))
    wm.add(_message("assistant", "recent assistant", TS4))

    summary = await wm.compress(gateway)
    assembled = wm.get_messages()

    assert summary.startswith("summary: keep key facts")
    assert assembled[0]["role"] == "system"
    assert "Summary of earlier conversation" in assembled[0]["content"]
    assert assembled[1]["role"] == "user"
    assert assembled[2]["role"] == "assistant"
    assert "recent user" in assembled[1]["content"]
    assert "recent assistant" in assembled[2]["content"]
    assert "[2026-" in assembled[1]["content"]


async def test_working_memory_compress_appends_history_file_references(
    monkeypatch,
) -> None:
    monkeypatch.setattr("src.memory.message_format._local_timezone", lambda: UTC)
    gateway = FakeModelGateway(["summary: keep key facts"])
    wm = WorkingMemory(conversation_id="conv-refs", token_budget=1)

    wm.add(_message("user", "old user", TS1))
    wm.add(_message("assistant", "old assistant", TS2))
    wm.add(_message("user", "recent user", TS3))
    wm.add(_message("assistant", "recent assistant", TS4))

    summary = await wm.compress(gateway)

    assert "完整历史见 data/conversations/2026/05/01.jsonl" in summary


async def test_working_memory_preserves_messages_when_summary_and_retry_are_empty() -> None:
    gateway = FakeModelGateway(["", ""])
    wm = WorkingMemory(conversation_id="conv-empty-summary", token_budget=1)

    wm.add(_message("user", "old user", TS1))
    wm.add(_message("assistant", "old assistant", TS2))
    wm.add(_message("user", "recent user", TS3))
    wm.add(_message("assistant", "recent assistant", TS4))

    original = [item.copy() for item in wm.get_messages()]
    summary = await wm.compress(gateway)

    assert summary == ""
    assert wm.get_messages() == original


async def test_summary_retries_once_when_provider_returns_empty() -> None:
    gateway = FakeModelGateway(["", "retry summary"])
    summary = await summarize_messages(
        model_gateway=gateway,
        messages=[_message("user", "old user", TS1), _message("assistant", "old reply", TS2)],
    )

    assert summary == "retry summary"
    assert len(gateway.calls) == 2


async def test_summary_merge_keeps_all_batch_summaries_when_merge_is_empty() -> None:
    gateway = FakeModelGateway([""])
    merged = await _merge_summaries(gateway, ["first facts", "second facts"])

    assert "first facts" in merged and "second facts" in merged


async def test_working_memory_does_not_discard_failed_turn_without_summary() -> None:
    gateway = FakeModelGateway([])
    wm = WorkingMemory(conversation_id="conv-failed", token_budget=1)
    failure_metadata = FailedTurn("failed", reason="stop_verification").message_metadata()

    wm.add(_message("user", "failed request", TS1))
    wm.add(_message("assistant", "failed reply", TS2, metadata=failure_metadata))
    wm.add(_message("user", "recent user", TS3))
    wm.add(_message("assistant", "recent assistant", TS4))

    summary = await wm.compress(gateway)
    assembled = wm.get_messages()

    assert summary == ""
    assert gateway.calls == []
    assert [message["role"] for message in assembled] == ["user", "assistant", "user", "assistant"]
    assert "failed request" in assembled[0]["content"]


async def test_working_memory_compress_keeps_token_bounded_complete_turns() -> None:
    gateway = FakeModelGateway(["summary: first pair"])
    wm = WorkingMemory(conversation_id="conv-boundary", token_budget=1, recent_budget=170)
    messages = [
        _message("user", "first user", TS1),
        _message("assistant", "first assistant", TS1),
        _message("user", "second user", TS2),
        _message("assistant", "second assistant", TS2),
        _message("user", "third user", TS3),
        _message("assistant", "third assistant", TS3),
    ]
    for message in messages:
        wm.add(message)

    await wm.compress(gateway)
    assembled = wm.get_messages()

    assert [message["role"] for message in assembled] == [
        "system",
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert "first user" in gateway.calls[0][0]["content"]
    assert "second user" not in gateway.calls[0][0]["content"]


async def test_extract_before_compression_filters_invalid_items() -> None:
    raw = (
        '[{"category":"fact","content":"timezone is Asia/Shanghai"},'
        '{"category":"noise","content":"hello"},'
        '{"category":"concept","content":42}]'
    )
    gateway = FakeModelGateway([raw])
    wm = WorkingMemory(conversation_id="conv-2", token_budget=1)

    wm.add(_message("user", "message 1", TS1))
    wm.add(_message("assistant", "message 2", TS2))
    wm.add(_message("user", "message 3", TS3))
    wm.add(_message("assistant", "message 4", TS4))

    items = await wm.extract_before_compression(gateway)

    assert items == [
        {"category": "fact", "content": "timezone is Asia/Shanghai"},
    ]


async def test_extract_before_compression_excludes_failed_turn() -> None:
    gateway = FakeModelGateway([])
    wm = WorkingMemory(conversation_id="conv-failed", token_budget=1)
    failure_metadata = FailedTurn("failed", reason="stop_verification").message_metadata()

    wm.add(_message("user", "failed request", TS1))
    wm.add(_message("assistant", "failed reply", TS2, metadata=failure_metadata))
    wm.add(_message("user", "recent user", TS3))
    wm.add(_message("assistant", "recent assistant", TS4))

    items = await wm.extract_before_compression(gateway)

    assert items == []
    assert gateway.calls == []


async def test_extract_before_compression_accepts_wrapped_json_array() -> None:
    gateway = FakeModelGateway(
        [
            """
            Here are the long-term items:
            [
              {"category":"fact","content":"timezone is Asia/Shanghai"}
            ]
            """,
        ]
    )
    wm = WorkingMemory(conversation_id="conv-3", token_budget=1)

    wm.add(_message("user", "message 1", TS1))
    wm.add(_message("assistant", "message 2", TS2))
    wm.add(_message("user", "message 3", TS3))
    wm.add(_message("assistant", "message 4", TS4))

    items = await wm.extract_before_compression(gateway)

    assert items == [{"category": "fact", "content": "timezone is Asia/Shanghai"}]


async def test_extract_before_compression_accepts_fenced_json_array() -> None:
    gateway = FakeModelGateway(
        [
            """```json
            [
              {"category":"procedure","content":"Deploy with make release"}
            ]
            ```""",
        ]
    )
    wm = WorkingMemory(conversation_id="conv-4", token_budget=1)

    wm.add(_message("user", "message 1", TS1))
    wm.add(_message("assistant", "message 2", TS2))
    wm.add(_message("user", "message 3", TS3))
    wm.add(_message("assistant", "message 4", TS4))

    items = await wm.extract_before_compression(gateway)

    assert items == [{"category": "procedure", "content": "Deploy with make release"}]


async def test_extract_before_compression_ignores_tool_call_wrappers() -> None:
    gateway = FakeModelGateway(
        [
            """
            [TOOL_CALL]
            {tool => "web_search", args => {"query": "memory system"}}
            [/TOOL_CALL]
            """,
        ]
    )
    wm = WorkingMemory(conversation_id="conv-5", token_budget=1)

    wm.add(_message("user", "message 1", TS1))
    wm.add(_message("assistant", "message 2", TS2))
    wm.add(_message("user", "message 3", TS3))
    wm.add(_message("assistant", "message 4", TS4))

    items = await wm.extract_before_compression(gateway)

    assert items == []
