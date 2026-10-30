"""Addressable web turns whose lifetime is independent of HTTP connections."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.core.logging import get_logger
from src.core.user_scope import SINGLE_USER_ID
from src.infrastructure.event_bus import EventBus

if TYPE_CHECKING:
    from src.agent.agent import Agent
    from src.agent.coordination import UserExecutionCoordinator

logger = get_logger(__name__)
_TERMINAL = frozenset({"completed", "cancelled", "failed"})
_RETAINED_TERMINAL_RUNS = 100


class ChatRunConflictError(ValueError):
    """A submission conflicts with an existing request or the admission gate."""


@dataclass
class _ChatRun:
    run_id: str
    request_id: str
    conversation_id: str
    status: str = "queued"
    text: str = ""
    tool_events: list[dict[str, str]] = field(default_factory=list)
    error: str | None = None
    task: asyncio.Task[None] | None = None
    delivered: bool = False

    def snapshot(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "request_id": self.request_id,
            "conversation_id": self.conversation_id,
            "status": self.status,
            "text": self.text,
            "tool_events": [dict(event) for event in self.tool_events],
            "error": self.error,
        }


class ChatRunManager:
    """Own run tasks, idempotency and cancellation for the API's canonical user.

    Terminal output is bounded; request fingerprints remain for this process's
    lifetime so an evicted request can fail explicitly instead of executing twice.
    Persistent conversation messages remain the authority after service restart.
    """

    def __init__(self, agent: Agent, execution_coordinator: UserExecutionCoordinator) -> None:
        self._agent = agent
        self._coordinator = execution_coordinator
        self._runs: dict[str, _ChatRun] = {}
        self._requests: dict[str, tuple[str, str]] = {}
        self._withdrawn_requests: set[str] = set()
        self._closing = False
        self._deleting: set[str] = set()
        bus = getattr(agent, "event_bus", None)
        self._event_bus = bus if isinstance(bus, EventBus) else None
        if self._event_bus is not None:
            self._event_bus.subscribe("agent.tool.executed", self._on_tool_executed)

    @property
    def busy(self) -> bool:
        return any(run.status not in _TERMINAL for run in self._runs.values())

    def conversation_busy(self, conversation_id: str) -> bool:
        return any(
            run.conversation_id == conversation_id and run.status not in _TERMINAL
            for run in self._runs.values()
        )

    def start(self, *, message: str, conversation_id: str = "", request_id: str) -> dict[str, Any]:
        if request_id in self._withdrawn_requests:
            raise ChatRunConflictError("This request was withdrawn and cannot be submitted")
        payload = json.dumps([conversation_id, message], ensure_ascii=False)
        fingerprint = hashlib.sha256(payload.encode()).hexdigest()
        previous = self._requests.get(request_id)
        if previous is not None:
            if previous[1] != fingerprint:
                raise ChatRunConflictError(
                    "request_id has already been used for a different message"
                )
            if previous[0] not in self._runs:
                raise ChatRunConflictError("This request has expired; reload conversation history")
            return self.get(previous[0])
        if self._closing or not self._coordinator.accepting:
            raise ChatRunConflictError("The service is restarting and cannot accept a new turn")
        if conversation_id in self._deleting:
            raise ChatRunConflictError("The conversation is being deleted")
        self._prune_terminal_runs()
        run = _ChatRun(uuid.uuid4().hex, request_id, conversation_id or uuid.uuid4().hex)
        self._runs[run.run_id] = run
        self._requests[request_id] = (run.run_id, fingerprint)
        run.task = asyncio.create_task(self._execute(run, message), name=f"chat-{run.run_id}")
        return run.snapshot()

    def get(self, run_id: str) -> dict[str, Any]:
        return self._runs[run_id].snapshot()

    def begin_delete(self, conversation_id: str) -> None:
        if self.conversation_busy(conversation_id) or conversation_id in self._deleting:
            raise ChatRunConflictError("The conversation has an active turn")
        self._deleting.add(conversation_id)

    def end_delete(self, conversation_id: str) -> None:
        self._deleting.discard(conversation_id)

    def forget_conversation(self, conversation_id: str) -> None:
        """Drop terminal output after deletion while keeping idempotency tombstones."""
        if self.conversation_busy(conversation_id):
            raise ChatRunConflictError("The conversation has an active turn")
        self._runs = {
            key: run for key, run in self._runs.items() if run.conversation_id != conversation_id
        }

    def list(
        self, conversation_id: str | None = None, request_id: str | None = None
    ) -> list[dict[str, Any]]:
        return [
            run.snapshot()
            for run in self._runs.values()
            if (conversation_id is None or run.conversation_id == conversation_id)
            and (request_id is None or run.request_id == request_id)
        ]

    def stop(self, run_id: str) -> dict[str, Any]:
        run = self._runs[run_id]
        if run.status not in _TERMINAL and run.status != "stopping":
            # A task cancelled before its first step never enters its finally block.
            # Close queued state here; running state waits for real cleanup/persistence.
            queued = run.status == "queued"
            run.status = "cancelled" if queued else "stopping"
            if run.task is not None:
                run.task.cancel()
        return run.snapshot()

    def stop_request(self, request_id: str) -> dict[str, Any]:
        """Resolve an uncertain submission without allowing a delayed POST to start."""
        self._withdrawn_requests.add(request_id)
        previous = self._requests.get(request_id)
        if previous is None:
            return {"request_id": request_id, "status": "not_accepted"}
        if previous[0] not in self._runs:
            return {"request_id": request_id, "status": "expired"}
        return self.stop(previous[0])

    async def stop_all(self) -> None:
        self._closing = True
        tasks = []
        for run in self._runs.values():
            self.stop(run.run_id)
            if run.task is not None:
                tasks.append(run.task)
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._event_bus is not None:
            self._event_bus.unsubscribe("agent.tool.executed", self._on_tool_executed)

    async def confirm_delivery(self, run_id: str) -> None:
        run = self._runs.get(run_id)
        if run is None or run.delivered or run.status != "completed" or not run.text:
            return
        confirm = getattr(self._agent, "confirm_delivery", None)
        run.delivered = True
        try:
            if confirm is not None:
                await confirm(run.conversation_id, run.text, run.run_id)
        except BaseException:
            run.delivered = False
            raise

    async def _execute(self, run: _ChatRun, message: str) -> None:
        try:
            async with self._coordinator.serialize(SINGLE_USER_ID):
                run.status = "running"
                await self._consume_run(run, message)
        except asyncio.CancelledError as exc:
            run.status = "cancelled"
            run.text = getattr(exc, "partial_text", run.text)
            self._finish_tools(run, "interrupted")
        except Exception as exc:
            logger.error("chat.run_failed", run_id=run.run_id, error_type=type(exc).__name__)
            run.status = "failed"
            run.error = "The turn failed. Check the local application logs."
            self._finish_tools(run, "interrupted")

    async def _consume_run(self, run: _ChatRun, message: str) -> None:
        final_status = "completed"
        async for chunk in self._agent.run_stream(
            message, conversation_id=run.conversation_id, platform="web", user_id=SINGLE_USER_ID
        ):
            if chunk.type == "text":
                run.text += chunk.text
            elif chunk.type == "tool_status":
                self._finish_tools(run, "finished")
                run.tool_events.append({"name": chunk.tool_name, "status": "running"})
            elif chunk.type == "done" and getattr(chunk, "turn_outcome", None) == "failed":
                final_status = "failed"
                run.error = getattr(chunk, "failure_reason", "") or "Turn did not complete"
        self._finish_tools(run, "finished")
        run.status = final_status

    @staticmethod
    def _finish_tools(run: _ChatRun, status: str) -> None:
        run.tool_events = [
            {**event, "status": status} if event["status"] == "running" else event
            for event in run.tool_events
        ]

    async def _on_tool_executed(self, event: dict[str, Any]) -> None:
        for run in self._runs.values():
            if run.status not in {"running", "stopping"}:
                continue
            if run.conversation_id != event.get("conversation_id"):
                continue
            status = "failed" if event.get("is_error") else "finished"
            run.tool_events = [
                {**item, "status": status}
                if item["name"] == event.get("tool") and item["status"] == "running"
                else item
                for item in run.tool_events
            ]

    def _prune_terminal_runs(self) -> None:
        terminal = [run_id for run_id, run in self._runs.items() if run.status in _TERMINAL]
        for run_id in terminal[:-_RETAINED_TERMINAL_RUNS]:
            del self._runs[run_id]
