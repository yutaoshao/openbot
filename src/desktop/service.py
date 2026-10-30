"""Bind desktop policy to the shared API without changing source deployments."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.desktop.access import DesktopAuthentication
from src.desktop.maintenance import (
    login_in_progress,
    maintenance_in_progress,
    other_management_writes,
)
from src.desktop.settings import EXECUTION_TOOLS, DesktopSettings, DesktopSettingsService

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any

    from fastapi import FastAPI

    from src.tools.registry import ToolRegistry


class DesktopService:
    def __init__(self, settings: DesktopSettings, *, token: str, runtime: Path) -> None:
        self.settings = settings
        self.runtime = runtime
        self._token = token

    def install_api(self, api: FastAPI) -> None:
        from src.desktop.import_routes import router as import_router
        from src.desktop.routes import router
        from src.desktop.service_routes import router as services_router
        from src.desktop.update_routes import router as update_router

        application = api.state.application
        state = self.settings.read()
        application.tool_registry.configure_execution_permissions(
            {name: state.permissions.get(name, False) for name in ("bash", "code_executor")}
        )
        for name, enabled in state.tool_enabled.items():
            if application.tool_registry.get(name) is not None:
                allowed = name not in EXECUTION_TOOLS or state.permissions.get(name, False)
                application.tool_registry.update_config(name, {"enabled": enabled and allowed})
        if not state.configured:
            application.execution_coordinator.pause_if_idle()
        api.state.desktop_service = self
        api.state.settings_service = DesktopSettingsService(application.config_path, self.settings)
        api.include_router(router)
        api.include_router(import_router)
        api.include_router(services_router)
        api.include_router(update_router)
        api.add_middleware(
            DesktopAuthentication,
            token=self._token,
            origins=api.state.config.api.cors_origins,
            is_configured=lambda: self.settings.read().configured,
        )

    def update_tool_config(
        self, registry: ToolRegistry, name: str, updates: dict[str, Any]
    ) -> dict:
        if registry.get(name) is None:
            raise KeyError(name)
        state = self.settings.read()
        if updates.get("enabled") and name in EXECUTION_TOOLS and not state.permissions.get(name):
            raise PermissionError("Explicit current-user execution authorization is required.")
        if "enabled" in updates:
            enabled = {**state.tool_enabled, name: bool(updates["enabled"])}
            self.settings.save(state.model_copy(update={"tool_enabled": enabled}))
        return registry.update_config(name, updates)


def is_busy(api: FastAPI) -> bool:
    runs = getattr(api.state, "chat_runs", None)
    return bool(runs and runs.busy) or api.state.execution_coordinator.busy


def pause_for_restart(api: FastAPI) -> bool:
    """Runs reserve synchronously before their task enters the shared coordinator."""
    return (
        not maintenance_in_progress(api)
        and not login_in_progress(api)
        and not other_management_writes(api)
        and not is_busy(api)
        and api.state.execution_coordinator.pause_if_idle()
    )
