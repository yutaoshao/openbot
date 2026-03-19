from __future__ import annotations

from src.infrastructure.model_gateway import ModelResponse
from src.memory.working import WorkingMemory


class FakeModelGateway:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.calls: list[list[dict[str, str]]] = []

    async def chat(self, messages: list[dict[str, str]]) -> ModelResponse:
        self.calls.append(messages)
        return ModelResponse(text=self._responses.pop(0))


async def test_working_memory_compress_replaces_older_half_with_summary() -> None:
    gateway = FakeModelGateway(["summary: keep key facts"])
    wm = WorkingMemory(conversation_id="conv-1", token_budget=1)

    wm.add({"role": "user", "content": "old user"})
    wm.add({"role": "assistant", "content": "old assistant"})
    wm.add({"role": "user", "content": "recent user"})
    wm.add({"role": "assistant", "content": "recent assistant"})

    summary = await wm.compress(gateway)
    assembled = wm.get_messages()

    assert summary == "summary: keep key facts"
    assert assembled[0]["role"] == "system"
    assert "Summary of earlier conversation" in assembled[0]["content"]
    assert assembled[1:] == [
        {"role": "user", "content": "recent user"},
        {"role": "assistant", "content": "recent assistant"},
    ]


async def test_extract_before_compression_filters_invalid_items() -> None:
    raw = (
        '[{"category":"fact","content":"timezone is Asia/Shanghai"},'
        '{"category":"noise","content":"hello"},'
        '{"category":"concept","content":42}]'
    )
    gateway = FakeModelGateway([raw])
    wm = WorkingMemory(conversation_id="conv-2", token_budget=1)

    wm.add({"role": "user", "content": "message 1"})
    wm.add({"role": "assistant", "content": "message 2"})
    wm.add({"role": "user", "content": "message 3"})
    wm.add({"role": "assistant", "content": "message 4"})

    items = await wm.extract_before_compression(gateway)

    assert items == [
        {"category": "fact", "content": "timezone is Asia/Shanghai"},
    ]
