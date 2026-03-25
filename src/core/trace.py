"""Trace context for request-scoped correlation.

Integrates with OpenTelemetry when configured:
- Creates real OTel spans for each request
- structlog processor reads trace_id / span_id from OTel context

Falls back to lightweight internal tracing when OTel is not configured.

Usage::

    from src.core.trace import TraceContext, setup_tracing

    # Optional: enable OTel export
    setup_tracing(service_name="openbot", otlp_endpoint="http://localhost:4317")

    # Create trace context
    with TraceContext(interaction_id="conv_abc") as ctx:
        logger.info("task_received", surface="contextual")
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from src.core.logging import get_logger

logger = get_logger(__name__)

# Context variables — automatically propagated across await boundaries
_trace_ctx: ContextVar[TraceContext | None] = ContextVar("_trace_ctx", default=None)

# OTel tracer (set by setup_tracing, None if OTel not configured)
_tracer: Any = None


def setup_tracing(
    service_name: str = "openbot",
    otlp_endpoint: str | None = None,
) -> None:
    """Initialize OpenTelemetry tracing with optional OTLP export.

    Args:
        service_name: Service name for OTel resource.
        otlp_endpoint: gRPC endpoint for OTLP exporter (e.g. "http://localhost:4317").
            If None, uses a no-op tracer (traces still populate trace_id/span_id
            in logs but are not exported).
    """
    global _tracer  # noqa: PLW0603

    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        logger.info(
            "tracing.otel_enabled",
            endpoint=otlp_endpoint,
            service=service_name,
        )
    else:
        logger.info("tracing.otel_noop", service=service_name)

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(service_name)


@dataclass
class TraceContext:
    """Request-scoped trace context with optional OTel span.

    Attributes:
        trace_id: Unique ID for this request/task.
        interaction_id: Conversation or session ID.
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
    _span: Any = field(default=None, repr=False, compare=False)
    _token: Any = field(default=None, repr=False, compare=False)
    _otel_token: Any = field(default=None, repr=False, compare=False)

    def __enter__(self) -> TraceContext:
        # Start OTel span if tracer is configured
        if _tracer is not None:
            from opentelemetry import context, trace

            self._span = _tracer.start_span(
                "agent.request",
                attributes={
                    "interaction_id": self.interaction_id,
                    "platform": self.platform,
                },
            )
            # Use OTel trace_id instead of random one
            span_ctx = self._span.get_span_context()
            if span_ctx and span_ctx.is_valid:
                self.trace_id = format(span_ctx.trace_id, "032x")

            # Activate span in OTel context
            otel_ctx = trace.set_span_in_context(self._span)
            self._otel_token = context.attach(otel_ctx)

        self._token = _trace_ctx.set(self)
        return self

    def __exit__(self, *exc: Any) -> None:
        _trace_ctx.reset(self._token)
        if self._span is not None:
            from opentelemetry import context

            self._span.end()
            if self._otel_token is not None:
                context.detach(self._otel_token)

    def to_dict(self) -> dict[str, Any]:
        """Return fields for structlog injection."""
        d: dict[str, Any] = {"trace_id": self.trace_id}

        # Add OTel span_id if available
        if self._span is not None:
            ctx = self._span.get_span_context()
            if ctx and ctx.is_valid:
                d["span_id"] = format(ctx.span_id, "016x")

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
