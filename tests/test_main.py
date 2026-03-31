from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from main import Application


async def _completed_task() -> None:
    return None


async def test_wait_for_api_ready_raises_when_server_exits_before_started() -> None:
    task = asyncio.create_task(_completed_task())
    await task
    app = SimpleNamespace(
        api_server=SimpleNamespace(started=False),
        api_task=task,
        config=SimpleNamespace(api=SimpleNamespace(host="127.0.0.1", port=8000)),
    )

    with pytest.raises(RuntimeError, match="exited before becoming ready"):
        await Application._wait_for_api_ready(app, timeout=0.01)


async def test_wait_for_api_ready_returns_when_server_is_started() -> None:
    app = SimpleNamespace(
        api_server=SimpleNamespace(started=True),
        api_task=None,
        config=SimpleNamespace(api=SimpleNamespace(host="127.0.0.1", port=8000)),
    )

    await Application._wait_for_api_ready(app, timeout=0.01)
