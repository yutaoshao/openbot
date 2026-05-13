from __future__ import annotations

from datetime import UTC, datetime

from src.infrastructure.model_gateway import ModelResponse
from src.memory.working import WorkingMemory

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


def _message(role: str, content: str, timestamp: datetime) -> dict[str, object]:
    return {"role": role, "content": content, "timestamp": timestamp}


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
