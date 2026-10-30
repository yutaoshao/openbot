from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import WebSocket  # noqa: TC002 - FastAPI resolves this annotation at registration.
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.agent.coordination import UserExecutionCoordinator
from src.api import create_api_app
from src.application.runtime import RuntimeEnvironment
from src.core.config import AppConfig
from src.desktop.service import DesktopService
from src.desktop.settings import DesktopSettings
from src.tools.builtin import BashTool, CodeExecutorTool
from src.tools.registry import ToolRegistry

TOKEN = "synthetic-desktop-token-32-characters-long"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def desktop_api(tmp_path):
    settings = DesktopSettings(tmp_path / "application")
    registry = ToolRegistry()
    registry.register(BashTool(root=tmp_path))
    registry.register(CodeExecutorTool(root=tmp_path))
    config = AppConfig(telegram={"enabled": False})
    service = DesktopService(settings, token=TOKEN, runtime=tmp_path / "runtime")
    application = SimpleNamespace(
        config_path=str(settings.data_dir / "config.yaml"),
        runtime=RuntimeEnvironment(configure_api=service.install_api),
        execution_coordinator=UserExecutionCoordinator(),
        tool_registry=registry,
        request_restart=AsyncMock(),
    )
    api = create_api_app(config=config, application=application, tool_registry=registry)
    api.state.chat_runs = SimpleNamespace(busy=False, stop_all=AsyncMock())
    return api, service, application


async def test_instance_auth_and_origin_protect_shared_http_routes(desktop_api) -> None:
    api, _, _ = desktop_api
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="http://127.0.0.1"
    ) as c:
        assert (await c.get("/api/desktop/status")).status_code == 401
        assert (
            await c.get("/health", headers={"Authorization": "Bearer other-instance"})
        ).status_code == 401
        assert (
            await c.get("/health", headers={**AUTH, "Origin": "https://untrusted.invalid"})
        ).status_code == 403
        response = await c.get("/api/desktop/status", headers=AUTH)
        assert response.status_code == 200
        assert response.json()["permissions"] == {"bash": False, "code_executor": False}
        assert "api_key" not in response.json()["model"]
        assert (
            await c.post("/api/chat", headers=AUTH, json={"message": "hello"})
        ).status_code == 409


def test_unauthenticated_websocket_cannot_bypass_http_guard(desktop_api) -> None:
    api, _, _ = desktop_api
    with TestClient(api) as client:
        with pytest.raises(WebSocketDisconnect) as exc, client.websocket_connect("/api/ws/chat"):
            pytest.fail("Unauthenticated websocket must not be accepted")
        assert exc.value.code == 1008


async def test_only_explicit_grant_can_enable_execution_and_revoke_persists(desktop_api) -> None:
    api, service, app = desktop_api
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="http://127.0.0.1", headers=AUTH
    ) as c:
        assert (await c.put("/api/tools/bash/config", json={"enabled": True})).status_code == 403
        assert (
            await c.post("/api/desktop/permissions", json={"tool": "bash", "authorized": True})
        ).status_code == 422
        response = await c.post(
            "/api/desktop/permissions",
            json={
                "tool": "bash",
                "authorized": True,
                "acknowledgement": "current-user-permissions",
            },
        )
        assert response.status_code == 200
        assert app.tool_registry.is_execution_allowed("bash")
        assert service.settings.read().permissions["bash"]
        await c.post(
            "/api/desktop/permissions",
            json={
                "tool": "bash",
                "authorized": False,
                "acknowledgement": "current-user-permissions",
            },
        )
        assert not app.tool_registry.is_execution_allowed("bash")
        assert not service.settings.read().permissions["bash"]


