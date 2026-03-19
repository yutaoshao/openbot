"""In-process async event bus with wildcard subscription support.

All inter-layer communication goes through the event bus to maintain decoupling.
Supports exact match ("agent.response") and wildcard ("agent.*") patterns.
"""

from __future__ import annotations

import asyncio
import fnmatch
from collections import defaultdict
from collections.abc import Callable, Coroutine
from typing import Any

from src.core.logging import get_logger

logger = get_logger(__name__)

# Type alias for event handler: async callable that takes event data dict
EventHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class EventBus:
    """Async pub/sub event bus with wildcard pattern matching."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, pattern: str, handler: EventHandler) -> None:
        """Subscribe a handler to an event pattern.

        Args:
            pattern: Event name or wildcard pattern (e.g. "agent.*").
            handler: Async callable receiving event data dict.
        """
        self._handlers[pattern].append(handler)
        logger.debug("event_bus.subscribe", pattern=pattern, handler=handler.__qualname__)

    def unsubscribe(self, pattern: str, handler: EventHandler) -> None:
        """Remove a handler from an event pattern."""
        handlers = self._handlers.get(pattern, [])
        if handler in handlers:
            handlers.remove(handler)
            logger.debug("event_bus.unsubscribe", pattern=pattern, handler=handler.__qualname__)

    async def publish(self, event: str, data: dict[str, Any] | None = None) -> None:
        """Publish an event to all matching subscribers.

        Matching rules:
        - Exact match: "agent.response" matches "agent.response"
        - Wildcard: "agent.*" matches "agent.response", "agent.error"
        - Deep wildcard: "agent.**" matches "agent.response.ok"

        Args:
            event: Event name (dot-separated).
            data: Event payload dict.
        """
        if data is None:
            data = {}

        matched_handlers: list[EventHandler] = []
        for pattern, handlers in self._handlers.items():
            if pattern == event or fnmatch.fnmatch(event, pattern):
                matched_handlers.extend(handlers)

        if not matched_handlers:
            return

        logger.debug("event_bus.publish", event_name=event, handler_count=len(matched_handlers))

        # Fire all handlers concurrently, isolate failures
        results = await asyncio.gather(
            *(self._safe_call(handler, event, data) for handler in matched_handlers),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                logger.error("event_bus.handler_error", event_name=event, error=str(result))

    async def _safe_call(
        self, handler: EventHandler, event: str, data: dict[str, Any]
    ) -> None:
        """Call handler with error isolation."""
        try:
            await handler(data)
        except Exception:
            logger.exception(
                "event_bus.handler_exception",
                event_name=event,
                handler=handler.__qualname__,
            )
            raise
