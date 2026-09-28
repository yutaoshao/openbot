from __future__ import annotations

import asyncio
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI

from main import Application
from src.agent.conversation.post_turn import PostTurnMemory
from src.application import lifecycle
from src.channels.hub import MsgHub
from src.infrastructure.event_bus import EventBus


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


async def test_wait_for_api_ready_raises_on_timeout() -> None:
    task = asyncio.create_task(asyncio.Event().wait())
    app = SimpleNamespace(
        api_server=SimpleNamespace(started=False),
        api_task=task,
        config=SimpleNamespace(api=SimpleNamespace(host="127.0.0.1", port=8000)),
    )
    try:
        with pytest.raises(TimeoutError, match="did not become ready"):
            await lifecycle.wait_for_api_ready(app, timeout=0)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_api_shutdown_cancels_a_server_stalled_during_startup() -> None:
    cancelled = asyncio.Event()

    async def stalled_start() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    task = asyncio.create_task(stalled_start())
    await asyncio.sleep(0)
    server = SimpleNamespace(started=False, should_exit=False)
    app = SimpleNamespace(api_server=server, api_task=task)

    await asyncio.wait_for(lifecycle._stop_api(app), timeout=0.5)

    assert cancelled.is_set()
    assert server.should_exit


def _partly_started_app() -> SimpleNamespace:
    return SimpleNamespace(
        api_server=None,
        api_task=None,
        housekeeping_task=None,
        scheduler=None,
        feishu=None,
        wechat=None,
        telegram=None,
        post_turn_memory=SimpleNamespace(stop=AsyncMock()),
        database=SimpleNamespace(close=AsyncMock()),
    )


async def test_failed_start_cleans_up_partly_started_resources(monkeypatch) -> None:
    app = _partly_started_app()

    async def failed_start(_app) -> None:
        raise RuntimeError("scheduler startup failed")

    monkeypatch.setattr(lifecycle, "_start_services", failed_start)
    with pytest.raises(RuntimeError, match="scheduler startup failed"):
        await lifecycle.start_application(app)

    app.post_turn_memory.stop.assert_awaited_once()
    app.database.close.assert_awaited_once()


async def test_occupied_api_port_still_stops_memory_and_closes_database(monkeypatch) -> None:
    monkeypatch.setattr(lifecycle, "create_api_app", lambda **kwargs: FastAPI())
    monkeypatch.setattr(lifecycle, "enable_db_logging", lambda logs: None)
    monkeypatch.setattr(lifecycle, "disable_db_logging", lambda: None)
    app = _partly_started_app()
    app.database.initialize = AsyncMock()
    app.storage = SimpleNamespace(logs=object())
    app.api_app = None
    for name in (
        "agent",
        "msg_hub",
        "web_adapter",
        "tool_registry",
        "monitor",
        "identity_service",
        "settings_service",
    ):
        setattr(app, name, None)

    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        port = occupied.getsockname()[1]
        app.config = SimpleNamespace(
            api=SimpleNamespace(enabled=True, host="127.0.0.1", port=port),
            log=SimpleNamespace(level="ERROR"),
        )

        with pytest.raises(RuntimeError, match="API server failed to start") as failure:
            await lifecycle.start_application(app)

    assert isinstance(failure.value.__cause__, RuntimeError)
    assert "status 1" in str(failure.value.__cause__)
    app.post_turn_memory.stop.assert_awaited_once()
    app.database.close.assert_awaited_once()
    assert app.api_task is None
    assert app.api_server is None


async def test_shutdown_cancels_memory_work_before_database_close_and_continues_on_error() -> None:
    app = _partly_started_app()
    compress_started = asyncio.Event()
    compress_cancelled = asyncio.Event()

    async def compress(_conversation_id: str) -> None:
        compress_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            compress_cancelled.set()
            raise

    memory = PostTurnMemory(
        SimpleNamespace(maybe_compress=compress, sync_memory_after_turn=AsyncMock())
    )
    app.post_turn_memory = memory
    app.scheduler = SimpleNamespace(stop=AsyncMock(side_effect=RuntimeError("scheduler error")))

    async def close_database() -> None:
        assert compress_cancelled.is_set()
        assert memory.task_for("conv-1") is None

    app.database.close = AsyncMock(side_effect=close_database)
    memory.schedule("conv-1")
    await asyncio.wait_for(compress_started.wait(), timeout=0.5)

    with pytest.raises(ExceptionGroup, match="Application shutdown failed") as failure:
        await lifecycle.stop_application(app)

    assert any("scheduler error" in str(error) for error in failure.value.exceptions)
    app.database.close.assert_awaited_once()
    with pytest.raises(RuntimeError, match="stopping"):
        memory.schedule("conv-2")


async def test_optional_adapter_failed_start_releases_partial_resources(monkeypatch) -> None:
    adapter = SimpleNamespace(
        start=AsyncMock(side_effect=RuntimeError("connection failed")),
        stop=AsyncMock(),
    )
    monkeypatch.setattr(lifecycle, "TelegramAdapter", lambda *args: adapter)
    hub = MsgHub(EventBus())
    app = SimpleNamespace(
        config=SimpleNamespace(
            telegram=SimpleNamespace(enabled=True, missing_required_env_vars=lambda: [])
        ),
        msg_hub=hub,
        telegram=None,
        api_app=None,
    )

    await lifecycle.start_telegram(app)

    adapter.stop.assert_awaited_once()
    assert hub.get_adapter("telegram") is None
    assert app.telegram is None
