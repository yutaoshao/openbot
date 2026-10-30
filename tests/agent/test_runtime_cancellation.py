from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from src.agent.agent import Agent
from src.agent.coordination import UserExecutionCoordinator
from src.application.chat_runs import ChatRunManager
from src.core.config import AgentConfig
from src.infrastructure.event_bus import EventBus
from src.infrastructure.model_gateway import StreamChunk, ToolCall, Usage
from src.tools.builtin.bash_tool import BashTool
from src.tools.registry import ToolRegistry


class _Memory:
    def __init__(self):
        self.users = []
        self.completed = []
        self.failed = []

    async def get_or_create_conversation(self, *_args):
        return None

    async def add_user_message(self, _cid, content, **_kwargs):
        self.users.append(content)

    async def prepare_context_budget(self, _cid, system, user, *_args, **_kwargs):
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def get_task_state(self, _cid):
        return None

    def record_tool_event(self, *_args, **_kwargs):
        return None

    async def add_assistant_message(self, _cid, **kwargs):
        self.completed.append(kwargs)

    async def add_failed_assistant_message(self, _cid, failed_turn, **kwargs):
        self.failed.append((failed_turn, kwargs))


class _PostTurn:
    def __init__(self):
        self.calls = []

    def schedule(self, cid):
        self.calls.append(cid)


class _PartialGateway:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def model_round_chunks(self, *_args, **_kwargs):
        yield StreamChunk(type="text", text="尚未验证的部分内容")
        self.started.set()
        await self.release.wait()
        yield StreamChunk(type="done", usage=Usage(tokens_in=1, tokens_out=1))


def _manager(gateway, memory=None, tools=None):
    memory = memory or _Memory()
    post_turn = _PostTurn()
    agent = Agent(
        gateway,
        EventBus(),
        AgentConfig(max_iterations=3),
        tools,
        memory,
        post_turn_memory=post_turn,
    )
    manager = ChatRunManager(agent, UserExecutionCoordinator())
    run = manager.start(
        message="准备一个本地样例", conversation_id="conv", request_id=str(uuid.uuid4())
    )
    return manager, run["run_id"], memory, post_turn


async def _terminal(manager, run_id):
    async def wait():
        while manager.get(run_id)["status"] not in {"completed", "cancelled", "failed"}:
            await asyncio.sleep(0)
        return manager.get(run_id)

    return await asyncio.wait_for(wait(), 2)


async def test_cancel_persists_model_partial_as_failed_without_publishing_unverified_reply():
    gateway = _PartialGateway()
    manager, run_id, memory, post_turn = _manager(gateway)
    await gateway.started.wait()
    assert manager.get(run_id)["text"] == ""
    assert manager.stop(run_id)["status"] == "stopping"
    result = await _terminal(manager, run_id)
    assert result["status"] == "cancelled"
    assert result["text"] == "尚未验证的部分内容"
    assert len(memory.failed) == 1
    assert memory.failed[0][0].reason == "cancelled"
    assert memory.failed[0][0].content == result["text"]
    assert memory.completed == []
    assert post_turn.calls == []
    await manager.stop_all()


async def test_cancel_during_user_write_finishes_local_write_before_failed_terminal():
    class SlowUserMemory(_Memory):
        def __init__(self):
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def add_user_message(self, _cid, content, **_kwargs):
            self.started.set()
            await self.release.wait()
            self.users.append(content)

    memory = SlowUserMemory()
    manager, run_id, _, post_turn = _manager(_PartialGateway(), memory)
    await memory.started.wait()
    manager.stop(run_id)
    await asyncio.sleep(0)
    assert manager.get(run_id)["status"] == "stopping"
    assert memory.failed == []
    memory.release.set()
    assert (await _terminal(manager, run_id))["status"] == "cancelled"
    assert memory.users == ["准备一个本地样例"]
    assert memory.failed[0][0].reason == "cancelled"
    assert post_turn.calls == []
    await manager.stop_all()


