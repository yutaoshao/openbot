from __future__ import annotations

from typing import Any

from src.agent.agent import Agent
from src.core.config import AgentConfig
from src.infrastructure.model_gateway import StreamChunk, ToolCall, Usage
from src.tools.builtin.file_manager import FileManagerTool
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


class FinalThenWriteGateway:
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
            yield StreamChunk(type="text", text="# 2026-05-10\n\n今天聊了定时日记。")
            yield StreamChunk(type="done", usage=Usage(tokens_in=5, tokens_out=8))
            return
        if self.calls == 2:
            yield StreamChunk(
                type="tool_call",
                tool_call=ToolCall(
                    id="tc-write",
                    name="file_manager",
                    arguments={
                        "operation": "write_file",
                        "path": "data/diaries/2026-05-10.md",
                        "content": "# 2026-05-10\n\n今天聊了定时日记。",
                    },
                ),
            )
            yield StreamChunk(type="done", usage=Usage(tokens_in=7, tokens_out=4))
            return
        yield StreamChunk(type="text", text="已保存到 data/diaries/2026-05-10.md。")
        yield StreamChunk(type="done", usage=Usage(tokens_in=6, tokens_out=5))


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


async def test_run_repairs_missing_file_write_before_final_reply(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(FileManagerTool(workspace=tmp_path), visibility=CORE_VISIBILITY)
    agent = Agent(
        model_gateway=FinalThenWriteGateway(),
        event_bus=FakeEventBus(),
        config=AgentConfig(max_iterations=4),
        tool_registry=registry,
        conversation_manager=None,
    )

    result = await agent.run("写一篇日记，保存到文件 data/diaries/YYYY-MM-DD.md")

    saved = tmp_path / "data/diaries/2026-05-10.md"
    assert saved.read_text(encoding="utf-8") == "# 2026-05-10\n\n今天聊了定时日记。"
    assert "已保存到 data/diaries/2026-05-10.md" in result.content
