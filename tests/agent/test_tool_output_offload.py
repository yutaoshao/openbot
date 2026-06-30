from __future__ import annotations

from typing import Any

from src.agent.agent import Agent
from src.core.config import AgentConfig
from src.infrastructure.model_gateway import StreamChunk, ToolCall, Usage
from src.tools.registry import CORE_VISIBILITY, ToolRegistry, ToolResult


class LongOutputGateway:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, Any]]] = []

    async def model_round_chunks(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **_: Any,
    ):
        self.calls.append([dict(message) for message in messages])
        if len(self.calls) == 1:
            yield StreamChunk(
                type="tool_call",
                tool_call=ToolCall(id="tc-1", name="long_tool", arguments={}),
            )
            yield StreamChunk(type="done", usage=Usage(tokens_in=1, tokens_out=1))
            return
        yield StreamChunk(type="text", text="read the saved output")
        yield StreamChunk(type="done", usage=Usage(tokens_in=1, tokens_out=1))


class LongTool:
    @property
    def name(self) -> str:
        return "long_tool"

    @property
    def description(self) -> str:
        return "Returns long text"

    @property
    def parameters(self) -> dict[str, object]:
        return {"type": "object", "properties": {}}

    @property
    def category(self) -> str:
        return "test"

    async def execute(self, args: dict[str, object]) -> ToolResult:
        return ToolResult(content="x" * 10001, metadata={"source": "test"})


async def test_long_tool_output_is_saved_and_replaced_with_file_reference(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    gateway = LongOutputGateway()
    registry = ToolRegistry()
    registry.register(LongTool(), visibility=CORE_VISIBILITY)
    agent = Agent(
        model_gateway=gateway,
        event_bus=_NoopBus(),
        config=AgentConfig(max_iterations=3),
        tool_registry=registry,
    )

    result = await agent.run("call long tool", conversation_id="conv-1", platform="web")

    assert result.content == "read the saved output"
    saved_files = list((tmp_path / "data" / "tool_outputs").glob("**/*.txt"))
    assert len(saved_files) == 1
    assert saved_files[0].read_text(encoding="utf-8") == "x" * 10001
    tool_messages = [item for item in gateway.calls[1] if item["role"] == "tool"]
    assert len(tool_messages) == 1
    assert "data/tool_outputs" in tool_messages[0]["content"]
    assert "10001 chars" in tool_messages[0]["content"]
    assert "x" * 10001 not in tool_messages[0]["content"]


class _NoopBus:
    async def publish(self, event_name: str, data: dict[str, Any]) -> None:
        return None
