"""Management mutations cannot race a staged import or an application replacement."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from src.agent.coordination import UserExecutionCoordinator
from src.desktop.access import DesktopAuthentication
from src.desktop.service import pause_for_restart

AUTH = {"Authorization": "Bearer synthetic-maintenance-token"}


@pytest.fixture
def api():
    app = FastAPI()
    app.state.application = SimpleNamespace(restart_requested=False)
    app.state.execution_coordinator = UserExecutionCoordinator()
    app.state.started = asyncio.Event()
    app.state.release = asyncio.Event()
    app.state.writes = 0

    @app.post("/api/write")
    async def write():
        app.state.started.set()
        await app.state.release.wait()
        app.state.writes += 1
        return {"saved": True}

    @app.post("/api/desktop/transition")
    async def transition():
        if not pause_for_restart(app):
            raise HTTPException(409, "busy")
        app.state.desktop_import_in_progress = True
        return {"paused": True}

    @app.get("/api/read")
    async def read():
        return {"writes": app.state.writes}

    app.add_middleware(
        DesktopAuthentication,
        token="synthetic-maintenance-token",
        origins=[],
        is_configured=lambda: True,
    )
    return app


async def test_waits_for_existing_management_write_and_denies_later_writes(api):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="http://127.0.0.1", headers=AUTH
    ) as client:
        writing = asyncio.create_task(client.post("/api/write"))
        await api.state.started.wait()
        assert (await client.post("/api/desktop/transition")).status_code == 409
        assert api.state.execution_coordinator.accepting
        api.state.release.set()
        assert (await writing).status_code == 200
        assert (await client.post("/api/desktop/transition")).status_code == 200
        assert not api.state.execution_coordinator.accepting
        assert (await client.post("/api/write")).status_code == 409
        assert (await client.get("/api/read")).json() == {"writes": 1}
        assert api.state.desktop_mutations == 0


@pytest.mark.parametrize("flag", ["desktop_import_in_progress", "desktop_update_in_progress"])
async def test_transition_refuses_other_settings_grants_and_chat_admission(api, flag):
    setattr(api.state, flag, True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="http://127.0.0.1", headers=AUTH
    ) as client:
        for path in (
            "/api/desktop/permissions",
            "/api/tools/bash/config",
            "/api/desktop/transition",
        ):
            assert (await client.post(path)).status_code == 409
        assert (await client.get("/api/read")).status_code == 200
    assert not pause_for_restart(api)


def test_restart_and_qr_login_are_part_of_transition_exclusion(api):
    api.state.application.restart_requested = True
    assert not pause_for_restart(api)
    api.state.application.restart_requested = False
    api.state.desktop_service = SimpleNamespace(wechat_login=SimpleNamespace(active=True))
    assert not pause_for_restart(api)
    api.state.desktop_service.wechat_login.active = False
    assert pause_for_restart(api)
