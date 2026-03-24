"""Trace context for request-scoped correlation.

Uses ``contextvars`` to propagate trace_id, interaction_id, and iteration
across async boundaries.  The structlog processor in ``logging.py`` reads
these values and injects them into every log entry automatically.

Usage::

    from src.core.trace import TraceContext

    async def handle_request():
        with TraceContext(interaction_id="conv_abc") as ctx:
            # All logs within this block carry trace_id + interaction_id
            logger.info("task_received", surface="contextual")
            ctx.iteration = 1
            logger.info("thought_step", surface="cognitive")
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

# Context variables — automatically propagated across await boundaries
_trace_ctx: ContextVar[TraceContext | None] = ContextVar("_trace_ctx", default=None)


@dataclass
class TraceContext:
    """Request-scoped trace context.

    Attributes:
        trace_id: Unique ID for this request/task (auto-generated).
        interaction_id: Conversation or session ID (links related events).
        platform: Origin platform (telegram, web, feishu, scheduler).
        iteration: Current ReAct loop iteration (0 = not in loop).
        parent_action_id: Parent span for tree-structured traces.
        extra: Arbitrary key-value pairs injected into every log.
    """

    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    interaction_id: str = ""
    platform: str = ""
    iteration: int = 0
    parent_action_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def __enter__(self) -> TraceContext:
        self._token = _trace_ctx.set(self)
        return self

    def __exit__(self, *_: Any) -> None:
        _trace_ctx.reset(self._token)

    def to_dict(self) -> dict[str, Any]:
        """Return fields for structlog injection."""
        d: dict[str, Any] = {"trace_id": self.trace_id}
        if self.interaction_id:
            d["interaction_id"] = self.interaction_id
        if self.platform:
            d["platform"] = self.platform
        if self.iteration:
            d["iteration"] = self.iteration
        if self.parent_action_id:
            d["parent_action_id"] = self.parent_action_id
        d.update(self.extra)
        return d


def current_trace() -> TraceContext | None:
    """Get the current trace context (if any)."""
    return _trace_ctx.get()


@contextmanager
def trace_scope(
    interaction_id: str = "",
    platform: str = "",
    **extra: Any,
):
    """Context manager that creates and activates a TraceContext.

    Example::

        with trace_scope(interaction_id="conv_1", platform="telegram"):
            logger.info("task_received", surface="contextual")
    """
    ctx = TraceContext(
        interaction_id=interaction_id,
        platform=platform,
        extra=extra,
    )
    with ctx:
        yield ctx
