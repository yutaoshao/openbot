"""State-owning execution object for the ReAct loop."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.agent.turn_outcome import CompletedTurn, FailedTurn, TurnOutcome
from src.core.logging import get_logger
from src.infrastructure.model_gateway import StreamChunk

from .file_write_verification import file_write_verification_failure
from .loop_helpers import (
    UsageTotals,
    accumulate_usage,
    append_assistant_tool_calls,
    cost_limit_text,
    is_stuck,
    timeout_text,
)
from .prompting import resolve_tools
from .rounds import ModelRoundResult, model_round_events
from .stream_context import current_task_state
from .tool_calls import ToolExecutionBatch, execute_tool_calls_for_round
from .turn_loop_types import LoopCompletion, TurnLoopContext, TurnLoopSnapshot

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = get_logger(__name__)


class TurnLoopExecution:
    """Own all mutation required while advancing model and tool rounds."""

    def __init__(self, context: TurnLoopContext) -> None:
        self._context = context
        self._messages = list(context.messages)
        self._task_start = context.clock()
        self._iterations = 0
        self._usage = UsageTotals()
        self._final_model = ""
        self._tool_calls: list[dict[str, Any]] = []
        self._recent_tool_signatures: list[str] = []

    async def events(self) -> AsyncIterator[StreamChunk | LoopCompletion]:
        """Yield tool status chunks followed by exactly one loop completion."""
        while self._iterations < self._context.agent.max_iterations:
            timeout_completion = self._timeout_completion()
            if timeout_completion is not None:
                yield timeout_completion
                return
            model_round, text_chunks = await self._collect_model_round()
            final_completion = self._final_reply_completion(model_round, text_chunks)
            if final_completion is not None:
                yield final_completion
                return
            cost_completion = self._cost_completion()
            if cost_completion is not None:
                yield cost_completion
                return
            self._append_model_tool_calls(model_round)
            tool_batch: ToolExecutionBatch | None = None
            async for event in self._execute_round_tools(model_round):
                if isinstance(event, StreamChunk):
                    yield event
                else:
                    tool_batch = event
            assert tool_batch is not None
            self._tool_calls.extend(tool_batch.executed_calls)
            stuck_completion = self._stuck_completion(model_round)
            if stuck_completion is not None:
                yield stuck_completion
                return
        yield self._max_iterations_completion()

    async def _collect_model_round(
        self,
    ) -> tuple[ModelRoundResult, tuple[StreamChunk, ...]]:
        self._iterations += 1
        self._context.trace_context.iteration = self._iterations
        logger.info(
            "thought_step",
            surface="cognitive",
            iteration=self._iterations,
            max_iterations=self._context.agent.max_iterations,
        )
        task_state = current_task_state(
            self._context.agent,
            self._context.request.conversation_id,
        )
        tools = resolve_tools(
            self._context.agent,
            self._context.request.input_text,
            task_state=task_state,
        )
        model_round: ModelRoundResult | None = None
        text_chunks: list[StreamChunk] = []
        async for event in model_round_events(
            self._context.agent,
            self._messages,
            tools,
            route_decision=self._context.route_decision,
        ):
            if isinstance(event, StreamChunk) and event.type == "text":
                text_chunks.append(event)
            elif isinstance(event, ModelRoundResult):
                model_round = event
        assert model_round is not None
        self._record_model_round(model_round)
        return model_round, tuple(text_chunks)

    def _record_model_round(self, model_round: ModelRoundResult) -> None:
        self._final_model = model_round.model or self._final_model
        self._usage = accumulate_usage(
            self._usage,
            model_round.usage,
        )

    def _final_reply_completion(
        self,
        model_round: ModelRoundResult,
        text_chunks: tuple[StreamChunk, ...],
    ) -> LoopCompletion | None:
        if model_round.collected_tool_calls:
            return None
        logger.info(
            "decision_made",
            surface="cognitive",
            decision="final_reply",
            iteration=self._iterations,
        )
        failure_message = file_write_verification_failure(
            self._context.contract,
            self._tool_calls,
            project_root=self._context.project_root,
        )
        if failure_message is None:
            return self._completion(
                CompletedTurn(model_round.accumulated_text),
                pending_text=model_round.accumulated_text,
                pending_chunks=text_chunks,
            )
        logger.warning(
            "task_failed",
            surface="operational",
            reason="file_mutation_unverified",
            iterations=self._iterations,
        )
        return self._completion(
            FailedTurn(failure_message, reason="file_mutation_unverified"),
        )

    async def _execute_round_tools(
        self,
        model_round: ModelRoundResult,
    ) -> AsyncIterator[StreamChunk | ToolExecutionBatch]:
        task_state = current_task_state(
            self._context.agent,
            self._context.request.conversation_id,
        )
        async for event in execute_tool_calls_for_round(
            self._context.agent,
            collected_tool_calls=model_round.collected_tool_calls,
            conversation_id=self._context.request.conversation_id,
            platform=self._context.request.platform,
            task_state=task_state,
            task_start=self._task_start,
            task_timeout=self._context.agent.config.task_timeout,
            iterations=self._iterations,
            messages=self._messages,
        ):
            yield event

    def _append_model_tool_calls(self, model_round: ModelRoundResult) -> None:
        logger.info(
            "decision_made",
            surface="cognitive",
            decision="tool_calls",
            tool_count=len(model_round.collected_tool_calls),
            tools=[tool_call.name for tool_call in model_round.collected_tool_calls],
            iteration=self._iterations,
        )
        append_assistant_tool_calls(
            self._messages,
            accumulated_text=model_round.accumulated_text,
            reasoning_content=model_round.reasoning_content,
            collected_tool_calls=model_round.collected_tool_calls,
        )

    def _timeout_completion(self) -> LoopCompletion | None:
        elapsed = self._context.clock() - self._task_start
        message = timeout_text(self._context.agent, elapsed, self._iterations)
        if not message:
            return None
        return self._completion(
            FailedTurn(message, reason="task_timeout"),
        )

    def _cost_completion(self) -> LoopCompletion | None:
        message = cost_limit_text(
            self._context.agent,
            self._usage.cost_usd,
            self._iterations,
        )
        if not message:
            return None
        return self._completion(
            FailedTurn(message, reason="task_cost_limit"),
        )

    def _stuck_completion(
        self,
        model_round: ModelRoundResult,
    ) -> LoopCompletion | None:
        stuck = is_stuck(
            self._context.agent.config.stuck_detection_threshold,
            self._recent_tool_signatures,
            model_round,
        )
        if not stuck:
            return None
        logger.warning(
            "task_failed",
            surface="operational",
            reason="stuck_loop",
            repeated_sig=self._recent_tool_signatures[-1][:200],
            iterations=self._iterations,
        )
        message = (
            "Agent appears stuck — repeating the same tool calls. "
            "Stopping to avoid wasting resources."
        )
        return self._completion(
            FailedTurn(message, reason="stuck_loop"),
        )

    def _max_iterations_completion(self) -> LoopCompletion:
        logger.warning(
            "task_failed",
            surface="operational",
            reason="max_iterations",
            iterations=self._iterations,
        )
        return self._completion(
            FailedTurn(
                "Task exceeded maximum iterations.",
                reason="max_iterations",
            ),
        )

    def _completion(
        self,
        outcome: TurnOutcome,
        *,
        pending_text: str = "",
        pending_chunks: tuple[StreamChunk, ...] = (),
    ) -> LoopCompletion:
        return LoopCompletion(
            outcome=outcome,
            snapshot=self._snapshot(),
            pending_text=pending_text,
            pending_chunks=pending_chunks,
        )

    def _snapshot(self) -> TurnLoopSnapshot:
        return TurnLoopSnapshot(
            request=self._context.request,
            contract=self._context.contract,
            project_root=self._context.project_root,
            iterations=self._iterations,
            tokens_in=self._usage.tokens_in,
            tokens_out=self._usage.tokens_out,
            cost_usd=self._usage.cost_usd,
            final_model=self._final_model,
            tool_calls=tuple(self._tool_calls),
        )
