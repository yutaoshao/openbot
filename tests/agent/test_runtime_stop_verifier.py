from __future__ import annotations

from typing import Any

from src.agent.agent import Agent
from src.core.config import AgentConfig
from src.infrastructure.model_gateway import ModelResponse, StreamChunk, ToolCall, Usage
from src.tools.builtin.bash_tool import BashTool
from src.tools.builtin.file_manager import FileManagerTool
from src.tools.builtin.file_mutation_tools import CreateFileTool
from src.tools.effects import ToolEffect
from src.tools.file_mutation_service import FileMutationService
from src.tools.registry import CORE_VISIBILITY, ToolRegistry, ToolResult


class FakeEventBus:
    async def publish(self, event_name: str, data: dict[str, Any]) -> None:
        return None


class ReadThenSavedGateway:
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
            effects=(
                ToolEffect(
                    action="file.read",
                    effect="file_read",
                    status="completed",
                    target_type="file",
                    target="notes.md",
                ),
            ),
        )


class FinalWithoutWriteGateway:
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
            yield StreamChunk(type="text", text="# 2026-05-10\n\n今天聊了定时日记。")
            yield StreamChunk(type="done", usage=Usage(tokens_in=5, tokens_out=8))
            return


class ResearchWriteThenFinalGateway:
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
                    id="tc-write",
                    name="create_file",
                    arguments={
                        "path": "data/workspace/research/openbot-daily/2026-05-20-01-topic.md",
                        "content": "# report",
                    },
                ),
            )
            yield StreamChunk(type="done", usage=Usage(tokens_in=7, tokens_out=4))
            return
        yield StreamChunk(
            type="text",
            text="已保存到 data/workspace/research/openbot-daily/2026-05-20-01-topic.md。",
        )
        yield StreamChunk(type="done", usage=Usage(tokens_in=6, tokens_out=5))


class PlannedUpdateWithoutMutationGateway:
    def __init__(self) -> None:
        self.stream_calls = 0

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **_: Any,
    ) -> ModelResponse:
        return ModelResponse(
            text=(
                '{"required_actions": ['
                '{"action": "file.write", '
                '"target_paths": ["data/workspace/leetcode-hot100-plan.md"]}'
                '], "confidence": 0.93}'
            )
        )

    async def model_round_chunks(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **_: Any,
    ):
        self.stream_calls += 1
        if self.stream_calls == 1:
            yield StreamChunk(type="text", text="已更新计划。")
            yield StreamChunk(type="done", usage=Usage(tokens_in=5, tokens_out=4))
            return


class BashWriteGateway:
    def __init__(self) -> None:
        self.stream_calls = 0

    async def chat(self, *_args, **_kwargs) -> ModelResponse:
        return ModelResponse(
            text=(
                '{"required_actions": ['
                '{"action": "file.write", "target_paths": ["notes.md"]}'
                '], "confidence": 0.97}'
            )
        )

    async def model_round_chunks(self, *_args, **_kwargs):
        self.stream_calls += 1
        if self.stream_calls == 1:
            yield StreamChunk(
                type="tool_call",
                tool_call=ToolCall(
                    id="bash-write",
                    name="bash",
                    arguments={
                        "description": "write notes",
                        "command": "printf bash-only > notes.md",
                    },
                ),
            )
            yield StreamChunk(type="done", usage=Usage(tokens_in=7, tokens_out=4))
            return
        yield StreamChunk(type="text", text="已保存到 notes.md。")
        yield StreamChunk(type="done", usage=Usage(tokens_in=5, tokens_out=3))


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

    assert "没有结构化文件修改凭证" in result.content
    assert "已保存到读书笔记" not in result.content


async def test_run_fails_without_retry_when_required_write_is_missing(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(FileManagerTool(root=tmp_path), visibility=CORE_VISIBILITY)
    agent = Agent(
        model_gateway=FinalWithoutWriteGateway(),
        event_bus=FakeEventBus(),
        config=AgentConfig(max_iterations=4),
        tool_registry=registry,
        conversation_manager=None,
    )

    result = await agent.run("写一篇日记，保存到文件 data/diaries/YYYY-MM-DD.md")

    saved = tmp_path / "data/diaries/2026/05/2026-05-10.md"
    assert not saved.exists()
    assert "没有结构化文件修改凭证" in result.content
    assert result.iterations == 1


async def test_run_accepts_research_report_written_inside_template_dir(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(
        CreateFileTool(FileMutationService(tmp_path)),
        visibility=CORE_VISIBILITY,
    )
    gateway = ResearchWriteThenFinalGateway()
    agent = Agent(
        model_gateway=gateway,
        event_bus=FakeEventBus(),
        config=AgentConfig(max_iterations=3),
        tool_registry=registry,
        conversation_manager=None,
    )
    prompt = (
        "读取 `data/workspace/research/openbot-daily/`，根据已有报告决定下一个功能点。"
        "使用 file_manager 保存到："
        "`data/workspace/research/openbot-daily/YYYY-MM-DD-NN-topic-slug.md`"
    )

    result = await agent.run(prompt)

    saved = tmp_path / "data/workspace/research/openbot-daily/2026-05-20-01-topic.md"
    assert saved.read_text(encoding="utf-8") == "# report"
    assert "未确认写入成功" not in result.content
    assert gateway.calls == 2


async def test_run_fails_immediately_for_planned_update_without_mutation(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(FileManagerTool(root=tmp_path), visibility=CORE_VISIBILITY)
    gateway = PlannedUpdateWithoutMutationGateway()
    agent = Agent(
        model_gateway=gateway,
        event_bus=FakeEventBus(),
        config=AgentConfig(max_iterations=4),
        tool_registry=registry,
        conversation_manager=None,
    )

    result = await agent.run("你更新一下这份计划，每一题都带上题号")

    saved = tmp_path / "data/workspace/leetcode-hot100-plan.md"
    assert not saved.exists()
    assert "没有结构化文件修改凭证" in result.content
    assert gateway.stream_calls == 1


async def test_run_rejects_bash_file_write_without_retrying(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(BashTool(root=tmp_path), visibility=CORE_VISIBILITY)
    gateway = BashWriteGateway()
    agent = Agent(
        model_gateway=gateway,
        event_bus=FakeEventBus(),
        config=AgentConfig(max_iterations=4),
        tool_registry=registry,
        conversation_manager=None,
    )

    result = await agent.run("把内容保存到 notes.md")

    assert (tmp_path / "notes.md").read_text(encoding="utf-8") == "bash-only"
    assert "command_executed 不能作为结构化文件修改凭证" in result.content
    assert gateway.stream_calls == 2
