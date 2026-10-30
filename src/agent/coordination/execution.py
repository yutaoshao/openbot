"""Per-user execution serialization for cross-platform requests."""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class ExecutionAdmissionClosedError(RuntimeError):
    """New work must not enter during a managed restart."""


class UserExecutionCoordinator:
    """Serialize work for the same canonical user id."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()
        self._pending = 0
        self._accepting = True
        self._tasks: set[asyncio.Task] = set()

    @property
    def busy(self) -> bool:
        """Include queued work, but not idle channel polling."""
        return self._pending > 0

    @property
    def accepting(self) -> bool:
        return self._accepting

    def pause_if_idle(self) -> bool:
        """Atomically close admission only when no work is active or queued."""
        if self.busy:
            return False
        self._accepting = False
        return True

    def resume(self) -> None:
        self._accepting = True

    def stop_accepting(self) -> None:
        self._accepting = False

    async def stop_all(self) -> None:
        """Wait for cancellation persistence from every managed entry point."""
        self.stop_accepting()
        current = asyncio.current_task()
        tasks = tuple(task for task in self._tasks if task is not current)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    @asynccontextmanager
    async def serialize(self, user_id: str) -> AsyncIterator[float]:
        """Hold the lock for *user_id* and yield the queue wait in ms."""
        if not self._accepting:
            raise ExecutionAdmissionClosedError(
                "OpenBot is restarting and is not accepting new work."
            )
        self._pending += 1
        task = asyncio.current_task()
        if task is not None:
            self._tasks.add(task)
        try:
            lock = await self._get_lock(user_id)
            started = time.monotonic()
            await lock.acquire()
            waited_ms = (time.monotonic() - started) * 1000
            try:
                yield waited_ms
            finally:
                lock.release()
        finally:
            self._pending -= 1
            if task is not None:
                self._tasks.discard(task)

    async def _get_lock(self, user_id: str) -> asyncio.Lock:
        if not user_id:
            return asyncio.Lock()
        async with self._guard:
            return self._locks.setdefault(user_id, asyncio.Lock())
