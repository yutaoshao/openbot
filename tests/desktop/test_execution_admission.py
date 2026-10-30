from __future__ import annotations

import asyncio

import pytest

from src.agent.coordination import UserExecutionCoordinator


async def test_restart_admission_includes_queued_work_and_cleans_cancelled_waiter() -> None:
    coordinator = UserExecutionCoordinator()
    entered = asyncio.Event()

    async def waiting() -> None:
        async with coordinator.serialize("user"):
            entered.set()

    async with coordinator.serialize("user"):
        queued = asyncio.create_task(waiting())
        await asyncio.sleep(0)
        assert coordinator.busy
        assert not coordinator.pause_if_idle()
        assert coordinator.accepting
        queued.cancel()
        await asyncio.gather(queued, return_exceptions=True)
        assert coordinator.busy and not entered.is_set()
    assert not coordinator.busy
    assert coordinator.pause_if_idle()
    with pytest.raises(RuntimeError, match="not accepting"):
        async with coordinator.serialize("user"):
            pytest.fail("No execution may enter after the idle gate closes")
    coordinator.resume()
    async with coordinator.serialize("user"):
        assert coordinator.busy
    assert not coordinator.busy


async def test_shutdown_waits_for_cross_entry_cleanup_and_cancels_queued_work() -> None:
    coordinator = UserExecutionCoordinator()
    entered, cleanup_started, allow_cleanup = asyncio.Event(), asyncio.Event(), asyncio.Event()
    queued_entered = False

    async def active_channel() -> None:
        async with coordinator.serialize("user"):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleanup_started.set()
                await allow_cleanup.wait()

    async def queued_schedule() -> None:
        nonlocal queued_entered
        async with coordinator.serialize("user"):
            queued_entered = True

    active = asyncio.create_task(active_channel())
    await entered.wait()
    queued = asyncio.create_task(queued_schedule())
    await asyncio.sleep(0)
    shutdown = asyncio.create_task(coordinator.stop_all())
    await cleanup_started.wait()
    assert not coordinator.accepting and not shutdown.done()
    allow_cleanup.set()
    await asyncio.wait_for(shutdown, 1)
    assert active.done() and queued.done() and not queued_entered
    assert not coordinator.busy
