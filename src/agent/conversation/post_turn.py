"""Own post-reply memory work until application shutdown."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.core.logging import get_logger
from src.core.trace import TraceContext, current_trace

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from .manager import ConversationManager

logger = get_logger(__name__)


@dataclass(frozen=True)
class _BackgroundTraceInfo:
    interaction_id: str
    platform: str
    parent_trace_id: str


class PostTurnMemory:
    """Serialize per-conversation synchronization and own its background tasks."""

    def __init__(self, conversations: ConversationManager | None) -> None:
        self._conversations = conversations
        self._latest: dict[str, asyncio.Task[None]] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._stopping = False

    def schedule(self, conversation_id: str) -> None:
        if self._stopping:
            raise RuntimeError("Post-turn memory is stopping")
        previous = self._latest.get(conversation_id)
        trace = current_trace()
        info = _BackgroundTraceInfo(
            interaction_id=trace.interaction_id or conversation_id if trace else conversation_id,
            platform=trace.platform if trace else "",
            parent_trace_id=trace.trace_id if trace else "",
        )
        task = asyncio.create_task(
            self._run(conversation_id, previous, info), name=f"memory-finalize:{conversation_id}"
        )
        self._latest[conversation_id] = task
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def task_for(self, conversation_id: str) -> asyncio.Task[None] | None:
        """Return the active work for a conversation, when present."""
        return self._latest.get(conversation_id)

    async def stop(self) -> None:
        """Stop new work and await all cancellations before storage closes."""
        self._stopping = True
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        failures = [result for result in results if isinstance(result, Exception)]
        self._latest.clear()
        if failures:
            raise ExceptionGroup("Post-turn memory shutdown failed", failures)

    async def _run(
        self,
        conversation_id: str,
        previous: asyncio.Task[None] | None,
        info: _BackgroundTraceInfo,
    ) -> None:
        try:
            if previous is not None:
                try:
                    await previous
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.warning(
                        "conversation.background_finalize_prior_failed",
                        conversation_id=conversation_id,
                        exc_info=True,
                    )
            if self._conversations is None:
                return
            with TraceContext(
                interaction_id=info.interaction_id,
                platform=info.platform,
                parent_action_id=info.parent_trace_id,
                extra={"trigger": "post_reply_sync"},
            ):
                await _run_step(
                    self._conversations.maybe_compress,
                    conversation_id,
                    "conversation.background_compress_failed",
                )
                await _run_step(
                    self._conversations.sync_memory_after_turn,
                    conversation_id,
                    "conversation.background_sync_failed",
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "conversation.background_finalize_failed", conversation_id=conversation_id
            )
        finally:
            if self._latest.get(conversation_id) is asyncio.current_task():
                self._latest.pop(conversation_id, None)


async def _run_step(
    action: Callable[[str], Awaitable[None]], conversation_id: str, error_event: str
) -> None:
    try:
        await action(conversation_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception(error_event, conversation_id=conversation_id)
