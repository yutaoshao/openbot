from __future__ import annotations

import time
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

from src.agent.agent import Agent
from src.agent.runtime.turn_loop import TurnLoopExecution
from src.agent.runtime.turn_loop_types import LoopCompletion, TurnLoopContext
from src.agent.runtime.turn_request import TurnRequest
from src.agent.state.task_contract import (
    ACTION_FILE_WRITE,
    TaskContract,
    TaskRequirement,
    build_task_contract,
)
from src.agent.turn_outcome import FailedTurn
from src.core.config import AgentConfig
from src.infrastructure.model_gateway import StreamChunk, ToolCall, Usage
from src.tools.registry import CORE_VISIBILITY, ToolRegistry, ToolResult

TURN_TS = datetime(2026, 7, 19, 10, 0, tzinfo=UTC)


class _EventBus:
    async def publish(self, _event_name: str, _payload: dict[str, Any]) -> None:
        return None


class _EchoTool:
    name = "echo"
    description = "Echo a value"
    parameters = {"type": "object", "properties": {}}
    category = "test"

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(content=str(arguments.get("value", "ok")))


class _FinalReplyGateway:
    async def model_round_chunks(self, *_args: object, **_kwargs: object):
        yield StreamChunk(type="text", text="saved")
        yield StreamChunk(type="done", usage=Usage(tokens_in=2, tokens_out=1))


class _ToolLoopGateway:
    def __init__(self, cost_usd: float = 0.0) -> None:
        self._cost_usd = cost_usd

    async def model_round_chunks(self, *_args: object, **_kwargs: object):
        yield StreamChunk(
            type="tool_call",
            tool_call=ToolCall(
                id="echo-call",
                name="echo",
                arguments={"value": "ok"},
            ),
        )
        yield StreamChunk(
            type="done",
            usage=Usage(tokens_in=2, tokens_out=1, cost_usd=self._cost_usd),
        )


def _tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(_EchoTool(), visibility=CORE_VISIBILITY)
    return registry


def _execution(
    *,
    gateway: Any,
    config: AgentConfig,
    user_text: str,
    task_contract: TaskContract,
    tool_registry: ToolRegistry | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> TurnLoopExecution:
    agent = Agent(
        model_gateway=gateway,
        event_bus=_EventBus(),
        config=config,
        tool_registry=tool_registry,
    )
    request = TurnRequest(
        input_text=user_text,
        conversation_id="conv-1",
        platform="web",
        user_id="user-1",
        message_timestamp=TURN_TS,
    )
    context = TurnLoopContext(
        agent=agent,
        request=request,
        trace_context=SimpleNamespace(iteration=0),
        messages=(
            {"role": "system", "content": "system"},
            {"role": "user", "content": user_text},
        ),
        route_decision=None,
        contract=task_contract,
        project_root=None,
        clock=clock,
    )
    return TurnLoopExecution(context)


async def _loop_completion(execution: TurnLoopExecution) -> LoopCompletion:
    completion: LoopCompletion | None = None
    async for event in execution.events():
        if isinstance(event, LoopCompletion):
            completion = event
    assert completion is not None
    return completion


async def test_file_write_verification_produces_failed_outcome() -> None:
    execution = _execution(
        gateway=_FinalReplyGateway(),
        config=AgentConfig(max_iterations=3),
        user_text="请保存到 notes.md",
        task_contract=TaskContract(
            objective="请保存到 notes.md",
            required_actions=(TaskRequirement(ACTION_FILE_WRITE, target_paths=("notes.md",)),),
        ),
    )

    completion = await _loop_completion(execution)

    assert isinstance(completion.outcome, FailedTurn)
    assert completion.outcome.reason == "file_mutation_unverified"


async def test_cost_limit_produces_failed_outcome() -> None:
    execution = _execution(
        gateway=_ToolLoopGateway(cost_usd=1.0),
        config=AgentConfig(max_iterations=3, max_task_cost=0.5),
        user_text="run echo",
        task_contract=build_task_contract("run echo"),
        tool_registry=_tool_registry(),
    )

    completion = await _loop_completion(execution)

    assert isinstance(completion.outcome, FailedTurn)
    assert completion.outcome.reason == "task_cost_limit"


async def test_stuck_loop_produces_failed_outcome() -> None:
    execution = _execution(
        gateway=_ToolLoopGateway(),
        config=AgentConfig(max_iterations=4, stuck_detection_threshold=2),
        user_text="run echo",
        task_contract=build_task_contract("run echo"),
        tool_registry=_tool_registry(),
    )

    completion = await _loop_completion(execution)

    assert isinstance(completion.outcome, FailedTurn)
    assert completion.outcome.reason == "stuck_loop"


async def test_max_iterations_produces_failed_outcome() -> None:
    execution = _execution(
        gateway=_ToolLoopGateway(),
        config=AgentConfig(max_iterations=1, stuck_detection_threshold=0),
        user_text="run echo",
        task_contract=build_task_contract("run echo"),
        tool_registry=_tool_registry(),
    )

    completion = await _loop_completion(execution)

    assert isinstance(completion.outcome, FailedTurn)
    assert completion.outcome.reason == "max_iterations"


async def test_timeout_produces_failed_outcome() -> None:
    clock_ticks = iter((0.0, 2.0))
    execution = _execution(
        gateway=_FinalReplyGateway(),
        config=AgentConfig(max_iterations=3, task_timeout=1),
        user_text="answer",
        task_contract=build_task_contract("answer"),
        clock=lambda: next(clock_ticks),
    )

    completion = await _loop_completion(execution)

    assert isinstance(completion.outcome, FailedTurn)
    assert completion.outcome.reason == "task_timeout"
