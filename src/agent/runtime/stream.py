"""ReAct loop orchestration for the main Agent."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.agent.state.task_contract_planner import (
    plan_scheduled_task_contract,
    plan_task_contract,
)
from src.agent.state.task_contract_resources import (
    agent_project_root,
    resolve_agent_contract_resources,
)
from src.agent.turn_outcome import CompletedTurn, FailedTurn, TurnOutcome, replace_turn_content
from src.agent.verification.stop import ledger_from_tool_calls, verify_stop
from src.infrastructure.model_gateway import StreamChunk, Usage
from src.memory.message_format import strip_internal_timestamp_prefixes

from . import prompting
from .finalize import finalize_agent_run, verify_and_publish_final_response
from .loop_helpers import reply_chunks
from .stream_context import choose_route, current_task_state
from .turn_loop import TurnLoopExecution
from .turn_loop_types import LoopCompletion, TurnLoopContext, TurnLoopSnapshot

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from .turn_request import TurnRequest

build_system_prompt = prompting.build_system_prompt
prepare_agent_turn = prompting.prepare_agent_turn
resolve_tools = prompting.resolve_tools


async def run_stream_inner(
    agent: Any,
    request: TurnRequest,
    trace_context: Any,
) -> AsyncIterator[StreamChunk]:
    """Prepare, execute, verify, persist, and stream one turn."""
    execution = await _prepare_turn_loop(agent, request, trace_context)
    completion: LoopCompletion | None = None
    async for event in execution.events():
        if isinstance(event, StreamChunk):
            yield event
        else:
            completion = event
    assert completion is not None
    outcome = await _verified_stop_outcome(agent, completion)
    snapshot = completion.snapshot
    await finalize_agent_run(
        agent,
        conversation_id=snapshot.request.conversation_id,
        outcome=outcome,
        model=snapshot.final_model,
        tokens_in=snapshot.tokens_in,
        tokens_out=snapshot.tokens_out,
        latency_ms=0,
        iterations=snapshot.iterations,
        all_tool_calls=list(snapshot.tool_calls),
    )
    for chunk in reply_chunks(
        outcome.content,
        pending_final_text=completion.pending_text,
        pending_final_chunks=list(completion.pending_chunks),
    ):
        yield chunk
    yield _done_chunk(snapshot)


async def _prepare_turn_loop(
    agent: Any,
    request: TurnRequest,
    trace_context: Any,
) -> TurnLoopExecution:
    messages = await prepare_agent_turn(agent, request)
    task_state = current_task_state(agent, request.conversation_id)
    route_decision = choose_route(agent, request.input_text, task_state)
    await agent.event_bus.publish(
        "agent.think.start",
        {
            "conversation_id": request.conversation_id,
            "input_length": len(request.input_text),
        },
    )
    planner = (
        plan_scheduled_task_contract if request.platform == "scheduler" else plan_task_contract
    )
    contract = await planner(
        agent.model_gateway,
        request.input_text,
        messages=messages,
        task_state=task_state,
    )
    return TurnLoopExecution(
        TurnLoopContext(
            agent=agent,
            request=request,
            trace_context=trace_context,
            messages=tuple(messages),
            route_decision=route_decision,
            contract=resolve_agent_contract_resources(contract, agent),
            project_root=agent_project_root(agent),
        )
    )


async def _verified_stop_outcome(
    agent: Any,
    completion: LoopCompletion,
) -> TurnOutcome:
    snapshot = completion.snapshot
    outcome = await verify_and_publish_final_response(
        agent,
        conversation_id=snapshot.request.conversation_id,
        platform=snapshot.request.platform,
        outcome=completion.outcome,
        iterations=snapshot.iterations,
        all_tool_calls=list(snapshot.tool_calls),
    )
    outcome = _strip_internal_timestamps(outcome)
    stop_decision = verify_stop(
        snapshot.contract,
        outcome.content,
        ledger_from_tool_calls(list(snapshot.tool_calls)),
        project_root=snapshot.project_root,
    )
    if stop_decision.message:
        outcome = replace_turn_content(outcome, stop_decision.message)
    if not stop_decision.allow and isinstance(outcome, CompletedTurn):
        outcome = FailedTurn(outcome.content, reason="stop_verification")
    return _strip_internal_timestamps(outcome)


def _strip_internal_timestamps(outcome: TurnOutcome) -> TurnOutcome:
    return replace_turn_content(
        outcome,
        strip_internal_timestamp_prefixes(outcome.content),
    )


def _done_chunk(snapshot: TurnLoopSnapshot) -> StreamChunk:
    return StreamChunk(
        type="done",
        usage=Usage(
            tokens_in=snapshot.tokens_in,
            tokens_out=snapshot.tokens_out,
            cost_usd=snapshot.cost_usd,
        ),
        model=snapshot.final_model,
        iterations=snapshot.iterations,
    )
