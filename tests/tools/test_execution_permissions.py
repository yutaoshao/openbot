from __future__ import annotations

import asyncio

import httpx
import pytest

from src.agent.runtime.tool_executor import execute_tool_call
from src.api.app import create_api_app
from src.core.config import AgentConfig
from src.tools.hooks import PreToolHookResult, ToolHookManager
from src.tools.registry import ToolRegistry, ToolResult


class _Tool:
    name = "bash"
    description = "synthetic execution tool"
    category = "execution"
    parameters = {"type": "object", "properties": {}}

    def __init__(self):
        self.calls = 0

    async def execute(self, _args):
        self.calls += 1
        return ToolResult("executed")


async def _call(registry, hooks=None, platform="web"):
    return await execute_tool_call(
        registry,
        AgentConfig(),
        hooks or ToolHookManager(),
        "bash",
        {},
        conversation_id="conv",
        platform=platform,
    )


@pytest.mark.parametrize("platform", ["web", "telegram", "wechat", "scheduler"])
async def test_execution_permission_is_checked_even_for_direct_old_tool_calls(platform) -> None:
    registry = ToolRegistry()
    tool = _Tool()
    registry.register(tool)
    registry.configure_execution_permissions({"bash": False})
    assert registry.get_schemas() == []
    assert registry.list_status()[0]["enabled"] is False
    assert registry.list_status()[0]["authorized"] is False
    result = await _call(registry, platform=platform)
    assert result.is_error
    assert tool.calls == 0
    with pytest.raises(PermissionError):
        registry.update_config("bash", {"enabled": True})
    registry.set_execution_permission("bash", True)
    assert not (await _call(registry, platform=platform)).is_error
    assert tool.calls == 1
    registry.set_execution_permission("bash", False)
    assert (await _call(registry, platform=platform)).is_error
    assert tool.calls == 1


async def test_source_mode_preserves_default_execution_and_disabled_tools_do_not_execute() -> None:
    registry = ToolRegistry()
    tool = _Tool()
    registry.register(tool)
    assert not (await _call(registry)).is_error
    changes = {"enabled": False, "note": "example"}
    registry.update_config("bash", changes)
    assert changes == {"enabled": False, "note": "example"}
    assert (await _call(registry)).is_error
    assert tool.calls == 1


async def test_revocation_during_before_hook_is_checked_before_tool_side_effect() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class Hook:
        async def before_execute(self, *_args):
            entered.set()
            await release.wait()
            return PreToolHookResult()

    registry = ToolRegistry()
    tool = _Tool()
    registry.register(tool)
    registry.configure_execution_permissions({"bash": True})
    task = asyncio.create_task(_call(registry, ToolHookManager([Hook()])))
    await entered.wait()
    registry.set_execution_permission("bash", False)
    release.set()
    assert (await task).is_error
    assert tool.calls == 0


async def test_plain_management_config_cannot_grant_desktop_authorization() -> None:
    registry = ToolRegistry()
    registry.register(_Tool())
    registry.configure_execution_permissions({"bash": False})
    app = create_api_app(tool_registry=registry)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 12345)),
        base_url="http://127.0.0.1",
    ) as client:
        listed = (await client.get("/api/tools")).json()[0]
        assert listed["requires_authorization"] is True
        assert listed["authorized"] is False
        denied = await client.put("/api/tools/bash/config", json={"enabled": True})
        assert denied.status_code == 403
        nested = await client.put("/api/tools/bash/config", json={"config": {"enabled": True}})
        assert nested.status_code == 403
        assert not registry.is_execution_allowed("bash")


async def test_desktop_tool_route_uses_persistence_owner_and_never_falls_back_on_failure():
    class DesktopService:
        def __init__(self):
            self.calls = []

        def update_tool_config(self, registry, name, updates):
            self.calls.append((name, dict(updates)))
            raise OSError("synthetic persistence failure")

    registry = ToolRegistry()
    registry.register(_Tool())
    service = DesktopService()
    app = create_api_app(tool_registry=registry)
    app.state.desktop_service = service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=app, client=("127.0.0.1", 12345), raise_app_exceptions=False
        ),
        base_url="http://127.0.0.1",
    ) as client:
        response = await client.put("/api/tools/bash/config", json={"enabled": False})
        assert response.status_code == 500
    assert service.calls == [("bash", {"enabled": False})]
    assert registry.is_execution_allowed("bash")
