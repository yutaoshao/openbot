"""Per-user execution serialization for cross-platform requests."""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class UserExecutionCoordinator:
    """Serialize work for the same canonical user id."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    @asynccontextmanager
    async def serialize(self, user_id: str) -> AsyncIterator[float]:
        """Hold the lock for *user_id* and yield the queue wait in ms."""
        lock = await self._get_lock(user_id)
        started = time.monotonic()
        await lock.acquire()
        waited_ms = (time.monotonic() - started) * 1000
        try:
            yield waited_ms
        finally:
            lock.release()

    async def _get_lock(self, user_id: str) -> asyncio.Lock:
        if not user_id:
            return asyncio.Lock()
        async with self._guard:
            return self._locks.setdefault(user_id, asyncio.Lock())
