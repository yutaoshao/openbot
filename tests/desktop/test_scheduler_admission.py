from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx

from src.agent.coordination import UserExecutionCoordinator
from src.agent.scheduling import AgentScheduler
from src.api import create_api_app
from src.application.runtime import RuntimeEnvironment
from src.core.config import AppConfig
from src.desktop.service import DesktopService
from src.desktop.settings import DesktopSettings
from src.tools.builtin import BashTool, CodeExecutorTool
from src.tools.registry import ToolRegistry


def _scheduler(coordinator, agent):
    row = {
        "id": "synthetic",
        "name": "test",
        "status": "active",
        "prompt": "test",
        "cron": "0 8 * * *",
    }
    repo = SimpleNamespace(get=AsyncMock(return_value=row), update=AsyncMock())
    return AgentScheduler(
        SimpleNamespace(schedules=repo),
        agent,
        SimpleNamespace(publish=AsyncMock()),
        SimpleNamespace(),
        execution_coordinator=coordinator,
    )


async def test_paused_scheduler_does_not_enter_agent_or_deliver() -> None:
    coordinator = UserExecutionCoordinator()
    agent = SimpleNamespace(run=AsyncMock())
    scheduler = _scheduler(coordinator, agent)
    assert coordinator.pause_if_idle()
    await scheduler._execute_schedule("synthetic")
    agent.run.assert_not_awaited()


async def test_running_schedule_blocks_setup_and_apply_and_is_reported_busy(tmp_path) -> None:
    coordinator = UserExecutionCoordinator()
    entered, release = asyncio.Event(), asyncio.Event()

    async def run(**_kwargs):
        entered.set()
        await release.wait()
        return SimpleNamespace(content="synthetic result", latency_ms=1)

    scheduler = _scheduler(coordinator, SimpleNamespace(run=run))
    settings = DesktopSettings(tmp_path / "application")
    service = DesktopService(settings, token="a" * 64, runtime=tmp_path / "runtime")
    registry = ToolRegistry()
    registry.register(BashTool(root=tmp_path))
    registry.register(CodeExecutorTool(root=tmp_path))
    application = SimpleNamespace(
        config_path=str(settings.data_dir / "config.yaml"),
        runtime=RuntimeEnvironment(configure_api=service.install_api),
        execution_coordinator=coordinator,
        tool_registry=registry,
        request_restart=AsyncMock(),
    )
    api = create_api_app(config=AppConfig(), application=application)
    coordinator.resume()
    running = asyncio.create_task(scheduler._execute_schedule("synthetic"))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api),
            base_url="http://127.0.0.1",
            headers={"Authorization": f"Bearer {'a' * 64}"},
        ) as client:
            assert (await client.get("/api/desktop/status")).json()["busy"]
            response = await client.post(
                "/api/desktop/setup",
                json={
                    "model": {
                        "provider": "openai_compatible",
                        "base_url": "http://127.0.0.1:12345/v1",
                        "model": "test",
                    },
                    "work_dir": settings.read().work_dir,
                },
            )
            assert response.status_code == 409
            assert (await client.post("/api/settings/apply")).status_code == 409
            application.request_restart.assert_not_awaited()
    finally:
        release.set()
        await asyncio.wait_for(running, 1)
    assert not coordinator.busy