async def test_disabled_authorized_tool_stays_disabled_after_service_recreation(
    desktop_api,
) -> None:
    api, service, application = desktop_api
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="http://127.0.0.1", headers=AUTH
    ) as client:
        await client.post(
            "/api/desktop/permissions",
            json={
                "tool": "bash",
                "authorized": True,
                "acknowledgement": "current-user-permissions",
            },
        )
        response = await client.put("/api/tools/bash/config", json={"enabled": False})
        assert response.status_code == 200
    assert service.settings.read().permissions["bash"]
    assert not service.settings.read().tool_enabled["bash"]
    replacement = ToolRegistry()
    replacement.register(BashTool(root=service.settings.data_dir))
    replacement.register(CodeExecutorTool(root=service.settings.data_dir))
    application.tool_registry = replacement
    create_api_app(config=api.state.config, application=application, tool_registry=replacement)
    assert not replacement.is_execution_allowed("bash")
    assert next(item for item in replacement.list_status() if item["name"] == "bash")["authorized"]


async def test_setup_refuses_busy_runs_without_mutating_saved_state(desktop_api) -> None:
    api, service, app = desktop_api
    previous = service.settings.path.read_bytes()
    api.state.chat_runs.busy = True
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="http://127.0.0.1", headers=AUTH
    ) as c:
        response = await c.post(
            "/api/desktop/setup",
            json={
                "model": {
                    "provider": "openai_compatible",
                    "model": "test",
                    "base_url": "http://127.0.0.1:12345/v1",
                },
                "work_dir": service.settings.read().work_dir,
            },
        )
        assert response.status_code == 409
    assert service.settings.path.read_bytes() == previous
    app.request_restart.assert_not_awaited()


async def test_setup_closes_admission_before_publishing_restart(desktop_api) -> None:
    api, service, app = desktop_api
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="http://127.0.0.1", headers=AUTH
    ) as c:
        response = await c.post(
            "/api/desktop/setup",
            json={
                "model": {
                    "provider": "openai_compatible",
                    "model": "test",
                    "base_url": "http://127.0.0.1:12345/v1",
                },
                "work_dir": service.settings.read().work_dir,
            },
        )
        assert response.status_code == 200 and response.json()["requires_restart"]
        assert not app.execution_coordinator.accepting
        assert service.settings.read().configured
        app.request_restart.assert_awaited_once()


async def test_browser_validation_never_sets_or_accepts_cross_port_cookies(desktop_api) -> None:
    api, _, _ = desktop_api
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="http://127.0.0.1"
    ) as client:
        assert (await client.post("/api/desktop/browser-session")).status_code == 401
        response = await client.post("/api/desktop/browser-session", headers=AUTH)
        assert response.status_code == 200 and TOKEN not in response.text
        assert "set-cookie" not in response.headers
        response = await client.get(
            "/api/desktop/status", headers={"Cookie": f"openbot_desktop_session={TOKEN}"}
        )
        assert response.status_code == 401
        assert response.headers["X-OpenBot-Desktop"] == "1"
        assert (
            await client.get(
                "/api/desktop/status", headers={**AUTH, "Origin": "https://untrusted.invalid"}
            )
        ).status_code == 403


@pytest.mark.parametrize("headers", [AUTH, {**AUTH, "Origin": "https://untrusted.invalid"}])
def test_real_chat_websocket_rejects_unconfigured_or_wrong_origin(desktop_api, headers) -> None:
    api, _, _ = desktop_api
    with TestClient(api) as client:
        with (
            pytest.raises(WebSocketDisconnect) as exc,
            client.websocket_connect("/api/ws/chat", headers=headers),
        ):
            pytest.fail("Unconfigured or wrong-origin chat must not enter the shared WS route")
        assert exc.value.code == 1008


def test_browser_websocket_auth_uses_subprotocol_and_keeps_credential_out_of_url(
    desktop_api,
) -> None:
    api, _, _ = desktop_api

    @api.websocket("/api/ws/access-check")
    async def access_check(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_json({"connected": True})
        await websocket.close()

    with (
        TestClient(api) as client,
        client.websocket_connect(
            "/api/ws/access-check", subprotocols=[f"openbot.auth.{TOKEN}"]
        ) as websocket,
    ):
        assert websocket.receive_json() == {"connected": True}
