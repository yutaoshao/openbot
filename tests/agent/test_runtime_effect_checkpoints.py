from __future__ import annotations

import asyncio
import hashlib
import uuid
from types import SimpleNamespace

import pytest

from src.agent.agent import Agent
from src.agent.coordination import UserExecutionCoordinator
from src.application.chat_runs import ChatRunManager
from src.core.config import AgentConfig
from src.infrastructure.event_bus import EventBus
from src.infrastructure.model_gateway import StreamChunk, ToolCall, Usage
from src.tools.builtin.file_mutation_tools import CreateFileTool
from src.tools.file_mutation_service import FileMutationService
from src.tools.hooks import PostToolHookResult, PreToolHookResult, ToolHookManager
from src.tools.registry import ToolRegistry


class _Memory:
    def __init__(self):
        self.failed = []
        self.extractions = []

    async def get_or_create_conversation(self, *_args):
        return None

    async def add_user_message(self, *_args, **_kwargs):
        return None

    async def prepare_context_budget(self, _cid, system, user, *_args, **_kwargs):
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def get_task_state(self, _cid):
        return None

    def record_tool_event(self, *_args, **_kwargs):
        return None

    async def add_failed_assistant_message(self, _cid, failed_turn, **fields):
        self.failed.append((failed_turn, fields))


@pytest.mark.parametrize("stop_stage", ["metrics", "after_execute"])
async def test_stop_after_real_file_effect_preserves_returned_receipt_before_postprocessing(
    tmp_path, stop_stage
):
    blocked = asyncio.Event()
    bus = EventBus()
    memory = _Memory()

    class MarkerTool(CreateFileTool):
        async def execute(self, args):
            result = await super().execute(args)
            result.metadata = {
                **result.metadata,
                "actual_effect_completed": True,
                "diagnostic": {"state": "at-return"},
            }
            return result

    class PostprocessingHook:
        async def before_execute(self, *_args):
            return PreToolHookResult(
                override_args={"path": "actual-marker.txt", "content": "committed"}
            )

        async def after_execute(self, _name, _args, result, _state):
            result.metadata["diagnostic"]["state"] = "post-hook"
            if stop_stage == "after_execute":
                blocked.set()
                await asyncio.Event().wait()
            return PostToolHookResult()

    async def metric(_event):
        if stop_stage == "metrics":
            blocked.set()
            await asyncio.Event().wait()

    class Gateway:
        async def model_round_chunks(self, *_args, **_kwargs):
            yield StreamChunk(
                type="tool_call",
                tool_call=ToolCall(
                    "marker", "create_file", {"path": "requested-marker.txt", "content": "original"}
                ),
            )
            yield StreamChunk(type="done", usage=Usage())

    bus.subscribe("agent.tool.executed", metric)
    registry = ToolRegistry()
    marker = MarkerTool(FileMutationService(tmp_path))
    registry.register(marker)
    agent = Agent(
        Gateway(),
        bus,
        AgentConfig(max_iterations=3, tool_timeout=2),
        registry,
        memory,
        post_turn_memory=SimpleNamespace(schedule=memory.extractions.append),
    )
    agent.tool_hooks = ToolHookManager([PostprocessingHook()])
    manager = ChatRunManager(agent, UserExecutionCoordinator())
    run = manager.start(
        message="准备一个样例", conversation_id="conv", request_id=str(uuid.uuid4())
    )
    await asyncio.wait_for(blocked.wait(), 2)
    assert (tmp_path / "actual-marker.txt").read_text() == "committed"
    manager.stop(run["run_id"])

    async def wait_for_terminal():
        while manager.get(run["run_id"])["status"] not in {"completed", "cancelled", "failed"}:
            await asyncio.sleep(0)
        return manager.get(run["run_id"])

    terminal = await asyncio.wait_for(wait_for_terminal(), 2)
    assert terminal["status"] == "cancelled"
    assert (tmp_path / "actual-marker.txt").read_text() == "committed"
    assert not (tmp_path / "requested-marker.txt").exists()
    assert len(memory.failed) == 1
    failed, fields = memory.failed[0]
    assert failed.reason == "cancelled"
    assert len(fields["tool_calls"]) == 1
    record = fields["tool_calls"][0]
    assert record["is_error"] is False
    assert record["arguments"] == {"path": "actual-marker.txt", "content": "committed"}
    assert record["metadata"]["actual_effect_completed"] is True
    expected_state = "post-hook" if stop_stage == "metrics" else "at-return"
    assert record["metadata"]["diagnostic"]["state"] == expected_state
    effect = record["effects"][0]
    assert effect["status"] == "completed"
    assert effect["effect"] == "file_written"
    assert (
        effect["details"]["file_mutation"]["after_sha256"]
        == hashlib.sha256(b"committed").hexdigest()
    )
    assert memory.extractions == []
    await manager.stop_all()


async def test_after_hook_failure_does_not_replace_a_completed_file_receipt_with_no_effect(
    tmp_path,
):
    from src.agent.runtime.tool_executor import execute_tool_call
    from src.tools.file_mutation_receipt import verified_file_mutation

    class BrokenHook:
        async def before_execute(self, *_args):
            return PreToolHookResult()

        async def after_execute(self, *_args):
            raise RuntimeError("synthetic postprocessing failure")

    registry = ToolRegistry()
    registry.register(CreateFileTool(FileMutationService(tmp_path)))
    checkpointed = []

    def capture(result, _args):
        checkpointed.append((result.is_error, [effect.to_dict() for effect in result.effects]))

    result = await execute_tool_call(
        registry,
        AgentConfig(),
        ToolHookManager([BrokenHook()]),
        "create_file",
        {"path": "marker.txt", "content": "kept"},
        conversation_id="conv",
        platform="web",
        checkpoint=capture,
    )
    assert result.is_error
    assert result.metadata["postprocessing_error"] == "RuntimeError"
    assert (tmp_path / "marker.txt").read_text() == "kept"
    assert verified_file_mutation(result.effects[0], tmp_path)
    assert checkpointed[0][0] is False
    assert checkpointed[-1][0] is True
    assert all(records[0]["effect"] == "file_written" for _error, records in checkpointed)
