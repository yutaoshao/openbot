from __future__ import annotations

from typing import Any

from src.agent.agent import Agent
from src.core.config import AgentConfig
from src.infrastructure.model_gateway import StreamChunk, ToolCall, Usage
from src.tools.builtin.file_manager import FileManagerTool
from src.tools.registry import CORE_VISIBILITY, ToolRegistry


class FakeEventBus:
    async def publish(self, event_name: str, payload: dict[str, Any]) -> None:
        return None


class ReadThenUnknownToolGateway:
    def __init__(self) -> None:
        self.calls = 0

    async def model_round_chunks(
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
                    id="tc-read",
                    name="file_manager",
                    arguments={"operation": "read_file", "path": "notes.md"},
                ),
            )
            yield StreamChunk(type="done", usage=Usage(tokens_in=5, tokens_out=3))
            return
        if self.calls == 2:
            yield StreamChunk(
                type="tool_call",
                tool_call=ToolCall(
                    id="tc-unknown",
                    name="read_file",
                    arguments={"path": "notes.md"},
                ),
            )
            yield StreamChunk(type="done", usage=Usage(tokens_in=6, tokens_out=4))
            return
        yield StreamChunk(type="text", text="原因是模型调用了不存在的 read_file 工具。")
        yield StreamChunk(type="done", usage=Usage(tokens_in=7, tokens_out=9))


async def test_run_preserves_answer_after_nonblocking_tool_error(tmp_path) -> None:
    (tmp_path / "notes.md").write_text("log details", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(FileManagerTool(root=tmp_path), visibility=CORE_VISIBILITY)
    gateway = ReadThenUnknownToolGateway()
    agent = Agent(
        model_gateway=gateway,
        event_bus=FakeEventBus(),
        config=AgentConfig(max_iterations=4),
        tool_registry=registry,
        conversation_manager=None,
    )

    agent_response = await agent.run("看下日志为什么失败")

    assert "原因是模型调用了不存在的 read_file 工具。" in agent_response.content
    assert "Unknown tool: read_file" in agent_response.content
    assert "本轮未完成" not in agent_response.content
    assert gateway.calls == 3
