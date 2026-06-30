from __future__ import annotations

from typing import Any

from src.agent.agent import Agent
from src.core.config import AgentConfig
from src.infrastructure.model_gateway import ModelResponse, StreamChunk, ToolCall, Usage
from src.tools.builtin.file_manager import FileManagerTool
from src.tools.registry import CORE_VISIBILITY, ToolRegistry


class _EventBus:
    async def publish(self, event_name: str, payload: dict[str, Any]) -> None:
        return None


class _TodoAliasGateway:
    def __init__(self) -> None:
        self.stream_calls = 0

    async def chat(self, *_args, **_kwargs) -> ModelResponse:
        return ModelResponse(
            text=(
                '{"required_actions": ['
                '{"action": "file.write", "target_paths": ["TODO.md"]}'
                '], "confidence": 0.95}'
            )
        )

    async def model_round_chunks(self, *_args, **_kwargs):
        self.stream_calls += 1
        if self.stream_calls == 1:
            yield StreamChunk(
                type="tool_call",
                tool_call=ToolCall(
                    id="write-todo",
                    name="file_manager",
                    arguments={
                        "operation": "write_file",
                        "path": "data/TODO.md",
                        "content": "## 意图识别改进\n",
                    },
                ),
            )
            yield StreamChunk(type="done", usage=Usage(tokens_in=10, tokens_out=5))
            return
        yield StreamChunk(type="text", text="已保存到 data/TODO.md。")
        yield StreamChunk(type="done", usage=Usage(tokens_in=10, tokens_out=5))


async def test_runtime_accepts_unique_todo_alias_write_without_retry_loop(tmp_path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "TODO.md").write_text("# TODO\n", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(FileManagerTool(root=tmp_path), visibility=CORE_VISIBILITY)
    gateway = _TodoAliasGateway()
    agent = Agent(
        model_gateway=gateway,
        event_bus=_EventBus(),
        config=AgentConfig(max_iterations=4),
        tool_registry=registry,
        conversation_manager=None,
    )

    result = await agent.run("把这份意图识别的改进加到TODO.md里面去。")

    assert result.content == "已保存到 data/TODO.md。"
    assert (tmp_path / "data" / "TODO.md").read_text(encoding="utf-8") == "## 意图识别改进\n"
    assert gateway.stream_calls == 2