async def test_late_stop_during_final_persistence_preserves_one_completed_terminal():
    class SlowTerminalMemory(_Memory):
        def __init__(self):
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def add_assistant_message(self, _cid, **kwargs):
            self.started.set()
            await self.release.wait()
            self.completed.append(kwargs)

    gateway = _PartialGateway()
    gateway.release.set()
    memory = SlowTerminalMemory()
    manager, run_id, _, post_turn = _manager(gateway, memory)
    await memory.started.wait()
    assert manager.stop(run_id)["status"] == "stopping"
    memory.release.set()
    assert (await _terminal(manager, run_id))["status"] == "completed"
    assert len(memory.completed) == 1
    assert memory.failed == []
    assert post_turn.calls == ["conv"]
    await manager.stop_all()


async def test_cancel_preserves_completed_file_effect_and_records_interrupted_next_tool(tmp_path):
    class WaitTool:
        name = "wait"
        description = "synthetic cancellation point"
        category = "test"
        parameters = {"type": "object", "properties": {}}

        def __init__(self):
            self.started = asyncio.Event()

        async def execute(self, _args):
            self.started.set()
            await asyncio.Event().wait()

    class ToolGateway:
        async def model_round_chunks(self, *_args, **_kwargs):
            yield StreamChunk(
                type="tool_call",
                tool_call=ToolCall(
                    "write",
                    "bash",
                    {
                        "description": "write synthetic effect",
                        "command": "printf kept > effect.txt",
                    },
                ),
            )
            yield StreamChunk(type="tool_call", tool_call=ToolCall("wait", "wait", {}))
            yield StreamChunk(type="done", usage=Usage())

    tools = ToolRegistry()
    tools.register(BashTool(Path(tmp_path)))
    waiting = WaitTool()
    tools.register(waiting)
    manager, run_id, memory, post_turn = _manager(ToolGateway(), tools=tools)
    await asyncio.wait_for(waiting.started.wait(), 2)
    manager.stop(run_id)
    assert (await _terminal(manager, run_id))["status"] == "cancelled"
    assert (tmp_path / "effect.txt").read_text() == "kept"
    failed, fields = memory.failed[0]
    assert failed.reason == "cancelled"
    assert fields["tool_calls"][0]["name"] == "bash"
    assert fields["tool_calls"][0]["effects"][0]["effect"] == "command_executed"
    assert fields["tool_calls"][1]["name"] == "wait"
    assert fields["tool_calls"][1]["metadata"]["interrupted"] is True
    assert post_turn.calls == []
    await manager.stop_all()


async def test_execution_exception_persists_failed_partial_and_does_not_extract_memory():
    class BrokenGateway:
        async def model_round_chunks(self, *_args, **_kwargs):
            yield StreamChunk(type="text", text="模型请求中断前的部分内容")
            raise RuntimeError("synthetic failure")

    manager, run_id, memory, post_turn = _manager(BrokenGateway())
    assert (await _terminal(manager, run_id))["status"] == "failed"
    assert memory.failed[0][0].reason == "execution_error"
    assert memory.failed[0][0].content == "模型请求中断前的部分内容"
    assert memory.completed == []
    assert post_turn.calls == []
    await manager.stop_all()


async def test_completed_tool_is_not_shown_running_while_next_model_call_waits(tmp_path):
    class ToolThenWaitGateway:
        def __init__(self):
            self.round = 0
            self.waiting = asyncio.Event()

        async def model_round_chunks(self, *_args, **_kwargs):
            self.round += 1
            if self.round == 1:
                yield StreamChunk(
                    type="tool_call",
                    tool_call=ToolCall(
                        "write",
                        "bash",
                        {
                            "description": "write synthetic effect",
                            "command": "printf kept > effect.txt",
                        },
                    ),
                )
                yield StreamChunk(type="done", usage=Usage())
                return
            self.waiting.set()
            await asyncio.Event().wait()

    gateway = ToolThenWaitGateway()
    tools = ToolRegistry()
    tools.register(BashTool(Path(tmp_path)))
    manager, run_id, _memory, _post_turn = _manager(gateway, tools=tools)
    await asyncio.wait_for(gateway.waiting.wait(), 2)
    assert manager.get(run_id)["status"] == "running"
    assert manager.get(run_id)["tool_events"] == [{"name": "bash", "status": "finished"}]
    await manager.stop_all()
    assert (tmp_path / "effect.txt").read_text() == "kept"
