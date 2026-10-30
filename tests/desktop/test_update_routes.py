"""The update transition shares chat/channel/schedule admission and owns a lease."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from src.agent.coordination import UserExecutionCoordinator
from src.desktop.access import DesktopAuthentication
from src.desktop.update_routes import router

LEASE = "a" * 64
AUTH = {"Authorization": "Bearer synthetic-update-token"}


@pytest.fixture
def update_api():
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(
        DesktopAuthentication,
        token="synthetic-update-token",
        origins=[],
        is_configured=lambda: True,
    )
    app.state.execution_coordinator = UserExecutionCoordinator()
    app.state.chat_runs = SimpleNamespace(busy=False)
    return app


async def test_update_transition_requires_instance_authentication(update_api):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=update_api), base_url="http://127.0.0.1"
    ) as client:
        response = await client.post("/api/desktop/update/prepare", json={"lease": LEASE})
    assert response.status_code == 401
    assert update_api.state.execution_coordinator.accepting


async def test_busy_runs_keep_admission_open_and_do_not_create_lease(update_api):
    update_api.state.chat_runs.busy = True
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=update_api), base_url="http://127.0.0.1", headers=AUTH
    ) as client:
        response = await client.post("/api/desktop/update/prepare", json={"lease": LEASE})
    assert response.status_code == 409
    assert update_api.state.execution_coordinator.accepting
    assert not getattr(update_api.state, "desktop_update_in_progress", False)


async def test_any_shared_execution_blocks_install(update_api):
    async with (
        update_api.state.execution_coordinator.serialize("user"),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=update_api), base_url="http://127.0.0.1", headers=AUTH
        ) as client,
    ):
        response = await client.post("/api/desktop/update/prepare", json={"lease": LEASE})
    assert response.status_code == 409


async def test_prepare_closes_admission_and_only_matching_lease_resumes(update_api):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=update_api), base_url="http://127.0.0.1", headers=AUTH
    ) as client:
        response = await client.post("/api/desktop/update/prepare", json={"lease": LEASE})
        assert response.json() == {"status": "prepared", "lease": LEASE}
        assert not update_api.state.execution_coordinator.accepting
        assert update_api.state.desktop_update_in_progress
        wrong = await client.post("/api/desktop/update/resume", json={"lease": "b" * 64})
        assert wrong.status_code == 409
        assert not update_api.state.execution_coordinator.accepting
        restored = await client.post("/api/desktop/update/resume", json={"lease": LEASE})
        assert restored.status_code == 200
        assert update_api.state.execution_coordinator.accepting
        assert not update_api.state.desktop_update_in_progress
        assert (
            await client.post("/api/desktop/update/resume", json={"lease": LEASE})
        ).status_code == 409


async def test_prepare_rejects_invalid_transition_id_without_changing_admission(update_api):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=update_api), base_url="http://127.0.0.1", headers=AUTH
    ) as client:
        for value in [None, "short", "g" * 64]:
            response = await client.post("/api/desktop/update/prepare", json={"lease": value})
            assert response.status_code == 422
    assert update_api.state.execution_coordinator.accepting
