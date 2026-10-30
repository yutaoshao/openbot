from __future__ import annotations

import pytest

from src.agent.agent import Agent
from src.core.config import AgentConfig
from src.infrastructure.model_gateway import ModelResponse, StreamChunk, ToolCall, Usage
from src.tools.builtin.file_mutation_tools import AppendFileTool
from src.tools.file_mutation_service import FileMutationService
from src.tools.registry import ToolRegistry


class _EventBus:
    async def publish(self, *_args):
        return None


@pytest.mark.parametrize("tamper", [False, True])
async def test_runtime_verifies_real_app_data_snapshot_and_rejects_tampered_receipt(
    tmp_path, tamper
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.md").write_text("# Notes\n")
    snapshots = tmp_path / "app-data" / "file-snapshots"

    class Gateway:
        def __init__(self):
            self.round = 0

        async def chat(self, *_args, **_kwargs):
            return ModelResponse(
                text='{"required_actions":[{"action":"file.write",'
                '"target_paths":["notes.md"]}],"confidence":0.99}'
            )

        async def model_round_chunks(self, *_args, **_kwargs):
            self.round += 1
            if self.round == 1:
                yield StreamChunk(
                    type="tool_call",
                    tool_call=ToolCall(
                        "append", "append_file", {"path": "notes.md", "content": "new line\n"}
                    ),
                )
                yield StreamChunk(type="done", usage=Usage())
                return
            if tamper:
                next(snapshots.rglob("*.bak")).write_text("tampered snapshot")
            yield StreamChunk(type="text", text="已追加到 notes.md。")
            yield StreamChunk(type="done", usage=Usage())

    registry = ToolRegistry()
    registry.register(AppendFileTool(FileMutationService(workspace, snapshot_root=snapshots)))
    agent = Agent(Gateway(), _EventBus(), AgentConfig(max_iterations=3), registry)
    chunks = [chunk async for chunk in agent.run_stream("在 notes.md 追加一行新内容。")]
    done = chunks[-1]
    assert done.type == "done"
    assert done.turn_outcome == ("failed" if tamper else "completed")
    if tamper:
        assert done.failure_reason == "file_mutation_unverified"
    assert (workspace / "notes.md").read_text() == "# Notes\nnew line\n"
    assert len(list(snapshots.rglob("*.bak"))) == 1
    assert not (workspace / "data" / "file_snapshots").exists()
