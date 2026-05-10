from __future__ import annotations

from typing import Any

from src.agent.agent import Agent
from src.core.config import AgentConfig
from src.infrastructure.model_gateway import StreamChunk, ToolCall, Usage
from src.tools.registry import CORE_VISIBILITY, ToolRegistry, ToolResult


class FakeEventBus:
    async def publish(self, event_name: str, data: dict[str, Any]) -> None:
        return None


class ReadThenSavedGateway:
    def __init__(self) -> None:
        self.calls = 0

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **_: Any,
    ):
        self.calls += 1
        if self.calls == 1:
            yield StreamChunk(
                type="tool_call",
                tool_call=ToolCall(
                    id="tc-1",
                    name="fake_file",
                    arguments={"operation": "read_file", "path": "notes.md"},
                ),
            )
            yield StreamChunk(type="done", usage=Usage(tokens_in=5, tokens_out=3))
            return
        yield StreamChunk(type="text", text="已保存到读书笔记。")
        yield StreamChunk(type="done", usage=Usage(tokens_in=6, tokens_out=4))


class FakeFileTool:
    @property
    def name(self) -> str:
        return "fake_file"

    @property
    def description(self) -> str:
        return "Fake file tool"

    @property
    def parameters(self) -> dict[str, object]:
        return {"type": "object", "properties": {}}

    @property
    def category(self) -> str:
        return "filesystem"

    async def execute(self, args: dict[str, object]) -> ToolResult:
        return ToolResult(
            content="read notes.md",
            metadata={
                "operation": "read_file",
                "path": "notes.md",
                "status": "completed",
                "effect": "read",
            },
        )


async def test_run_replaces_unconfirmed_save_claim_with_incomplete_message() -> None:
    registry = ToolRegistry()
    registry.register(FakeFileTool(), visibility=CORE_VISIBILITY)
    agent = Agent(
        model_gateway=ReadThenSavedGateway(),
        event_bus=FakeEventBus(),
        config=AgentConfig(max_iterations=3),
        tool_registry=registry,
        conversation_manager=None,
    )

    result = await agent.run("请保存到读书笔记")

    assert "未确认写入成功" in result.content
    assert "已保存到读书笔记" not in result.content
